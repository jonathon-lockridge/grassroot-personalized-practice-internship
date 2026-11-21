"""Checks for the next-problem rules (step T3).

Most tests build a tiny course in code, so the rule being checked is easy to see.
The last few use the real physics course.
"""

from datetime import datetime, timedelta
from pathlib import Path

from practice_engine.mastery import new_mastery_state
from practice_engine.models import (
    Course,
    MasteryState,
    Problem,
    Skill,
    Step,
    StepAnswer,
    load_course,
    validate_course,
)
from practice_engine.selection import (
    FADING_DAYS,
    MASTERED,
    READY_MASTERY,
    MissedStep,
    next_problems,
)

# The course file, found from this test file's own location (see test_models.py).
COURSE = (
    Path(__file__).resolve().parents[1] / "data" / "ap-physics-c-energy-momentum" / "course.json"
)
NOW = datetime(2026, 11, 20, 12, 0)
LAST_WEEK = NOW - timedelta(days=FADING_DAYS + 1)


def tiny_course(skills: dict[str, list[str]], problems: list[tuple[str, int, list[str]]]) -> Course:
    """A small course: `skills` is skill id -> prerequisites; each problem is
    (id, difficulty, the skill of each step). Every step is a number step."""
    course = Course(
        id="tiny",
        title="Tiny course",
        skills=[
            Skill(id=skill_id, name=f"Skill {skill_id}", prerequisites=prerequisites)
            for skill_id, prerequisites in skills.items()
        ],
        problems=[
            Problem(
                id=problem_id,
                prompt="A problem.",
                difficulty=difficulty,
                steps=[
                    Step(prompt="A step.", kind="number", answer=1, hint="A hint.", skill=skill)
                    for skill in step_skills
                ],
            )
            for problem_id, difficulty, step_skills in problems
        ],
    )
    assert validate_course(course) == []  # make sure the test course itself is sound
    return course


def state(mastery: dict[str, float]) -> MasteryState:
    return MasteryState(nickname="sam", mastery=mastery)


def answer(problem_id: str, position: int, correct: bool, when: datetime = NOW) -> StepAnswer:
    return StepAnswer(
        nickname="sam",
        problem_id=problem_id,
        step_position=position,
        correct=correct,
        seconds=20,
        hints_used=0,
        answered_at=when,
    )


# An old, right answer: enough history that the student is not new, but it blocks
# nothing (it is more than 24 hours old) and triggers no follow-up.
OLD_RIGHT = [answer("p_old", 1, True, LAST_WEEK)]


def ids(picks: list) -> list[str]:
    return [pick.problem_id for pick in picks]


# Rule 1: a starting check for a new student.


def test_new_student_gets_a_starting_check_covering_starting_skills_first() -> None:
    course = tiny_course(
        {"a": [], "b": [], "c": ["a"]},
        [
            ("only_c", 1, ["c"]),
            ("a_hard", 3, ["a"]),
            ("a_easy", 1, ["a", "c"]),
            ("b_easy", 1, ["b"]),
        ],
    )

    picks = next_problems(course, state({}), [], NOW)

    # a_easy covers starting skill a (and c), b_easy covers b; then nothing is left
    # to cover, so the check stops at two problems.
    assert ids(picks) == ["a_easy", "b_easy"]
    assert [pick.target_skill for pick in picks] == ["a", "b"]
    assert all(pick.reason.startswith("Starting check") for pick in picks)
    assert not any(pick.is_follow_up for pick in picks)


def test_starting_check_is_at_most_count_problems() -> None:
    course = tiny_course(
        {"a": [], "b": [], "c": []},
        [("pa", 1, ["a"]), ("pb", 1, ["b"]), ("pc", 1, ["c"])],
    )

    assert ids(next_problems(course, state({}), [], NOW, count=2)) == ["pa", "pb"]


# Rule 2: follow-up on the most recent missed step.


