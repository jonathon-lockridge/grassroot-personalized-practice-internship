"""Checks for remembering students between sessions (step T5).

Every test uses its own new file in a temporary folder (pytest's `tmp_path`), so
nothing here touches a real saved file.
"""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from practice_engine.mastery import new_mastery_state, update_mastery
from practice_engine.models import Course, StepAnswer, load_course
from practice_engine.selection import MissedStep, Pick
from practice_engine.storage import (
    check_saved_answers,
    forget_student,
    list_students,
    load_history,
    load_mastery,
    load_picks,
    open_storage,
    save_answer,
    save_picks,
)

COURSE = (
    Path(__file__).resolve().parents[1] / "data" / "ap-physics-c-energy-momentum" / "course.json"
)

# Problem push_cart: step 1 is choose_principle, step 2 work_constant_force,
# step 3 kinetic_energy.
START_TIME = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)


@pytest.fixture
def course() -> Course:
    return load_course(COURSE)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "practice.sqlite"


def answer(
    position: int,
    correct: bool,
    nickname: str = "sam",
    minute: int = 0,
    attempt: int = 1,
    hints_used: int = 0,
    problem_id: str = "push_cart",
) -> StepAnswer:
    """A step answer on push_cart (by default), `minute` minutes after 10:00 UTC."""
    return StepAnswer(
        nickname=nickname,
        problem_id=problem_id,
        step_position=position,
        correct=correct,
        seconds=20,
        hints_used=hints_used,
        answered_at=START_TIME + timedelta(minutes=minute),
        attempt=attempt,
    )


def some_answers() -> list[StepAnswer]:
    """A short session: right, wrong then right on a second try, right after a hint."""
    return [
        answer(1, True, minute=0),
        answer(2, False, minute=1),
        answer(2, True, minute=2, attempt=2),
        answer(3, True, minute=3, hints_used=1),
    ]


def test_closing_and_reopening_keeps_mastery(course: Course, path: Path) -> None:
    live = new_mastery_state(course, "sam")
    with closing(open_storage(path)) as db:
        for step_answer in some_answers():
            save_answer(db, course, step_answer)
            live = update_mastery(live, step_answer, course)

    with closing(open_storage(path)) as db:
        assert load_mastery(db, course, "sam") == live
        assert load_history(db, course, "sam") == some_answers()


def test_replaying_saved_answers_gives_exactly_the_live_state(course: Course, path: Path) -> None:
    # A longer, mixed history over several problems: the rebuilt state must match
    # the one built answer by answer, number for number.
    history = [
        answer(1, True, minute=0),
        answer(2, False, minute=1),
        answer(3, True, minute=2, hints_used=2),
        answer(1, False, minute=10, problem_id="drag_crate"),
        answer(1, True, minute=11, problem_id="drag_crate", attempt=2),
        answer(2, True, minute=12, problem_id="drag_crate"),
    ]
    live = new_mastery_state(course, "sam")
    with closing(open_storage(path)) as db:
        for step_answer in history:
            save_answer(db, course, step_answer)
            live = update_mastery(live, step_answer, course)
        assert load_mastery(db, course, "sam") == live


def test_a_new_student_gets_the_starting_state(course: Course, path: Path) -> None:
    with closing(open_storage(path)) as db:
        assert load_mastery(db, course, "newcomer") == new_mastery_state(course, "newcomer")
        assert load_history(db, course, "newcomer") == []


def test_the_same_answer_sent_twice_is_stored_once(course: Course, path: Path) -> None:
    with closing(open_storage(path)) as db:
        assert save_answer(db, course, answer(1, True)) is True
        assert save_answer(db, course, answer(1, True)) is False
        assert load_history(db, course, "sam") == [answer(1, True)]
        (rows,) = db.execute("SELECT COUNT(*) FROM answers").fetchone()
        assert rows == 1


def test_a_second_try_is_not_a_duplicate(course: Course, path: Path) -> None:
    with closing(open_storage(path)) as db:
        save_answer(db, course, answer(2, False, minute=1))
        assert save_answer(db, course, answer(2, True, minute=1, attempt=2)) is True
        assert len(load_history(db, course, "sam")) == 2


def test_a_clashing_answer_with_the_same_identity_is_refused(course: Course, path: Path) -> None:
    # Same student, problem, step, try and time, but now marked wrong: one of the two
    # is a mistake, so it is refused instead of quietly keeping either.
    with closing(open_storage(path)) as db:
        save_answer(db, course, answer(1, True))
        with pytest.raises(ValueError, match="already saved"):
            save_answer(db, course, answer(1, False))
        assert load_history(db, course, "sam") == [answer(1, True)]


