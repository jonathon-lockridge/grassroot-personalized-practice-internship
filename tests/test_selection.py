"""Checks for the next-problem rules (step T3).

Most tests build a tiny course in code, so the rule being checked is easy to see.
The last few use the real physics course.

Handy numbers for the tiny courses: every step is a number step unless a test says
otherwise, and the chance of getting a number step right is 0.2 + 0.65 x mastery
(mastery.chance_correct). So mastery 1.0 gives 0.85, 0.6 gives 0.59, 0 gives 0.2.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from practice_engine.mastery import MASTERED, START_MASTERY, new_mastery_state, update_mastery
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
    MAX_BATCH_SKILLS,
    READY_MASTERY,
    STUCK_STEPS,
    MissedStep,
    next_problems,
)

# The course file, found from this test file's own location (see test_models.py).
COURSE = (
    Path(__file__).resolve().parents[1] / "data" / "ap-physics-c-energy-momentum" / "course.json"
)
NOW = datetime(2026, 11, 20, 12, 0)
LAST_WEEK = NOW - timedelta(days=7)
KNOWN = MASTERED + 0.02  # a mastery number high enough to count as mastered


def tiny_course(skills: dict[str, list[str]], problems: list[tuple]) -> Course:
    """A small course: `skills` is skill id -> prerequisites; each problem is
    (id, difficulty, the skill of each step), with an optional fourth item: the
    answer of a choice first step (options "X" and "Y"). Other steps are number steps.
    A problem's title is "Problem <id>"; a skill's name is "Skill <id>"."""
    built = []
    for problem_id, difficulty, step_skills, *first_answer in problems:
        steps = [
            Step(prompt="A step.", kind="number", answer=1, hint="A hint.", skill=skill)
            for skill in step_skills
        ]
        if first_answer:
            wrong = "Y" if first_answer[0] == "X" else "X"
            steps[0] = Step(
                prompt="Which idea?",
                kind="choice",
                options=["X", "Y"],
                answer=first_answer[0],
                hint="A hint.",
                skill=step_skills[0],
                feedback={wrong: "Not this one."},
            )
        built.append(
            Problem(
                id=problem_id,
                title=f"Problem {problem_id}",
                prompt="A problem.",
                difficulty=difficulty,
                steps=steps,
            )
        )
    course = Course(
        id="tiny",
        title="Tiny course",
        skills=[
            Skill(id=skill_id, name=f"Skill {skill_id}", prerequisites=prerequisites)
            for skill_id, prerequisites in skills.items()
        ],
        problems=built,
    )
    assert validate_course(course) == []  # make sure the test course itself is sound
    return course


def state(mastery: dict[str, float], course_id: str = "tiny") -> MasteryState:
    return MasteryState(nickname="sam", course_id=course_id, mastery=mastery)


def answer(
    problem_id: str,
    position: int,
    correct: bool,
    when: datetime = NOW,
    attempt: int = 1,
    hints_used: int = 0,
) -> StepAnswer:
    return StepAnswer(
        nickname="sam",
        problem_id=problem_id,
        step_position=position,
        correct=correct,
        seconds=20,
        hints_used=hints_used,
        answered_at=when,
        attempt=attempt,
    )


def streak(problem_id: str, when: datetime) -> list[StepAnswer]:
    """Four right first tries on step 1 (a number step) of a problem, a minute apart:
    from a new student's number, enough to reach MASTERED with a streak, so the skill
    counts as mastered from the fourth one (mastery.is_mastered)."""
    return [answer(problem_id, 1, True, when + timedelta(minutes=i)) for i in range(4)]


# A problem on a skill of its own. Added to a tiny course whose problems all share a
# skill, it stops that skill from counting as "used by every problem", which no rule
# ever targets (see the tests near the end).
OTHER_PROBLEM = ("p_other", 1, ["other"])

# An old, right answer: enough history that the student is not new, but it blocks
# nothing (it is more than 24 hours old) and triggers no follow-up.
OLD_RIGHT = [answer("p_old", 1, True, LAST_WEEK)]


def ids(picks: list) -> list[str]:
    return [pick.problem_id for pick in picks]


def skills_of(picks: list) -> list[str]:
    return [pick.target_skill for pick in picks]


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
    assert skills_of(picks) == ["a", "b"]
    assert picks[0].reason == (
        "Starting check: you are new here, so this problem shows what you "
        "already know about Skill a."
    )
    assert not any(pick.is_follow_up for pick in picks)


def test_starting_check_is_at_most_count_problems() -> None:
    course = tiny_course(
        {"a": [], "b": [], "c": []},
        [("pa", 1, ["a"]), ("pb", 1, ["b"]), ("pc", 1, ["c"])],
    )

    assert ids(next_problems(course, state({}), [], NOW, count=2)) == ["pa", "pb"]


def test_answers_by_another_student_or_not_in_the_course_are_ignored() -> None:
    course = tiny_course({"a": []}, [("p1", 1, ["a"]), ("p2", 1, ["a"])])
    someone_else = answer("p1", 1, False).model_copy(update={"nickname": "alex"})
    history = [answer("gone", 1, False), someone_else]

    picks = next_problems(course, state({}), history, NOW, count=1)

    assert picks[0].reason.startswith("Starting check")


def test_a_state_for_another_course_is_refused() -> None:
    course = tiny_course({"a": []}, [("p1", 1, ["a"])])

    with pytest.raises(ValueError, match="is for course 'other'"):
        next_problems(course, state({}, course_id="other"), [], NOW)


# Rule 2: follow-up on the most recent missed first try.


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
    # The reason names the problem by its title and the skill by its name, never ids.
    assert first.reason == (
        "Picked for you: you missed step 2 of Problem p1 (Skill b), "
        "so this problem practices that skill again."
    )
    # The other picks are not follow-ups, have no missed step, and say so in their reason.
    assert all(not pick.is_follow_up and pick.missed_step is None for pick in picks[1:])
    assert not any(pick.reason.startswith("Picked for you") for pick in picks[1:])


def test_a_wrong_first_try_after_a_hint_counts_as_missed() -> None:
    course = tiny_course({"a": []}, [("p1", 1, ["a"]), ("p2", 1, ["a"])])
    history = [answer("p1", 1, False, hints_used=1)]

    picks = next_problems(course, state({"a": 0.3}), history, NOW, count=1)

    assert picks[0].is_follow_up is True


def test_a_right_first_try_after_a_hint_is_neither_a_miss_nor_a_right_answer() -> None:
    course = tiny_course({"a": []}, [("p1", 1, ["a"]), ("p2", 1, ["a"]), ("p3", 1, ["a"])])
    earlier = NOW - timedelta(hours=1)
    # Alone, it starts no follow-up.
    hinted_only = [answer("p1", 1, True, hints_used=1)]
    # After a miss, it does not cancel that miss's follow-up either.
    miss_then_hinted = [answer("p1", 1, False, earlier), answer("p2", 1, True, hints_used=1)]

    alone = next_problems(course, state({"a": 0.3}), hinted_only, NOW, count=1)
    after_miss = next_problems(course, state({"a": 0.3}), miss_then_hinted, NOW, count=1)

    assert alone[0].is_follow_up is False
    assert after_miss[0].is_follow_up is True
    assert after_miss[0].missed_step == MissedStep(problem_id="p1", step_position=1)


def test_a_right_second_try_does_not_cancel_the_follow_up() -> None:
    course = tiny_course({"a": []}, [("p1", 1, ["a"]), ("p2", 1, ["a"])])
    history = [answer("p1", 1, False), answer("p1", 1, True, attempt=2)]

    picks = next_problems(course, state({"a": 0.3}), history, NOW, count=1)

    assert picks[0].is_follow_up is True
    assert picks[0].missed_step == MissedStep(problem_id="p1", step_position=1)


def test_a_wrong_second_try_is_not_a_miss() -> None:
    course = tiny_course({"a": []}, [("p1", 1, ["a"]), ("p2", 1, ["a"])])
    history = [answer("p1", 1, True), answer("p1", 1, False, attempt=2)]

    picks = next_problems(course, state({"a": 0.3}), history, NOW, count=1)

    assert picks[0].is_follow_up is False


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
    assert "you missed step 1 of Problem pc (Skill c)" in first.reason
    assert "builds on Skill b" in first.reason


def test_no_follow_up_once_the_missed_skill_was_answered_right() -> None:
    course = tiny_course({"a": []}, [("p1", 1, ["a"]), ("p2", 1, ["a"]), ("p3", 1, ["a"])])
    earlier = NOW - timedelta(hours=1)
    history = [answer("p1", 1, False, earlier), answer("p2", 1, True)]

    picks = next_problems(course, state({"a": 0.5}), history, NOW)

    assert not any(pick.is_follow_up for pick in picks)


# The stuck rule.


def misses(problem_id: str, how_many: int) -> list[StepAnswer]:
    """`how_many` missed first tries on step 1 of a problem, last week, a minute apart."""
    return [answer(problem_id, 1, False, LAST_WEEK + timedelta(minutes=i)) for i in range(how_many)]


def test_stuck_follow_up_steps_back_to_the_weakest_prerequisite_not_mastered() -> None:
    course = tiny_course(
        {"a": [], "b": ["a"]},
        [("pb1", 1, ["b"]), ("pb2", 1, ["b"]), ("pa", 1, ["a"])],
    )
    # a is ready (so b is too) but not mastered: it has no streak of right answers.
    mastery = {"a": READY_MASTERY + 0.05, "b": 0.3}

    stuck = next_problems(course, state(mastery), misses("pb1", STUCK_STEPS), NOW, count=1)
    not_yet = next_problems(course, state(mastery), misses("pb1", STUCK_STEPS - 1), NOW, count=1)

    assert stuck[0].target_skill == "a"
    assert stuck[0].is_follow_up is True
    assert stuck[0].reason == (
        "Picked for you: you missed step 1 of Problem pb1 (Skill b). Skill b has been "
        "hard for a while, so this problem practices Skill a, which it builds on."
    )
    assert not_yet[0].target_skill == "b"


def test_later_tries_do_not_count_toward_stuck() -> None:
    course = tiny_course(
        {"a": [], "b": ["a"]},
        [("pb1", 1, ["b"]), ("pb2", 1, ["b"]), ("pa", 1, ["a"])],
    )
    mastery = {"a": READY_MASTERY + 0.05, "b": 0.3}
    # Seven missed first tries, then three missed second tries: still only seven.
    history = misses("pb1", STUCK_STEPS - 1) + [
        answer("pb1", 1, False, LAST_WEEK + timedelta(hours=1), attempt=2) for _ in range(3)
    ]

    picks = next_problems(course, state(mastery), history, NOW, count=1)

    assert picks[0].target_skill == "b"
    assert "hard for a while" not in picks[0].reason


def test_stuck_with_no_prerequisite_gets_the_easiest_problem() -> None:
    course = tiny_course(
        {"b": [], "strong": [], "other": []},
        [("b_hard", 3, ["b", "strong", "strong", "strong"]), ("b_easy", 1, ["b"]), OTHER_PROBLEM],
    )
    # Normally b_hard fits better: its strong steps lift its predicted success
    # (0.74 against 0.40) inside the target.
    mastery = {"b": 0.3, "strong": 1.0}

    stuck = next_problems(course, state(mastery), misses("b_easy", STUCK_STEPS), NOW, count=1)
    not_yet = next_problems(course, state(mastery), misses("b_easy", STUCK_STEPS - 1), NOW, count=1)

    assert ids(stuck) == ["b_easy"]
    assert "Skill b has been hard for a while, so this is an easier problem on it." in (
        stuck[0].reason
    )
    assert ids(not_yet) == ["b_hard"]


def test_stuck_partway_skill_steps_back_too() -> None:
    course = tiny_course({"a": [], "b": ["a"]}, [("pb", 1, ["b"]), ("pa", 1, ["a"])])
    # Eight first tries on b, the last one right, so there is no follow-up.
    history = misses("pb", STUCK_STEPS - 1) + [
        answer("pb", 1, True, LAST_WEEK + timedelta(hours=1))
    ]
    mastery = {"a": READY_MASTERY + 0.05, "b": 0.4}

    picks = next_problems(course, state(mastery), history, NOW, count=1)

    assert picks[0].target_skill == "a"
    assert picks[0].is_follow_up is False
    assert picks[0].reason == (
        "Skill b has been hard for a while, so this problem practices Skill a, which it builds on."
    )


# Rule 3: partway skills, weakest first.


def test_partway_skills_come_weakest_first() -> None:
    course = tiny_course(
        {"a": [], "b": [], "c": []},
        [("pa", 2, ["a"]), ("pb", 2, ["b"]), ("pc", 1, ["c"]), ("pc2", 1, ["c"])],
    )
    # a and b were tried (b is weaker). c has the lowest number but was never tried,
    # so it is new, not partway.
    history = [answer("pa", 1, True, LAST_WEEK), answer("pb", 1, True, LAST_WEEK)]
    mastery = {"a": 0.6, "b": 0.45, "c": 0.1}

    picks = next_problems(course, state(mastery), history, NOW, count=2)

    assert skills_of(picks) == ["b", "a"]
    assert picks[0].reason == (
        "You are partway to mastering Skill b, so this problem helps you finish it."
    )


def test_high_number_without_a_streak_is_still_partway() -> None:
    course = tiny_course({"a": [], "b": []}, [("pa", 1, ["a"]), ("pb", 1, ["b"])])
    # a has a mastered-level number but only one right first try, so it is not mastered.
    history = [answer("pa", 1, True, LAST_WEEK)]

    picks = next_problems(course, state({"a": KNOWN, "b": 0.1}), history, NOW, count=1)

    assert picks[0].target_skill == "a"
    assert "partway" in picks[0].reason


# The ready rule: prerequisites before what depends on them.


def test_skill_whose_prerequisite_is_below_ready_is_not_targeted() -> None:
    course = tiny_course({"a": [], "b": ["a"]}, [("pb", 2, ["b"]), ("pa", 2, ["a"])])
    history = [answer("pb", 1, True, LAST_WEEK)]  # b was tried, a never

    below = next_problems(course, state({"a": READY_MASTERY - 0.01, "b": 0.4}), history, NOW, 1)
    at = next_problems(course, state({"a": READY_MASTERY, "b": 0.4}), history, NOW, 1)

    assert below[0].target_skill == "a"  # b is not ready, so the new skill a comes first
    assert at[0].target_skill == "b"  # b is ready and partway


def test_course_with_no_prerequisites_switches_the_rule_off() -> None:
    course = tiny_course(
        {"a": [], "b": []},
        [("pb", 1, ["b"]), ("pa", 2, ["a"])],
    )
    history = [answer("pa", 1, True, LAST_WEEK), answer("pb", 1, True, LAST_WEEK)]
    # With no prerequisites anywhere, every skill is ready, so weakest-first decides.
    picks = next_problems(course, state({"a": 0.6, "b": 0.35}), history, NOW, count=1)

    assert picks[0].target_skill == "b"


# Rule 4: spaced review of mastered skills.

REVIEW_COURSE = {"a": [], "b": []}
REVIEW_PROBLEMS = [("pa1", 1, ["a"]), ("pa2", 1, ["a"]), ("pa3", 1, ["a"]), ("pb", 1, ["b"])]


def test_mastered_skill_comes_back_for_review_after_one_day() -> None:
    course = tiny_course(REVIEW_COURSE, REVIEW_PROBLEMS)
    history = streak("pa1", NOW - timedelta(days=1, hours=1))

    picks = next_problems(course, state({"a": KNOWN, "b": 0.1}), history, NOW, count=1)

    assert picks[0].target_skill == "a"
    assert (
        picks[0].reason == "Review: you mastered Skill a 1 day ago; a quick check keeps it fresh."
    )


def test_skill_mastered_today_is_not_reviewed_yet() -> None:
    course = tiny_course(REVIEW_COURSE, REVIEW_PROBLEMS)
    history = streak("pa1", NOW - timedelta(hours=5))

    picks = next_problems(course, state({"a": KNOWN, "b": 0.1}), history, NOW)

    assert not any(pick.reason.startswith("Review") for pick in picks)


def test_a_right_answer_on_a_later_day_moves_to_the_next_gap() -> None:
    course = tiny_course(REVIEW_COURSE, REVIEW_PROBLEMS)
    mastery = {"a": KNOWN, "b": 0.1}
    mastered = streak("pa1", NOW - timedelta(days=5))
    # Without a review since, the 1-day gap passed long ago.
    assert next_problems(course, state(mastery), mastered, NOW, 1)[0].reason.startswith("Review")

    # A right first try 2 days ago counts as the review, so the next gap is 3 days.
    reviewed = mastered + [answer("pa2", 1, True, NOW - timedelta(days=2))]
    today = next_problems(course, state(mastery), reviewed, NOW, count=1)
    tomorrow = next_problems(course, state(mastery), reviewed, NOW + timedelta(days=1), count=1)

    assert not today[0].reason.startswith("Review")
    assert tomorrow[0].reason == (
        "Review: you mastered Skill a 6 days ago; a quick check keeps it fresh."
    )


def test_a_miss_starts_the_review_gaps_over() -> None:
    course = tiny_course(REVIEW_COURSE, REVIEW_PROBLEMS)
    mastery = {"a": KNOWN, "b": 0.1}
    day = lambda n: NOW - timedelta(days=n)  # noqa: E731 (a one-line helper)
    early = streak("pa1", day(10)) + [
        answer("pa2", 1, True, day(9)),
        answer("pa3", 1, True, day(6)),
    ]
    # Reviews on days -9 and -6 grew the gap to 7 days. The right answers on day -3
    # come before that gap has passed, so they do not grow it, and nothing is due today.
    kept = early + streak("pa1", day(3))
    # The same, but with a miss on day -5: mastery was lost and earned again on day -3,
    # so the gaps start over at 1 day, which has passed.
    missed = early + [answer("pa2", 1, False, day(5))] + streak("pa1", day(3))

    assert not next_problems(course, state(mastery), kept, NOW, 1)[0].reason.startswith("Review")
    again = next_problems(course, state(mastery), missed, NOW, count=1)
    assert (
        again[0].reason == "Review: you mastered Skill a 3 days ago; a quick check keeps it fresh."
    )


def test_right_answers_before_a_review_is_due_do_not_grow_the_gap() -> None:
    course = tiny_course(REVIEW_COURSE, REVIEW_PROBLEMS)
    mastery = {"a": KNOWN, "b": 0.1}
    day = lambda n: NOW - timedelta(days=n)  # noqa: E731 (a one-line helper)
    # Mastered on day -10, reviewed on day -9 (the 1-day gap passed), so the gap is 3
    # days. The right answers on days -8 and -7 come too soon to count; day -6 does,
    # so the gap is now 7 days from day -6, due tomorrow.
    history = streak("pa1", day(10)) + [
        answer("pa2", 1, True, day(9)),
        answer("pa3", 1, True, day(8)),
        answer("pa1", 1, True, day(7)),
        answer("pa2", 1, True, day(6)),
    ]

    today = next_problems(course, state(mastery), history, NOW, count=1)
    tomorrow = next_problems(course, state(mastery), history, NOW + timedelta(days=1), count=1)

    assert not today[0].reason.startswith("Review")
    assert tomorrow[0].reason.startswith("Review: you mastered Skill a 11 days ago")


def test_review_clock_starts_when_the_number_reaches_mastered() -> None:
    course = tiny_course(REVIEW_COURSE, REVIEW_PROBLEMS)
    # One right first try a day: the streak is complete on day -2, but the number
    # only reaches MASTERED with the fourth, yesterday. So the clock starts yesterday,
    # and the 1-day review is due today.
    history = [answer("pa1", 1, True, NOW - timedelta(days=n)) for n in (4, 3, 2, 1)]

    picks = next_problems(course, state({"a": KNOWN, "b": 0.1}), history, NOW, count=1)

    assert picks[0].reason == (
        "Review: you mastered Skill a 1 day ago; a quick check keeps it fresh."
    )


def test_a_right_step_inside_a_problem_on_other_skills_counts_as_the_review() -> None:
    course = tiny_course(REVIEW_COURSE, REVIEW_PROBLEMS + [("p_ba", 1, ["b", "a"])])
    mastery = {"a": KNOWN, "b": 0.3}
    mastered = streak("pa1", NOW - timedelta(days=3))
    # Step 2 of p_ba is the a step, right on its first try two days later.
    reviewed = mastered + [
        answer("p_ba", 1, False, NOW - timedelta(days=1)),
        answer("p_ba", 2, True, NOW - timedelta(days=1)),
    ]

    before = next_problems(course, state(mastery), mastered, NOW, count=3)
    after = next_problems(course, state(mastery), reviewed, NOW, count=3)

    assert any(pick.reason.startswith("Review") for pick in before)
    assert not any(pick.reason.startswith("Review") for pick in after)


# Rule 5: starting new skills whose prerequisites are ready.


def test_new_ready_skill_comes_after_reviews_and_unready_ones_wait() -> None:
    course = tiny_course(
        {"rev": [], "new": [], "later": ["rev", "new"]},
        [
            ("p_rev", 1, ["rev"]),
            ("p_rev2", 1, ["rev"]),
            ("p_new", 1, ["new"]),
            ("p_later", 1, ["later"]),
        ],
    )
    history = streak("p_rev", LAST_WEEK)
    mastery = {"rev": KNOWN, "new": 0.1, "later": 0.1}

    picks = next_problems(course, state(mastery), history, NOW, count=2)

    assert skills_of(picks) == ["rev", "new"]
    assert picks[1].reason == "This problem starts you on Skill new."
    # "later" is new too, but "new" (one of its prerequisites) is not ready.


# The rules keep their order.


def test_follow_up_then_partway_then_review() -> None:
    course = tiny_course(
        {"miss": [], "part": [], "rev": [], "new": []},
        [
            ("p_miss", 1, ["miss"]),
            ("p_part", 2, ["part"]),
            ("p_rev", 3, ["rev"]),
            ("p_new", 1, ["new"]),
        ],
    )
    history = (
        streak("p_rev", LAST_WEEK)
        + [answer("p_part", 1, True, LAST_WEEK)]
        + [answer("p_miss", 1, False, LAST_WEEK + timedelta(hours=1))]
    )
    mastery = {"miss": 0.35, "part": 0.5, "rev": KNOWN, "new": 0.1}

    picks = next_problems(course, state(mastery), history, NOW)

    assert skills_of(picks) == ["miss", "part", "rev"]


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


# The success target.

# a is the target skill (tried once, partway); hi and lo are skills at 1.0 and 0.
SUCCESS_MASTERY = {"a": 0.6, "hi": 1.0, "lo": 0.0}
SUCCESS_SKILLS = {"a": [], "hi": [], "lo": [], "other": []}
A_TRIED = [answer("p_a", 1, True, LAST_WEEK)]


def test_prefers_predicted_success_closest_to_the_middle_of_the_target() -> None:
    course = tiny_course(
        SUCCESS_SKILLS,
        [
            ("p_a", 1, ["a"]),  # 0.59: below the target
            ("p_a_lo", 1, ["a", "lo"]),  # 0.40: below
            ("p_a_hi", 1, ["a", "hi"]),  # 0.72: inside
            ("p_a_hi_hi", 1, ["a", "hi", "hi"]),  # 0.76: inside, closest to 0.775
            OTHER_PROBLEM,
        ],
    )

    picks = next_problems(course, state(SUCCESS_MASTERY), A_TRIED, NOW, count=1)

    assert ids(picks) == ["p_a_hi_hi"]


def test_difficulty_breaks_a_tie_in_predicted_success() -> None:
    course = tiny_course(
        {"a": [], "hi": [], "other": []},
        [("p_a", 1, ["a"]), ("hard", 3, ["a", "hi"]), ("easy", 1, ["a", "hi"]), OTHER_PROBLEM],
    )

    picks = next_problems(course, state(SUCCESS_MASTERY), A_TRIED, NOW, count=1)

    assert ids(picks) == ["easy"]


def test_when_nothing_is_inside_the_target_the_lower_difficulty_comes_first() -> None:
    course = tiny_course(
        {"a": [], "lo": [], "other": []},
        [("p_a", 3, ["a"]), ("p_a_lo", 1, ["a", "lo"]), OTHER_PROBLEM],  # 0.59 and 0.40
    )

    picks = next_problems(course, state(SUCCESS_MASTERY), A_TRIED, NOW, count=1)

    # p_a is closer to the target, but neither is inside it, so the easier one wins.
    assert ids(picks) == ["p_a_lo"]


def test_when_nothing_is_inside_the_target_and_difficulty_ties_the_closest_is_picked() -> None:
    course = tiny_course(
        {"a": [], "lo": [], "other": []},
        [("p_a_lo", 2, ["a", "lo"]), ("p_a", 2, ["a"]), OTHER_PROBLEM],  # 0.40 and 0.59
    )

    picks = next_problems(course, state(SUCCESS_MASTERY), A_TRIED, NOW, count=1)

    assert ids(picks) == ["p_a"]


def test_a_new_ish_student_gets_an_easy_problem_before_a_hard_choice_heavy_one() -> None:
    # A choice step with 2 options is easier to guess (0.3) than a number step (0.2),
    # so at mastery 0.1 the hard problem's predicted share (0.355) is higher than the
    # easy one's (0.265) and closer to the target. Neither is inside it.
    course = tiny_course(
        {"a": [], "other": []},
        [
            ("hard_choices", 3, ["a", "a", "a"], "X"),  # its first step is a choice step
            ("easy_numbers", 1, ["a", "a"]),
            ("p_a_old", 2, ["a"]),
            OTHER_PROBLEM,
        ],
    )
    hard = course.problems[0]
    # Make all three of the hard problem's steps 2-option choice steps.
    hard.steps = [hard.steps[0]] * 3
    history = [answer("p_a_old", 1, False, LAST_WEEK)]  # a was tried once and missed

    picks = next_problems(course, state({"a": 0.1, "other": 0.1}), history, NOW, count=1)

    assert ids(picks) == ["easy_numbers"]


def test_success_target_is_loosened_before_repeats() -> None:
    course = tiny_course(
        {"a": [], "hi": [], "other": []},
        # 0.72 (inside) and 0.59
        [("p_a_hi", 1, ["a", "hi"]), ("p_a", 1, ["a"]), OTHER_PROBLEM],
    )
    history = [answer("p_a_hi", 1, True)]  # the problem inside the target, just now

    picks = next_problems(course, state(SUCCESS_MASTERY), history, NOW, count=1)

    assert ids(picks) == ["p_a"]


def test_problem_answered_in_the_last_24_hours_is_not_picked() -> None:
    course = tiny_course({"a": []}, [("p1", 1, ["a"]), ("p2", 1, ["a"])])
    history = [answer("p1", 1, True, NOW - timedelta(hours=23))]

    picks = next_problems(course, state({"a": 0.35}), history, NOW, count=1)

    assert ids(picks) == ["p2"]


def test_repeats_are_loosened_before_any_skill() -> None:
    course = tiny_course({"a": [], "b": ["a"]}, [("pa", 1, ["a"]), ("pb", 1, ["b"])])
    history = [answer("pa", 1, True)]  # a's only problem was answered just now
    # a is partway; b is not ready, so b is only reached by "any skill".
    picks = next_problems(course, state({"a": 0.35, "b": 0.1}), history, NOW, count=1)

    assert ids(picks) == ["pa"]


def test_any_skill_is_used_when_no_rule_fits() -> None:
    course = tiny_course({"a": [], "b": []}, [("pa", 1, ["a"]), ("pb", 1, ["b"])])
    # Both skills were mastered this morning: nothing is partway, new or due for
    # review. Only "any skill" is left, and it still gives problems.
    history = streak("pa", NOW - timedelta(hours=5)) + streak("pb", NOW - timedelta(hours=4))
    picks = next_problems(course, state({"a": KNOWN, "b": KNOWN}), history, NOW, count=2)

    assert sorted(ids(picks)) == ["pa", "pb"]
    assert [pick.reason for pick in picks] == [
        "More practice with Skill a.",
        "More practice with Skill b.",
    ]
    assert not any(pick.reason.startswith("Picked for you") for pick in picks)


# Mixing problem types.

# p is the skill of each problem's first (choice) step; a is the target skill.
MIX_SKILLS = {"p": [], "a": [], "hi": [], "other": []}
MIX_MASTERY = {"p": 0.9, "a": 0.7, "hi": 1.0}


def pick_after(previous_answer: str, problems: list[tuple]) -> str:
    """The first pick after the student did a problem whose first step's answer is
    `previous_answer`."""
    course = tiny_course(
        MIX_SKILLS, [("prev", 1, ["p", "a"], previous_answer), *problems, OTHER_PROBLEM]
    )
    history = [answer("prev", 2, True, LAST_WEEK)]  # step 2 is skill a
    return next_problems(course, state(MIX_MASTERY), history, NOW, count=1)[0].problem_id


def test_mixing_prefers_a_different_first_step_answer_when_otherwise_equal() -> None:
    # Same skills and difficulty, so the same predicted success: only mixing differs.
    problems = [("x_twin", 1, ["p", "a", "hi"], "X"), ("y_twin", 1, ["p", "a", "hi"], "Y")]

    assert pick_after("X", problems) == "y_twin"
    assert pick_after("Y", problems) == "x_twin"


def test_closeness_to_the_middle_comes_before_mixing() -> None:
    problems = [
        ("x_close", 1, ["p", "a", "hi"], "X"),  # 0.77, closest to the middle
        ("y_far", 1, ["p", "a"], "Y"),  # 0.73
    ]

    assert pick_after("X", problems) == "x_close"  # even though it repeats the type


def test_two_picks_in_a_row_never_practice_the_same_skill_when_avoidable() -> None:
    course = tiny_course(
        {"a": [], "b": []},
        [("a1", 1, ["a"]), ("a2", 1, ["a"]), ("b1", 1, ["b"]), ("b2", 1, ["b"])],
    )
    history = [answer("a1", 1, True, LAST_WEEK)]

    picks = next_problems(course, state({"a": 0.4, "b": 0.3}), history, NOW, count=4)

    targets = skills_of(picks)
    assert len(picks) == 4
    assert all(first != second for first, second in zip(targets, targets[1:], strict=False))


def test_a_batch_keeps_to_three_skills() -> None:
    skills = {name: [] for name in "abcde"}
    course = tiny_course(skills, [(f"{name}{i}", 1, [name]) for name in "abcde" for i in (1, 2)])
    history = [answer(f"{name}1", 1, True, LAST_WEEK) for name in "abcde"]

    picks = next_problems(course, state({name: 0.4 for name in "abcde"}), history, NOW, count=5)

    targets = skills_of(picks)
    assert len(picks) == 5
    assert len(set(targets)) == 3
    assert all(first != second for first, second in zip(targets, targets[1:], strict=False))


def test_count_above_the_skill_cap_can_give_fewer_picks() -> None:
    skills = {name: [] for name in "abcde"}
    course = tiny_course(skills, [(f"{name}1", 1, [name]) for name in "abcde"])
    history = [answer(f"{name}1", 1, True, LAST_WEEK) for name in "abcde"]

    picks = next_problems(course, state({name: 0.4 for name in "abcde"}), history, NOW, count=5)

    # Skills a, b and c have one problem each, and d and e would be a fourth skill.
    assert len(picks) == MAX_BATCH_SKILLS
    assert ids(picks) == ["a1", "b1", "c1"]


# A skill used by every problem is never a target.

# "pick" is the first step of every problem, like the real course's choose_principle.
EVERY_SKILLS = {"pick": [], "a": [], "b": []}
EVERY_PROBLEMS = [
    ("p1", 1, ["pick", "a"]),
    ("p2", 1, ["pick", "b"]),
    ("p3", 1, ["pick", "a"]),
    ("p4", 1, ["pick", "b"]),
]


def test_skill_in_every_problem_is_not_the_starting_check_target() -> None:
    course = tiny_course(EVERY_SKILLS, EVERY_PROBLEMS)

    picks = next_problems(course, state({}), [], NOW)

    assert skills_of(picks) == ["a", "b"]


def test_a_miss_on_the_skill_in_every_problem_follows_up_on_another_skill() -> None:
    course = tiny_course(EVERY_SKILLS, EVERY_PROBLEMS)
    # Step 1 (pick) missed, step 2 (a) right. pick is now the weakest skill.
    history = [answer("p1", 1, False), answer("p1", 2, True)]
    mastery = {"pick": 0.05, "a": 0.4, "b": 0.1}

    picks = next_problems(course, state(mastery), history, NOW)

    first = picks[0]
    assert first.is_follow_up is True
    assert first.missed_step == MissedStep(problem_id="p1", step_position=1)
    # a is the weakest partway skill, so it is practiced instead, and the reason says so.
    assert first.target_skill == "a"
    assert first.reason == (
        "Picked for you: you missed step 1 of Problem p1 (Skill pick), which every "
        "problem practices. You are partway to mastering Skill a, so this problem helps "
        "you finish it."
    )
    assert "pick" not in skills_of(picks)


def test_skill_in_every_problem_is_never_a_target_but_is_still_practiced() -> None:
    course = tiny_course(EVERY_SKILLS, EVERY_PROBLEMS)
    scenarios = [
        # pick tried and weak (would be partway, weakest first)
        ([answer("p1", 1, True, LAST_WEEK)], {"pick": 0.2, "a": 0.1, "b": 0.1}),
        # pick mastered last week (would be due for review); a and b too
        (
            streak("p1", LAST_WEEK) + streak("p1", LAST_WEEK + timedelta(hours=1)),
            {"pick": KNOWN, "a": 0.5, "b": 0.1},
        ),
        # every problem done today (only "any skill" is left)
        ([answer(f"p{i}", 1, True) for i in range(1, 5)], {"pick": 0.1, "a": 0.5, "b": 0.5}),
    ]
    for history, mastery in scenarios:
        picks = next_problems(course, state(mastery), history, NOW, count=4)
        assert picks, "the list is never empty"
        assert "pick" not in skills_of(picks)


def test_skill_in_every_problem_is_never_stepped_back_to() -> None:
    # b builds on pick, and pick is in every problem, so neither the stuck rule nor
    # the step down to a prerequisite that is not ready may move to pick.
    course = tiny_course(
        {"pick": [], "b": ["pick"], "c": []},
        [("p1", 1, ["pick", "b"]), ("p2", 1, ["pick", "b"]), ("p3", 1, ["pick", "c"])],
    )
    mastery = {"pick": 0.3, "b": 0.3}  # pick is below ready and not mastered
    missed_b = [
        answer("p1", 2, False, LAST_WEEK + timedelta(minutes=i)) for i in range(STUCK_STEPS)
    ]

    stuck = next_problems(course, state(mastery), missed_b, NOW, count=1)
    not_stuck = next_problems(course, state(mastery), missed_b[1:], NOW, count=1)

    assert stuck[0].target_skill == "b"
    assert "so this is an easier problem on it." in stuck[0].reason
    assert not_stuck[0].target_skill == "b"
    assert not_stuck[0].reason.endswith("so this problem practices that skill again.")


def test_skill_in_every_problem_is_still_a_target_when_it_is_the_only_skill_used() -> None:
    # One problem, or problems that all use the same skills: nothing else to pick for.
    single = tiny_course({"a": [], "b": []}, [("p1", 1, ["a", "b"])])
    shared = tiny_course({"a": [], "b": []}, [("p1", 1, ["a", "b"]), ("p2", 1, ["b", "a"])])

    assert skills_of(next_problems(single, state({}), [], NOW)) == ["a"]
    assert "a" in skills_of(next_problems(shared, state({}), [], NOW))


# Time zones.


def test_mixing_times_with_and_without_a_time_zone_is_refused() -> None:
    course = tiny_course({"a": []}, [("p1", 1, ["a"])])
    history = [answer("p1", 1, True, NOW.replace(tzinfo=UTC))]

    with pytest.raises(ValueError, match="time zone"):
        next_problems(course, state({"a": 0.3}), history, NOW, count=1)


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

    assert ids(picks) == ["box_slides_to_stop", "drag_crate", "bat_hits_ball"]
    # choose_principle is the first step of every problem, so the check is never
    # aimed at it.
    assert skills_of(picks) == ["newtons_laws", "work_constant_force", "momentum_impulse"]


def real_state(course: Course, **mastery: float) -> MasteryState:
    """A new student's state for the real course, with some skills set by hand."""
    student = new_mastery_state(course, "sam")
    student.mastery.update(mastery)
    return student