def test_follow_up_practices_the_missed_skill_and_fills_its_fields() -> None:
    course = tiny_course(
        {"a": [], "b": []},
        [("p_old", 1, ["a"]), ("p1", 1, ["a", "b"]), ("p2", 1, ["b"]), ("p3", 1, ["a"])],
    )
    history = [answer("p1", 1, True), answer("p1", 2, False)]

    picks = next_problems(course, state({"a": 0.5, "b": 0.2}), history, NOW)

    first = picks[0]
    assert first.problem_id == "p2"
    assert first.is_follow_up is True
    assert first.target_skill == "b"
    assert first.missed_step == MissedStep(problem_id="p1", step_position=2)
    assert first.reason == (
        "Picked for you: you missed step 2 of p1 (Skill b), "
        "so this problem practices that skill again."
    )
    # The other picks are not follow-ups and have no missed step.
    assert all(not pick.is_follow_up and pick.missed_step is None for pick in picks[1:])


def test_follow_up_goes_to_the_weakest_unready_prerequisite_and_says_so() -> None:
    course = tiny_course(
        {"a": [], "b": [], "c": ["a", "b"]},
        [("p_old", 1, ["a"]), ("pc", 1, ["c"]), ("pa", 1, ["a"]), ("pb", 1, ["b"])],
    )
    history = [answer("pc", 1, False)]
    # c is not ready: a and b are both below READY_MASTERY, and b is weaker.
    mastery = {"a": READY_MASTERY - 0.1, "b": READY_MASTERY - 0.3, "c": 0.5}

    picks = next_problems(course, state(mastery), history, NOW)

    first = picks[0]
    assert first.problem_id == "pb"
    assert first.target_skill == "b"
    assert first.is_follow_up is True
    assert first.missed_step == MissedStep(problem_id="pc", step_position=1)
    assert "you missed step 1 of pc (Skill c)" in first.reason
    assert "builds on Skill b" in first.reason


def test_no_follow_up_once_the_missed_skill_was_answered_right() -> None:
    course = tiny_course({"a": []}, [("p1", 1, ["a"]), ("p2", 1, ["a"]), ("p3", 1, ["a"])])
    earlier = NOW - timedelta(hours=1)
    history = [answer("p1", 1, False, earlier), answer("p2", 1, True)]

    picks = next_problems(course, state({"a": 0.5}), history, NOW)

    assert not any(pick.is_follow_up for pick in picks)


# Rule 3: partway skills, weakest first.


def test_partway_skills_come_weakest_first() -> None:
    course = tiny_course(
        {"a": [], "b": [], "c": [], "d": []},
        [("p_old", 1, ["d"]), ("pa", 2, ["a"]), ("pb", 2, ["b"]), ("pc", 1, ["c"])],
    )
    # a and b are partway (b weaker); c is barely started; d is mastered.
    mastery = {"a": 0.6, "b": 0.45, "c": 0.1, "d": 0.95}

    picks = next_problems(course, state(mastery), OLD_RIGHT, NOW, count=2)

    assert ids(picks) == ["pb", "pa"]
    assert "partway" in picks[0].reason


# Rule 4: prerequisites before what depends on them.


def test_skill_that_is_not_ready_is_not_targeted() -> None:
    course = tiny_course(
        {"a": [], "b": ["a"]},
        [("p_old", 1, ["a"]), ("pb", 2, ["b"]), ("pa", 2, ["a"])],
    )
    # b is partway and weaker, but a (its prerequisite) is below READY_MASTERY.
    mastery = {"a": READY_MASTERY - 0.05, "b": 0.35}

    picks = next_problems(course, state(mastery), OLD_RIGHT, NOW, count=1)

    assert picks[0].target_skill == "a"


def test_course_with_no_prerequisites_switches_the_rule_off() -> None:
    course = tiny_course(
        {"a": [], "b": []},
        [("p_old", 1, ["a"]), ("pb", 1, ["b"]), ("pa", 2, ["a"])],
    )
    # With no prerequisites anywhere, every skill is ready, so weakest-first decides.
    picks = next_problems(course, state({"a": 0.6, "b": 0.35}), OLD_RIGHT, NOW, count=1)

    assert picks[0].target_skill == "b"


# Rule 5: revisit fading skills.


def test_mastered_skill_not_practiced_for_a_while_comes_back() -> None:
    course = tiny_course(
        {"a": [], "b": []},
        [("pa", 3, ["a"]), ("pb", 3, ["b"]), ("pa2", 3, ["a"]), ("pb2", 3, ["b"])],
    )
    # Both mastered; a was last practiced over a week ago, b yesterday-ish (25 hours).
    history = [answer("pa", 1, True, LAST_WEEK), answer("pb", 1, True, NOW - timedelta(hours=25))]
    mastery = {"a": MASTERED + 0.05, "b": MASTERED + 0.05}

    picks = next_problems(course, state(mastery), history, NOW, count=1)

    assert picks[0].target_skill == "a"
    assert f"not practiced it in {FADING_DAYS + 1} days" in picks[0].reason