def test_history_comes_back_oldest_first_and_equal_times_in_saving_order(
    course: Course, path: Path
) -> None:
    late = answer(3, True, minute=5)
    first = answer(1, True, minute=0)
    same_time_a = answer(2, False, minute=2)
    same_time_b = answer(2, True, minute=2, attempt=2)
    with closing(open_storage(path)) as db:
        for step_answer in (late, same_time_a, same_time_b, first):
            save_answer(db, course, step_answer)
        assert load_history(db, course, "sam") == [first, same_time_a, same_time_b, late]


def test_times_are_stored_in_utc_and_read_back_as_the_same_moment(
    course: Course, path: Path
) -> None:
    new_york = timezone(timedelta(hours=-5))
    local = answer(1, True).model_copy(
        update={"answered_at": datetime(2026, 11, 20, 5, 0, tzinfo=new_york)}
    )
    with closing(open_storage(path)) as db:
        save_answer(db, course, local)
        (stored,) = db.execute("SELECT answered_at FROM answers").fetchone()
        (loaded,) = load_history(db, course, "sam")
    assert stored == "2026-11-20T10:00:00.000000+00:00"
    assert loaded.answered_at == START_TIME
    assert loaded.answered_at.tzinfo == UTC


def test_a_time_without_a_time_zone_is_refused(course: Course, path: Path) -> None:
    naive = answer(1, True).model_copy(update={"answered_at": datetime(2026, 11, 20, 10, 0)})
    with closing(open_storage(path)) as db:
        with pytest.raises(ValueError, match="time zone"):
            save_answer(db, course, naive)
        assert load_history(db, course, "sam") == []


def test_an_answer_to_a_step_the_course_lacks_is_refused(course: Course, path: Path) -> None:
    with closing(open_storage(path)) as db:
        with pytest.raises(ValueError, match="no step 9"):
            save_answer(db, course, answer(9, True))
        with pytest.raises(ValueError, match="no problem"):
            save_answer(db, course, answer(1, True, problem_id="not_a_problem"))


def test_each_answer_row_keeps_the_course_the_skill_and_the_given_answer(
    course: Course, path: Path
) -> None:
    with closing(open_storage(path)) as db:
        save_answer(db, course, answer(2, True), given="1200")
        save_answer(db, course, answer(3, True, minute=1))
        rows = db.execute(
            "SELECT course_id, skill_id, given FROM answers ORDER BY step_position"
        ).fetchall()
    assert rows == [
        (course.id, "work_constant_force", "1200"),
        (course.id, "kinetic_energy", None),
    ]


def test_a_course_edit_that_moves_a_step_to_another_skill_is_noticed(
    course: Course, path: Path
) -> None:
    with closing(open_storage(path)) as db:
        save_answer(db, course, answer(2, True))
        assert check_saved_answers(db, course) == []

        edited = course.model_copy(deep=True)
        edited.problems[0].steps[1].skill = "kinetic_energy"  # push_cart step 2
        complaints = check_saved_answers(db, edited)
        assert len(complaints) == 1
        assert "push_cart" in complaints[0] and "work_constant_force" in complaints[0]

        # Like the rest of the engine, mastery skips the answer that no longer fits
        # instead of stopping, so the student is not locked out.
        assert load_mastery(db, edited, "sam") == new_mastery_state(edited, "sam")


def test_a_course_edit_that_removes_a_step_is_noticed(course: Course, path: Path) -> None:
    with closing(open_storage(path)) as db:
        save_answer(db, course, answer(3, True))
        edited = course.model_copy(deep=True)
        edited.problems[0].steps.pop()  # push_cart loses step 3
        assert len(check_saved_answers(db, edited)) == 1
        assert load_mastery(db, edited, "sam") == new_mastery_state(edited, "sam")


def test_mastery_still_counts_the_answers_that_fit_after_a_course_edit(
    course: Course, path: Path
) -> None:
    with closing(open_storage(path)) as db:
        save_answer(db, course, answer(2, True))
        save_answer(db, course, answer(3, True, minute=1))
        edited = course.model_copy(deep=True)
        edited.problems[0].steps[1].skill = "kinetic_energy"  # push_cart step 2 moves
        expected = update_mastery(
            new_mastery_state(edited, "sam"), answer(3, True, minute=1), edited
        )
        assert load_mastery(db, edited, "sam") == expected


def test_a_seconds_value_that_is_not_a_number_is_refused(course: Course, path: Path) -> None:
    broken = answer(1, True).model_copy(update={"seconds": float("nan")})
    with closing(open_storage(path)) as db:
        with pytest.raises(ValueError, match="seconds"):
            save_answer(db, course, broken)
        assert load_history(db, course, "sam") == []