def test_real_course_follow_up_after_a_missed_step() -> None:
    course = load_course(COURSE)
    # The prerequisite of nonconservative_work (energy with friction) is ready.
    student = real_state(course, energy_conservation=0.9, nonconservative_work=0.4)
    # Step 4 of rough_ramp is a nonconservative_work step, answered wrong.
    history = [answer("rough_ramp", step, step != 4) for step in (1, 2, 3, 4)]

    picks = next_problems(course, student, history, NOW)

    first = picks[0]
    assert first.is_follow_up is True
    assert first.target_skill == "nonconservative_work"
    assert first.missed_step == MissedStep(problem_id="rough_ramp", step_position=4)
    # rough_ramp was answered today, so another problem with this skill is picked.
    assert first.problem_id != "rough_ramp"
    assert first.reason.startswith(
        "Picked for you: you missed step 4 of Block sliding down a rough ramp (Energy with friction"
    )
    assert len(set(skills_of(picks))) == 3


def test_real_course_follow_up_steps_back_to_a_prerequisite() -> None:
    course = load_course(COURSE)
    student = new_mastery_state(course, "sam")  # every skill at the starting value
    history = [answer("rough_ramp", step, step != 4) for step in (1, 2, 3, 4)]

    picks = next_problems(course, student, history, NOW)

    # nonconservative_work needs energy_conservation, which needs kinetic_energy and
    # potential_energy (tied, so the first listed wins), which need nothing not ready.
    first = picks[0]
    assert first.target_skill == "kinetic_energy"
    assert first.is_follow_up is True
    assert "builds on Kinetic energy" in first.reason


