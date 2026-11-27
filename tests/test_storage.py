"""Checks for remembering students between sessions (step T5).

Every test uses its own new file in a temporary folder (pytest's `tmp_path`), so
nothing here touches a real saved file.
"""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

# The physics course with push_cart's numbers frozen (see plain_course.py).
from plain_course import COURSE

from practice_engine.mastery import new_mastery_state, update_mastery
from practice_engine.models import Course, Step, StepAnswer, fill_problem, load_course
from practice_engine.selection import MissedStep, Pick
from practice_engine.storage import (
    check_saved_answers,
    forget_student,
    list_students,
    load_history,
    load_mastery,
    load_picks,
    load_tries,
    open_storage,
    save_answer,
    save_picks,
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


def save(db: sqlite3.Connection, course: Course, step_answer: StepAnswer) -> bool:
    """Save an answer the way a truthful page would: a right answer comes with the
    step's own answer as what the student gave, a wrong one with nothing given."""
    given = None
    if step_answer.correct:
        problem = next(p for p in course.problems if p.id == step_answer.problem_id)
        given = problem.steps[step_answer.step_position - 1].answer
    return save_answer(db, course, step_answer, given=given)


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
            save(db, course, step_answer)
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
        answer(1, False, minute=10, problem_id="car_power"),
        answer(1, True, minute=11, problem_id="car_power", attempt=2),
        answer(2, True, minute=12, problem_id="car_power"),
    ]
    live = new_mastery_state(course, "sam")
    with closing(open_storage(path)) as db:
        for step_answer in history:
            save(db, course, step_answer)
            live = update_mastery(live, step_answer, course)
        assert load_mastery(db, course, "sam") == live


def test_a_new_student_gets_the_starting_state(course: Course, path: Path) -> None:
    with closing(open_storage(path)) as db:
        assert load_mastery(db, course, "newcomer") == new_mastery_state(course, "newcomer")
        assert load_history(db, course, "newcomer") == []


def test_the_same_answer_sent_twice_is_stored_once(course: Course, path: Path) -> None:
    with closing(open_storage(path)) as db:
        assert save(db, course, answer(1, True)) is True
        assert save(db, course, answer(1, True)) is False
        assert load_history(db, course, "sam") == [answer(1, True)]
        (rows,) = db.execute("SELECT COUNT(*) FROM answers").fetchone()
        assert rows == 1


def test_load_tries_gives_one_steps_tries_since_a_time_with_what_was_given(
    course: Course, path: Path
) -> None:
    with closing(open_storage(path)) as db:
        save_answer(db, course, answer(3, False, minute=0), given="9")  # before `since`
        save_answer(db, course, answer(3, False, minute=5), given="8")
        save_answer(db, course, answer(3, True, minute=6, attempt=2), given="5.48")
        save_answer(db, course, answer(2, True, minute=7), given=30)  # another step
        save_answer(db, course, answer(3, True, minute=8, nickname="lee"), given="5.5")

        tries = load_tries(db, course, "sam", "push_cart", 3, START_TIME + timedelta(minutes=5))

    assert tries == [
        (answer(3, False, minute=5), "8"),
        (answer(3, True, minute=6, attempt=2), "5.48"),
    ]


def test_a_second_try_is_not_a_duplicate(course: Course, path: Path) -> None:
    with closing(open_storage(path)) as db:
        save(db, course, answer(2, False, minute=1))
        assert save(db, course, answer(2, True, minute=1, attempt=2)) is True
        assert len(load_history(db, course, "sam")) == 2


def test_a_clashing_answer_with_the_same_identity_is_refused(course: Course, path: Path) -> None:
    # Same student, problem, step, try and time, but now marked wrong: one of the two
    # is a mistake, so it is refused instead of quietly keeping either.
    with closing(open_storage(path)) as db:
        save(db, course, answer(1, True))
        with pytest.raises(ValueError, match="already saved"):
            save(db, course, answer(1, False))
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
            save(db, course, step_answer)
        assert load_history(db, course, "sam") == [first, same_time_a, same_time_b, late]