def test_replay_follows_answer_time_not_the_order_answers_arrived(
    course: Course, path: Path
) -> None:
    # The rule: the time on each answer decides the order. An answer that arrives
    # late but carries an earlier time is replayed in its time order.
    early, late = answer(1, True, minute=0), answer(2, False, minute=5)
    with closing(open_storage(path)) as db:
        save_answer(db, course, late)
        save_answer(db, course, early)
        expected = new_mastery_state(course, "sam")
        for step_answer in (early, late):
            expected = update_mastery(expected, step_answer, course)
        assert load_history(db, course, "sam") == [early, late]
        assert load_mastery(db, course, "sam") == expected


def test_list_students_names_each_student_once(course: Course, path: Path) -> None:
    with closing(open_storage(path)) as db:
        assert list_students(db) == []
        save_answer(db, course, answer(1, True, nickname="zoe"))
        save_answer(db, course, answer(2, True, nickname="zoe", minute=1))
        save_answer(db, course, answer(1, True, nickname="ali"))
        assert list_students(db) == ["ali", "zoe"]
        assert list_students(db, course.id) == ["ali", "zoe"]
        assert list_students(db, "another-course") == []


def test_a_student_with_only_picks_is_listed(course: Course, path: Path) -> None:
    with closing(open_storage(path)) as db:
        save_picks(db, course, "ghost", a_batch(), START_TIME)
        assert list_students(db) == ["ghost"]


def a_batch() -> list[Pick]:
    return [
        Pick(
            problem_id="drag_crate",
            reason="Picked for you: you missed step 2 of Push a cart.",
            is_follow_up=True,
            target_skill="work_constant_force",
            missed_step=MissedStep(problem_id="push_cart", step_position=2),
        ),
        Pick(
            problem_id="spring_launch",
            reason="New skill: Potential energy.",
            is_follow_up=False,
            target_skill="potential_energy",
        ),
    ]


def test_picks_are_saved_with_their_reasons_and_read_back_in_order(
    course: Course, path: Path
) -> None:
    later = START_TIME + timedelta(hours=1)
    with closing(open_storage(path)) as db:
        save_picks(db, course, "sam", a_batch(), START_TIME)
        save_picks(db, course, "sam", a_batch()[1:], later)
    with closing(open_storage(path)) as db:
        saved = load_picks(db, course, "sam")
    assert saved == [
        (START_TIME, a_batch()[0]),
        (START_TIME, a_batch()[1]),
        (later, a_batch()[1]),
    ]


def test_forgetting_a_student_removes_every_row_about_them(course: Course, path: Path) -> None:
    with closing(open_storage(path)) as db:
        for step_answer in some_answers():
            save_answer(db, course, step_answer)
        save_picks(db, course, "sam", a_batch(), START_TIME)
        save_answer(db, course, answer(1, True, nickname="ali"))
        save_picks(db, course, "ali", a_batch()[:1], START_TIME)

        # 1 student row + 4 answers + 2 picks.
        assert forget_student(db, "sam") == 7
        assert forget_student(db, "sam") == 0

        # No row in any table still holds "sam"; every table has a nickname column.
        tables = [
            name
            for (name,) in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        assert set(tables) == {"students", "answers", "picks"}
        for table in tables:
            # Table names come from the database itself, not from outside input.
            (left,) = db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE nickname = ?", ("sam",)
            ).fetchone()
            assert left == 0, table

        # The other student is untouched.
        assert list_students(db) == ["ali"]
        assert load_history(db, course, "ali") == [answer(1, True, nickname="ali")]
        assert len(load_picks(db, course, "ali")) == 1


def test_forgetting_is_kept_after_reopening(course: Course, path: Path) -> None:
    with closing(open_storage(path)) as db:
        save_answer(db, course, answer(1, True))
        forget_student(db, "sam")
    with closing(open_storage(path)) as db:
        assert list_students(db) == []
        assert load_history(db, course, "sam") == []


def test_odd_nicknames_are_stored_as_plain_text(course: Course, path: Path) -> None:
    # Values are passed separately from the SQL, so quotes in a nickname are just text.
    odd = "o'brien\"); DROP TABLE answers; --"
    with closing(open_storage(path)) as db:
        save_answer(db, course, answer(1, True, nickname=odd))
        assert list_students(db) == [odd]
        assert forget_student(db, odd) == 2
        db.execute("SELECT COUNT(*) FROM answers")  # the table is still there


def test_opening_the_same_file_twice_keeps_the_tables(path: Path) -> None:
    with closing(open_storage(path)):
        pass
    with closing(open_storage(path)) as db:
        assert isinstance(db, sqlite3.Connection)