def test_real_course_review_of_a_mastered_skill() -> None:
    course = load_course(COURSE)
    student = real_state(course, newtons_laws=KNOWN)
    # Four right first tries on Newton's-laws steps (all number steps) last week.
    steps = [("box_slides_to_stop", 2), ("car_power", 2), ("car_power", 4), ("rough_ramp", 3)]
    history = [
        answer(problem_id, position, True, LAST_WEEK + timedelta(minutes=i))
        for i, (problem_id, position) in enumerate(steps)
    ]

    picks = next_problems(course, student, history, NOW)

    first = picks[0]
    assert first.target_skill == "newtons_laws"
    assert first.reason == (
        "Review: you mastered Find a force from Newton's laws: balanced forces, F = ma, "
        "friction = μN 7 days ago; a quick check keeps it fresh."
    )
    assert not first.is_follow_up
    assert len(set(skills_of(picks))) >= 2  # a batch mixes at least two skills


def test_real_course_never_targets_choose_principle() -> None:
    course = load_course(COURSE)
    # A new student misses step 1 (choose_principle) of the bat problem, then gets
    # step 2 (momentum_impulse) right.
    history = [answer("bat_hits_ball", 1, False), answer("bat_hits_ball", 2, True)]
    student = update_mastery(new_mastery_state(course, "sam"), history[0], course)
    student = update_mastery(student, history[1], course)

    # Its mastery is still tracked: the miss lowered it.
    assert student.mastery["choose_principle"] < START_MASTERY
    picks = next_problems(course, student, history, NOW)

    first = picks[0]
    assert first.is_follow_up is True
    assert first.missed_step == MissedStep(problem_id="bat_hits_ball", step_position=1)
    assert first.target_skill == "momentum_impulse"  # the one partway skill
    assert "which every problem practices" in first.reason
    assert "choose_principle" not in skills_of(picks)
    # Nor in the starting check, nor when every problem was done today.
    everything = [answer(problem.id, 1, True) for problem in course.problems]
    for later in (
        next_problems(course, new_mastery_state(course, "sam"), [], NOW),
        next_problems(course, new_mastery_state(course, "sam"), everything, NOW),
    ):
        assert "choose_principle" not in skills_of(later)