def test_times_are_stored_in_utc_and_read_back_as_the_same_moment(
    course: Course, path: Path
) -> None:
    new_york = timezone(timedelta(hours=-5))
    local = answer(1, True).model_copy(
        update={"answered_at": datetime(2026, 11, 20, 5, 0, tzinfo=new_york)}
    )
    with closing(open_storage(path)) as db:
        save(db, course, local)
        (stored,) = db.execute("SELECT answered_at FROM answers").fetchone()
        (loaded,) = load_history(db, course, "sam")
    assert stored == "2026-11-20T10:00:00.000000+00:00"
    assert loaded.answered_at == START_TIME
    assert loaded.answered_at.tzinfo == UTC


def test_a_time_without_a_time_zone_is_refused(course: Course, path: Path) -> None:
    naive = answer(1, True).model_copy(update={"answered_at": datetime(2026, 11, 20, 10, 0)})
    with closing(open_storage(path)) as db:
        with pytest.raises(ValueError, match="time zone"):
            save(db, course, naive)
        assert load_history(db, course, "sam") == []


def test_an_answer_to_a_step_the_course_lacks_is_refused(course: Course, path: Path) -> None:
    with closing(open_storage(path)) as db:
        with pytest.raises(ValueError, match="no step 9"):
            save_answer(db, course, answer(9, True), given="1")
        with pytest.raises(ValueError, match="no problem"):
            save_answer(db, course, answer(1, True, problem_id="not_a_problem"), given="1")


def test_each_answer_row_keeps_the_course_the_skill_and_the_given_answer(
    course: Course, path: Path
) -> None:
    with closing(open_storage(path)) as db:
        save_answer(db, course, answer(2, True), given="30")
        save_answer(db, course, answer(3, False, minute=1))
        rows = db.execute(
            "SELECT course_id, skill_id, given FROM answers ORDER BY step_position"
        ).fetchall()
    assert rows == [
        (course.id, "work_constant_force", '"30"'),
        (course.id, "kinetic_energy", None),
    ]


def test_a_course_edit_that_moves_a_step_to_another_skill_is_noticed(
    course: Course, path: Path
) -> None:
    with closing(open_storage(path)) as db:
        save(db, course, answer(2, True))
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
        save(db, course, answer(3, True))
        edited = course.model_copy(deep=True)
        edited.problems[0].steps.pop()  # push_cart loses step 3
        assert len(check_saved_answers(db, edited)) == 1
        assert load_mastery(db, edited, "sam") == new_mastery_state(edited, "sam")


def test_mastery_still_counts_the_answers_that_fit_after_a_course_edit(
    course: Course, path: Path
) -> None:
    with closing(open_storage(path)) as db:
        save(db, course, answer(2, True))
        save(db, course, answer(3, True, minute=1))
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
            save(db, course, broken)
        assert load_history(db, course, "sam") == []


def test_replay_follows_answer_time_not_the_order_answers_arrived(
    course: Course, path: Path
) -> None:
    # The rule: the time on each answer decides the order. An answer that arrives
    # late but carries an earlier time is replayed in its time order.
    early, late = answer(1, True, minute=0), answer(2, False, minute=5)
    with closing(open_storage(path)) as db:
        save(db, course, late)
        save(db, course, early)
        expected = new_mastery_state(course, "sam")
        for step_answer in (early, late):
            expected = update_mastery(expected, step_answer, course)
        assert load_history(db, course, "sam") == [early, late]
        assert load_mastery(db, course, "sam") == expected