# Rule 6: the student's difficulty level, then the next level up.


def test_prefers_the_students_level_then_the_level_above() -> None:
    course = tiny_course(
        {"a": []},
        [("p_old", 3, ["a"]), ("hard", 3, ["a"]), ("easy", 1, ["a"]), ("medium", 2, ["a"])],
    )
    # 0.3 is level 1 (easy). Only one skill, so the second pick has to reuse it.
    picks = next_problems(course, state({"a": 0.3}), OLD_RIGHT, NOW, count=2)

    assert ids(picks) == ["easy", "medium"]


def test_level_comes_from_the_skills_mastery() -> None:
    course = tiny_course(
        {"a": []},
        [("p_old", 1, ["a"]), ("easy", 1, ["a"]), ("medium", 2, ["a"]), ("hard", 3, ["a"])],
    )

    assert ids(next_problems(course, state({"a": 0.5}), OLD_RIGHT, NOW, count=1)) == ["medium"]
    assert ids(next_problems(course, state({"a": 0.8}), OLD_RIGHT, NOW, count=1)) == ["hard"]


# Rule 7: a batch covers different skills.


def test_batch_covers_different_skills_when_it_can() -> None:
    course = tiny_course(
        {"a": [], "b": [], "c": []},
        [
            ("p_old", 1, ["a"]),
            ("a1", 1, ["a"]),
            ("a2", 1, ["a"]),
            ("b1", 2, ["b"]),
            ("c1", 2, ["c"]),
        ],
    )
    # a is the weakest partway skill, but the batch still spreads over three skills.
    mastery = {"a": 0.31, "b": 0.5, "c": 0.6}

    picks = next_problems(course, state(mastery), OLD_RIGHT, NOW)

    assert [pick.target_skill for pick in picks] == ["a", "b", "c"]


# Rule 8: no repeats within 24 hours.


def test_problem_answered_in_the_last_24_hours_is_not_picked() -> None:
    course = tiny_course({"a": []}, [("p1", 1, ["a"]), ("p2", 1, ["a"])])
    history = [answer("p1", 1, True, NOW - timedelta(hours=23))]

    picks = next_problems(course, state({"a": 0.35}), history, NOW, count=1)

    assert ids(picks) == ["p2"]


# Loosening the rules, in order: difficulty, then repeats, then any skill.


def test_difficulty_is_loosened_before_repeats() -> None:
    course = tiny_course({"a": []}, [("right_level", 1, ["a"]), ("too_hard", 3, ["a"])])
    history = [answer("right_level", 1, True)]  # answered just now

    picks = next_problems(course, state({"a": 0.35}), history, NOW, count=1)

    assert ids(picks) == ["too_hard"]


def test_repeats_are_loosened_before_any_skill() -> None:
    course = tiny_course(
        {"a": [], "b": []},
        [("pa", 1, ["a"]), ("pb", 1, ["b"])],
    )
    history = [answer("pa", 1, True)]  # a's only problem was answered just now
    # a is partway; b is barely started, so b is only reached by "any skill".
    picks = next_problems(course, state({"a": 0.35, "b": 0.1}), history, NOW, count=1)

    assert ids(picks) == ["pa"]


def test_any_skill_is_used_when_no_rule_fits() -> None:
    course = tiny_course(
        {"a": [], "b": []},
        [("p_old", 1, ["a"]), ("pb", 1, ["b"])],
    )
    # Nothing partway, nothing fading, no miss: "any skill" still gives a problem,
    # weakest skill first.
    picks = next_problems(course, state({"a": 0.1, "b": 0.05}), OLD_RIGHT, NOW, count=1)

    assert ids(picks) == ["pb"]
    # b was never answered, so the reason says this starts it, not "more practice".
    assert picks[0].reason == "This problem starts you on Skill b, which you have not tried yet."
    assert not picks[0].reason.startswith("Picked for you")  # that marks follow-ups only


# The rules keep their order, even when a rule has to be loosened.