def test_real_course_new_student_is_not_given_a_hard_problem_first() -> None:
    course = load_course(COURSE)
    # A new-ish student who has done one step: the first of Car hits a parked truck.
    history = [answer("car_hits_truck", 2, False, LAST_WEEK)]
    student = new_mastery_state(course, "sam")

    picks = next_problems(course, student, history, NOW)

    # No problem fits the 70-85% target at the starting numbers, so the easy problems
    # (difficulty 1) come before the medium and hard ones.
    difficulties = {problem.id: problem.difficulty for problem in course.problems}
    assert all(difficulties[pick.problem_id] == 1 for pick in picks)


def test_real_course_reasons_never_show_ids() -> None:
    course = load_course(COURSE)
    all_ids = [skill.id for skill in course.skills] + [problem.id for problem in course.problems]
    # Ids with an underscore cannot be mistaken for an ordinary word in a sentence.
    all_ids = [some_id for some_id in all_ids if "_" in some_id]
    scenarios = [
        (new_mastery_state(course, "sam"), []),
        (
            real_state(course, energy_conservation=0.9, nonconservative_work=0.4),
            [answer("rough_ramp", step, step != 4) for step in (1, 2, 3, 4)],
        ),
        (
            real_state(course, momentum_impulse=KNOWN),
            streak("bat_hits_ball", LAST_WEEK) + [answer("bat_hits_ball", 2, True, LAST_WEEK)],
        ),
    ]
    for student, history in scenarios:
        for pick in next_problems(course, student, history, NOW, count=3):
            assert not any(some_id in pick.reason for some_id in all_ids), pick.reason