def test_list_students_names_each_student_once(course: Course, path: Path) -> None:
    with closing(open_storage(path)) as db:
        assert list_students(db) == []
        save(db, course, answer(1, True, nickname="zoe"))
        save(db, course, answer(2, True, nickname="zoe", minute=1))
        save(db, course, answer(1, True, nickname="ali"))
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
            problem_id="car_power",
            reason="Picked for you: you missed step 2 of Push a cart.",
            is_follow_up=True,
            target_skill="work_constant_force",
            missed_step=MissedStep(problem_id="push_cart", step_position=2),
            rule="follow_up",
            challenge="solid",
        ),
        Pick(
            problem_id="spring_launch",
            reason="New skill: Potential energy.",
            is_follow_up=False,
            target_skill="potential_energy",
            rule="new_skill",
            challenge="stretch",
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
            save(db, course, step_answer)
        save_picks(db, course, "sam", a_batch(), START_TIME)
        save(db, course, answer(1, True, nickname="ali"))
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
        save(db, course, answer(1, True))
        forget_student(db, "sam")
    with closing(open_storage(path)) as db:
        assert list_students(db) == []
        assert load_history(db, course, "sam") == []


def test_odd_nicknames_are_stored_as_plain_text(course: Course, path: Path) -> None:
    # Values are passed separately from the SQL, so quotes in a nickname are just text.
    odd = "o'brien\"); DROP TABLE answers; --"
    with closing(open_storage(path)) as db:
        save(db, course, answer(1, True, nickname=odd))
        assert list_students(db) == [odd]
        assert forget_student(db, odd) == 2
        db.execute("SELECT COUNT(*) FROM answers")  # the table is still there


def test_opening_the_same_file_twice_keeps_the_tables(path: Path) -> None:
    with closing(open_storage(path)):
        pass
    with closing(open_storage(path)) as db:
        assert isinstance(db, sqlite3.Connection)


# The engine checks each answer itself, so a page cannot claim a wrong answer was right.


def test_a_page_claiming_a_wrong_answer_was_right_is_refused(course: Course, path: Path) -> None:
    # push_cart step 2's answer is 30.
    with closing(open_storage(path)) as db:
        with pytest.raises(ValueError, match="marked right, but '1200' is wrong"):
            save_answer(db, course, answer(2, True), given="1200")
        assert load_history(db, course, "sam") == []


def test_a_page_claiming_a_right_answer_was_wrong_is_refused(course: Course, path: Path) -> None:
    with closing(open_storage(path)) as db:
        with pytest.raises(ValueError, match="marked wrong, but '30' is right"):
            save_answer(db, course, answer(2, False), given="30")
        assert load_history(db, course, "sam") == []


def test_a_truthful_flag_is_saved_with_what_was_given(course: Course, path: Path) -> None:
    with closing(open_storage(path)) as db:
        assert save_answer(db, course, answer(2, True), given="30.0") is True
        assert save_answer(db, course, answer(3, False, minute=1), given=4) is True
        rows = db.execute("SELECT correct, given FROM answers ORDER BY seq").fetchall()
        assert len(load_history(db, course, "sam")) == 2
    assert rows == [(1, '"30.0"'), (0, "4")]


def test_a_right_answer_with_nothing_given_is_refused(course: Course, path: Path) -> None:
    with closing(open_storage(path)) as db:
        with pytest.raises(ValueError, match="nothing was given"):
            save_answer(db, course, answer(2, True))
        assert load_history(db, course, "sam") == []


def test_a_wrong_answer_with_nothing_given_is_saved(course: Course, path: Path) -> None:
    # Such as a step the student gave up on: marking it wrong can only lower mastery.
    with closing(open_storage(path)) as db:
        assert save_answer(db, course, answer(2, False)) is True
        assert load_history(db, course, "sam") == [answer(2, False)]


def test_an_order_answer_is_checked_and_saved_as_a_list(course: Course, path: Path) -> None:
    order = find_order_step(course)
    right = list(order.answer)
    wrong = list(reversed(right))
    step_answer = answer(2, True, problem_id="spring_launch")
    with closing(open_storage(path)) as db:
        with pytest.raises(ValueError, match="marked right"):
            save_answer(db, course, step_answer, given=wrong)
        assert save_answer(db, course, step_answer, given=right) is True
        (stored,) = db.execute("SELECT given FROM answers").fetchone()
    assert json.loads(stored) == right


def find_order_step(course: Course) -> Step:
    """Step 2 of spring_launch, an order step."""
    problem = next(problem for problem in course.problems if problem.id == "spring_launch")
    step = problem.steps[1]
    assert step.kind == "order"
    return step


def test_each_pick_is_saved_with_the_rule_that_made_it(course: Course, path: Path) -> None:
    with closing(open_storage(path)) as db:
        save_picks(db, course, "sam", a_batch(), START_TIME)
        rows = db.execute("SELECT rule FROM picks ORDER BY seq").fetchall()
        loaded = [pick.rule for _, pick in load_picks(db, course, "sam")]
    assert rows == [("follow_up",), ("new_skill",)]
    assert loaded == ["follow_up", "new_skill"]


# A file made before picks had a rule column (and before `given` was JSON text) cannot
# be read safely, so it is refused with a plain message instead of failing later.
OLD_PICKS_TABLE = """
CREATE TABLE picks (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    nickname TEXT NOT NULL,
    course_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    position INTEGER NOT NULL,
    problem_id TEXT NOT NULL,
    target_skill TEXT NOT NULL,
    is_follow_up INTEGER NOT NULL,
    missed_problem_id TEXT,
    missed_step_position INTEGER,
    reason TEXT NOT NULL
);
"""


def test_a_file_from_before_the_current_layout_is_refused_plainly(path: Path) -> None:
    with closing(sqlite3.connect(path)) as old:
        old.executescript(OLD_PICKS_TABLE)

    with pytest.raises(ValueError, match="older version"):
        open_storage(path)


def test_each_pick_is_saved_with_how_hard_it_was_meant_to_be(course: Course, path: Path) -> None:
    with closing(open_storage(path)) as db:
        save_picks(db, course, "sam", a_batch(), START_TIME)
        rows = db.execute("SELECT challenge FROM picks ORDER BY seq").fetchall()
        loaded = [pick.challenge for _, pick in load_picks(db, course, "sam")]
    assert rows == [("solid",), ("stretch",)]
    assert loaded == ["solid", "stretch"]


def test_a_file_from_before_picks_had_a_challenge_column_is_refused(path: Path) -> None:
    # Layout 1: picks has a rule column but no challenge column.
    layout_1 = OLD_PICKS_TABLE.replace(
        "    is_follow_up INTEGER NOT NULL,",
        "    rule TEXT NOT NULL,\n    is_follow_up INTEGER NOT NULL,",
    )
    with closing(sqlite3.connect(path)) as old:
        old.executescript(layout_1)
        old.execute("PRAGMA user_version = 1")

    with pytest.raises(ValueError, match="older version"):
        open_storage(path)


def test_a_new_file_opens_again_after_closing(course: Course, path: Path) -> None:
    with closing(open_storage(path)) as db:
        save(db, course, answer(2, True))
    with closing(open_storage(path)) as db:
        assert len(load_history(db, course, "sam")) == 1


# Template problems (decided 2026-11-27): each answer keeps its variant.


def test_a_template_answer_is_checked_against_its_variant_and_kept(
    course: Course, path: Path
) -> None:
    template = next(p for p in course.problems if p.id == "changing_force")
    work = fill_problem(template, 5).steps[3].answer
    right = answer(4, True, problem_id="changing_force").model_copy(update={"variant": 5})

    with closing(open_storage(path)) as db:
        with pytest.raises(ValueError, match="which variant"):
            save_answer(db, course, right.model_copy(update={"variant": None}), given=str(work))
        with pytest.raises(ValueError, match="is marked right"):
            save_answer(db, course, right, given=str(work * 2))
        assert save_answer(db, course, right, given=str(work)) is True
        assert load_history(db, course, "sam")[-1].variant == 5


def test_a_layout_2_file_gains_the_variant_column_and_keeps_its_answers(
    course: Course, path: Path
) -> None:
    with closing(open_storage(path)) as db:
        save(db, course, answer(1, True))
        db.execute("ALTER TABLE answers DROP COLUMN variant")
        db.execute("PRAGMA user_version = 2")
        db.commit()

    with closing(open_storage(path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        assert load_history(db, course, "sam") == [answer(1, True)]


def test_two_requests_opening_an_old_file_at_once_both_work(course: Course, path: Path) -> None:
    import threading

    with closing(open_storage(path)) as db:
        save(db, course, answer(1, True))
        db.execute("ALTER TABLE answers DROP COLUMN variant")
        db.execute("PRAGMA user_version = 2")
        db.commit()
    errors = []

    def open_it() -> None:
        try:
            with closing(open_storage(path)):
                pass
        except Exception as error:  # any failure fails the test below
            errors.append(error)

    threads = [threading.Thread(target=open_it) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