def test_follow_up_then_partway_then_fading() -> None:
    course = tiny_course(
        {"miss": [], "part": [], "fade": []},
        [("p_miss", 1, ["miss"]), ("p_part", 2, ["part"]), ("p_fade", 3, ["fade"])],
    )
    history = [answer("p_fade", 1, True, LAST_WEEK), answer("p_miss", 1, False, LAST_WEEK)]
    mastery = {"miss": 0.35, "part": 0.5, "fade": MASTERED + 0.05}

    picks = next_problems(course, state(mastery), history, NOW)

    assert [pick.target_skill for pick in picks] == ["miss", "part", "fade"]


def test_follow_up_is_not_crowded_out_when_its_only_problem_was_just_done() -> None:
    course = tiny_course(
        {"miss": [], "b": [], "c": [], "d": []},
        [("p_miss", 1, ["miss"]), ("pb", 2, ["b"]), ("pc", 2, ["c"]), ("pd", 2, ["d"])],
    )
    # p_miss is the only problem for the missed skill, and it was answered just now.
    history = [answer("p_miss", 1, False)]
    mastery = {"miss": 0.35, "b": 0.5, "c": 0.5, "d": 0.5}

    picks = next_problems(course, state(mastery), history, NOW)

    assert picks[0].is_follow_up is True
    assert picks[0].problem_id == "p_miss"


def test_answers_not_in_the_course_are_ignored() -> None:
    course = tiny_course({"a": []}, [("p1", 1, ["a"]), ("p2", 1, ["a"])])
    # An unknown problem only: the student counts as new and gets the starting check.
    picks = next_problems(course, state({}), [answer("gone", 1, False)], NOW, count=1)

    assert picks[0].reason.startswith("Starting check")


# Never empty.


def test_one_skill_course_still_fills_the_batch() -> None:
    course = tiny_course({"a": []}, [("p1", 1, ["a"]), ("p2", 2, ["a"]), ("p3", 3, ["a"])])
    history = [answer("p1", 1, True)]

    picks = next_problems(course, state({"a": 0.9}), history, NOW)

    assert sorted(ids(picks)) == ["p1", "p2", "p3"]


def test_never_empty_when_every_problem_was_done_today() -> None:
    course = load_course(COURSE)
    history = [answer(problem.id, 1, True) for problem in course.problems]

    picks = next_problems(course, new_mastery_state(course, "sam"), history, NOW)

    assert len(picks) == 3
    assert len(set(ids(picks))) == 3  # no problem twice in one batch


# The real physics course.


def test_real_course_starting_check() -> None:
    course = load_course(COURSE)

    picks = next_problems(course, new_mastery_state(course, "sam"), [], NOW)

    assert ids(picks) == ["push_cart", "bat_hits_ball", "rough_ramp"]


def test_real_course_follow_up_after_a_missed_step() -> None:
    course = load_course(COURSE)
    mastery = new_mastery_state(course, "sam").mastery
    # Prerequisites of nonconservative_work (energy with friction) are ready.
    mastery.update({"energy_conservation": 0.7, "nonconservative_work": 0.4})
    # Step 3 of rough_ramp is a nonconservative_work step, answered wrong.
    history = [answer("rough_ramp", step, step != 3) for step in (1, 2, 3)]

    picks = next_problems(course, state(mastery), history, NOW)

    first = picks[0]
    assert first.is_follow_up is True
    assert first.target_skill == "nonconservative_work"
    assert first.missed_step == MissedStep(problem_id="rough_ramp", step_position=3)
    # rough_ramp was answered today, but it is the only problem with this skill, so the
    # no-repeats rule is loosened rather than leaving the skill out.
    assert first.problem_id == "rough_ramp"
    assert "you missed step 3 of rough_ramp" in first.reason
    assert len({pick.target_skill for pick in picks}) == 3


def test_real_course_follow_up_steps_back_to_a_prerequisite() -> None:
    course = load_course(COURSE)
    mastery = new_mastery_state(course, "sam").mastery  # every skill at 0.2
    history = [answer("rough_ramp", step, step != 3) for step in (1, 2, 3)]

    picks = next_problems(course, state(mastery), history, NOW)

    # nonconservative_work needs energy_conservation, which needs kinetic_energy and
    # potential_energy (tied at 0.2, so the first listed wins), which are ready.
    first = picks[0]
    assert first.target_skill == "kinetic_energy"
    assert first.is_follow_up is True
    assert "builds on" in first.reason
