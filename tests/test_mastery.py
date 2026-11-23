"""Checks for the mastery update (step T2 and its follow-up)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from practice_engine.mastery import (
    HINT_CREDIT,
    MASTERED,
    MASTERY_STREAK,
    START_MASTERY,
    chance_correct,
    counts_as_right,
    find_step,
    has_mastery_streak,
    is_mastered,
    new_mastery_state,
    right_after_hint,
    step_table,
    update_mastery,
)
from practice_engine.models import Course, MasteryState, StepAnswer, load_course

# The course file, found from this test file's own location (see test_models.py).
COURSE = (
    Path(__file__).resolve().parents[1] / "data" / "ap-physics-c-energy-momentum" / "course.json"
)

# In the course, problem push_cart has three steps:
# step 1 is a choice step with 4 options, skill choose_principle;
# step 2 is a number step, skill work_constant_force.
CHOICE_SKILL = "choose_principle"
NUMBER_SKILL = "work_constant_force"

START_TIME = datetime(2026, 11, 20, 10, 0)


def answer(
    position: int,
    correct: bool,
    seconds: float = 20,
    hints_used: int = 0,
    attempt: int = 1,
    minute: int = 0,
) -> StepAnswer:
    """A step answer by student "sam" on problem push_cart, `minute` minutes after 10:00."""
    return StepAnswer(
        nickname="sam",
        problem_id="push_cart",
        step_position=position,
        correct=correct,
        seconds=seconds,
        hints_used=hints_used,
        answered_at=START_TIME + timedelta(minutes=minute),
        attempt=attempt,
    )


def test_new_student_has_every_skill_at_the_starting_value() -> None:
    course = load_course(COURSE)

    state = new_mastery_state(course, "sam")

    assert state.nickname == "sam"
    assert state.course_id == course.id
    assert set(state.mastery) == {skill.id for skill in course.skills}
    assert all(value == START_MASTERY for value in state.mastery.values())


def test_mastery_rises_on_a_correct_step() -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")

    after = update_mastery(state, answer(1, correct=True), course)

    assert after.mastery[CHOICE_SKILL] > START_MASTERY


def test_mastery_falls_on_a_wrong_step() -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")

    after = update_mastery(state, answer(1, correct=False), course)

    assert after.mastery[CHOICE_SKILL] < START_MASTERY


def test_only_the_step_skill_changes() -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")

    after = update_mastery(state, answer(1, correct=True), course)

    for skill_id, value in after.mastery.items():
        if skill_id != CHOICE_SKILL:
            assert value == START_MASTERY


@pytest.mark.parametrize("correct", [True, False])
def test_mastery_stays_between_0_and_1_after_many_answers(correct: bool) -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")

    for _ in range(200):
        state = update_mastery(state, answer(2, correct=correct), course)
        assert 0 <= state.mastery[NUMBER_SKILL] <= 1


def test_wrong_step_never_raises_mastery_after_earlier_misses() -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")
    # Many wrong number steps push work_constant_force to its lowest number-step value
    # (problem push_cart step 2 is a number step on that skill).
    for _ in range(50):
        state = update_mastery(state, answer(2, correct=False), course)
    low = state.mastery[NUMBER_SKILL]

    # A wrong choice step on the same skill (problem drag_crate step 3, 3 options), slow,
    # fast or after a hint, must not lift it.
    for wrong in (
        answer(3, correct=False, seconds=20),
        answer(3, correct=False, seconds=2),
        answer(3, correct=False, hints_used=1),
    ):
        wrong = wrong.model_copy(update={"problem_id": "drag_crate"})
        after = update_mastery(state, wrong, course)
        assert after.mastery[NUMBER_SKILL] <= low


@pytest.mark.parametrize(
    ("kind", "problem_id", "position", "skill"),
    [
        ("number", "push_cart", 2, NUMBER_SKILL),
        ("choice with 4 options", "push_cart", 1, CHOICE_SKILL),
        ("choice with 3 options", "drag_crate", 3, NUMBER_SKILL),
        ("order of 3 items", "spring_launch", 2, "energy_conservation"),
    ],
)
def test_reaching_mastered_takes_4_to_6_right_first_tries(
    kind: str, problem_id: str, position: int, skill: str
) -> None:
    # Count how many right first tries in a row take a new student to MASTERED.
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")
    right = answer(position, correct=True).model_copy(update={"problem_id": problem_id})

    steps = 0
    while state.mastery[skill] < MASTERED:
        state = update_mastery(state, right, course)
        steps += 1
        assert steps <= 6, f"a {kind} step has not reached {MASTERED} after 6 right steps"

    assert steps >= 4, f"a {kind} step reached {MASTERED} after only {steps} right steps"


def test_order_step_uses_its_own_guess_chance() -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")
    # Problem spring_launch step 2 orders 3 items (skill energy_conservation): 1 in 6,
    # raised to the lowest guess chance allowed, 0.2. Right answer, from 0.1:
    #   knows and did not slip:      0.1 x 0.85 = 0.085
    #   does not know and guessed:   0.9 x 0.2  = 0.18
    #   after the answer:            0.085 / (0.085 + 0.18) = 0.320755
    #   after learning:              0.320755 + (1 - 0.320755) x 0.05 = 0.354717
    order_answer = answer(2, correct=True).model_copy(update={"problem_id": "spring_launch"})

    after = update_mastery(state, order_answer, course)

    assert after.mastery["energy_conservation"] == pytest.approx(0.354717, abs=1e-6)


def test_wrong_step_taking_exactly_3_seconds_gets_the_full_change() -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")

    slow = update_mastery(state, answer(1, correct=False, seconds=20), course)
    edge = update_mastery(state, answer(1, correct=False, seconds=3), course)

    assert edge.mastery[CHOICE_SKILL] == slow.mastery[CHOICE_SKILL]


def test_state_missing_a_skill_is_refused() -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")
    del state.mastery[CHOICE_SKILL]

    with pytest.raises(ValueError, match=CHOICE_SKILL):
        update_mastery(state, answer(1, correct=True), course)


def test_fast_wrong_step_moves_mastery_less() -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")

    slow = update_mastery(state, answer(1, correct=False, seconds=20), course)
    fast = update_mastery(state, answer(1, correct=False, seconds=2), course)

    slow_drop = START_MASTERY - slow.mastery[CHOICE_SKILL]
    fast_drop = START_MASTERY - fast.mastery[CHOICE_SKILL]
    assert 0 < fast_drop < slow_drop


def test_matches_hand_computed_examples() -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")

    # Right answer on the number step (guess chance 0.2, slip 0.15), from 0.1:
    #   knows and did not slip:      0.1 x 0.85 = 0.085
    #   does not know and guessed:   0.9 x 0.2  = 0.18
    #   after the answer:            0.085 / (0.085 + 0.18) = 0.320755
    #   after learning:              0.320755 + (1 - 0.320755) x 0.05 = 0.354717
    right = update_mastery(state, answer(2, correct=True), course)
    assert right.mastery[NUMBER_SKILL] == pytest.approx(0.354717, abs=1e-6)

    # Wrong answer on the choice step (4 options: 1 in 4, so 0.25), from 0.1:
    #   knows but slipped:             0.1 x 0.15 = 0.015
    #   does not know, did not guess:  0.9 x 0.75 = 0.675
    #   after the answer:              0.015 / (0.015 + 0.675) = 0.021739
    #   after learning:                0.021739 + (1 - 0.021739) x 0.05 = 0.070652
    wrong = update_mastery(state, answer(1, correct=False), course)
    assert wrong.mastery[CHOICE_SKILL] == pytest.approx(0.070652, abs=1e-6)

    # The same wrong answer in 2 seconds keeps half the change:
    #   0.1 + (0.070652 - 0.1) x 0.5 = 0.085326
    fast = update_mastery(state, answer(1, correct=False, seconds=2), course)
    assert fast.mastery[CHOICE_SKILL] == pytest.approx(0.085326, abs=1e-6)


def test_second_try_leaves_mastery_unchanged() -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")

    for correct in (True, False):
        after = update_mastery(state, answer(1, correct=correct, attempt=2), course)
        assert after == state
        assert after is not state  # a copy, so changing it cannot change the original


def test_right_after_a_hint_gets_half_the_rise_of_a_right_answer() -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")

    # A right answer with no hint on the number step goes from 0.1 to 0.354717 (see
    # test_matches_hand_computed_examples). After a hint, only half of that rise is kept:
    #   0.1 + (0.354717 - 0.1) x 0.5 = 0.227358
    hinted = update_mastery(state, answer(2, correct=True, hints_used=1), course)
    assert hinted.mastery[NUMBER_SKILL] == pytest.approx(0.227358, abs=1e-6)
    assert HINT_CREDIT == 0.5

    # The same holds on a choice step: above where it started, below a right answer.
    plain = update_mastery(state, answer(1, correct=True), course)
    hinted_choice = update_mastery(state, answer(1, correct=True, hints_used=2), course)
    rise = plain.mastery[CHOICE_SKILL] - START_MASTERY
    assert hinted_choice.mastery[CHOICE_SKILL] == pytest.approx(START_MASTERY + rise / 2)


def test_wrong_after_a_hint_is_an_ordinary_wrong_answer() -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")

    hinted = update_mastery(state, answer(1, correct=False, hints_used=1), course)
    wrong = update_mastery(state, answer(1, correct=False), course)

    assert hinted.mastery[CHOICE_SKILL] == wrong.mastery[CHOICE_SKILL]


def test_fast_answer_after_a_hint_is_not_treated_as_a_guess() -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")

    # A wrong answer after a hint gets the full change, even if it was quick.
    fast_hinted = update_mastery(state, answer(1, correct=False, seconds=2, hints_used=1), course)
    slow_wrong = update_mastery(state, answer(1, correct=False, seconds=20), course)

    assert fast_hinted.mastery[CHOICE_SKILL] == slow_wrong.mastery[CHOICE_SKILL]


def test_state_for_another_course_is_refused() -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam").model_copy(update={"course_id": "other-course"})

    with pytest.raises(ValueError, match="other-course"):
        update_mastery(state, answer(1, correct=True), course)


def test_mastered_needs_the_number_and_a_streak() -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")
    history = []
    # Right first tries on the choice step, one a minute, until the number is high.
    for minute in range(6):
        right = answer(1, correct=True, minute=minute)
        state = update_mastery(state, right, course)
        history.append(right)
    assert state.mastery[CHOICE_SKILL] >= MASTERED

    assert is_mastered(state, history, CHOICE_SKILL, course) is True
    # The number alone is not enough: with too few answers there is no streak.
    assert is_mastered(state, history[: MASTERY_STREAK - 1], CHOICE_SKILL, course) is False
    # A right answer after a hint is skipped: it neither breaks the streak ...
    hinted = answer(1, correct=True, hints_used=1, minute=10)
    assert is_mastered(state, [*history, hinted], CHOICE_SKILL, course) is True
    # ... nor counts toward one: two right answers plus a hinted one are not enough.
    two_and_hinted = [*history[:2], hinted]
    assert is_mastered(state, two_and_hinted, CHOICE_SKILL, course) is False
    # A wrong answer after a hint is a miss, so it does break the streak.
    hinted_miss = answer(1, correct=False, hints_used=1, minute=12)
    assert is_mastered(state, [*history, hinted_miss], CHOICE_SKILL, course) is False
    # A second try is not a first try, so it neither breaks nor builds the streak.
    retry = answer(1, correct=False, attempt=2, minute=11)
    assert is_mastered(state, [*history, retry], CHOICE_SKILL, course) is True


def test_not_mastered_below_the_line_even_with_a_streak() -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")
    history = [answer(1, correct=True, minute=minute) for minute in range(MASTERY_STREAK)]

    assert is_mastered(state, history, CHOICE_SKILL, course) is False


def test_streak_uses_the_newest_answers_by_time() -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")
    state.mastery[CHOICE_SKILL] = 0.99
    rights = [answer(1, correct=True, minute=minute) for minute in range(MASTERY_STREAK)]
    # The newest answer is a miss, even though it comes first in the list.
    miss = answer(1, correct=False, minute=30)

    assert is_mastered(state, [miss, *rights], CHOICE_SKILL, course) is False


def test_chance_correct_matches_hand_computed_examples() -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")
    push_cart = course.problems[0]
    assert push_cart.id == "push_cart"

    # Choice step (4 options), from 0.1: 0.1 x 0.85 + 0.9 x 0.25 = 0.31
    assert chance_correct(state, push_cart.steps[0], course) == pytest.approx(0.31)
    # Number step, from 0.1: 0.1 x 0.85 + 0.9 x 0.2 = 0.265
    assert chance_correct(state, push_cart.steps[1]) == pytest.approx(0.265)


def test_the_state_passed_in_is_not_changed() -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")
    copy_before = state.model_copy(deep=True)

    update_mastery(state, answer(1, correct=True), course)

    assert state == copy_before


@pytest.mark.parametrize("position", [0, 4, 99])
def test_bad_step_position_is_refused(position: int) -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")

    with pytest.raises(ValueError, match="no step"):
        update_mastery(state, answer(position, correct=True), course)


def test_unknown_problem_is_refused() -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")
    bad = answer(1, correct=True).model_copy(update={"problem_id": "no_such_problem"})

    with pytest.raises(ValueError, match="no_such_problem"):
        update_mastery(state, bad, course)


def test_answer_from_another_student_is_refused() -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "alex")

    with pytest.raises(ValueError, match="sam"):
        update_mastery(state, answer(1, correct=True), course)


@pytest.mark.parametrize(("field", "value"), [("attempt", 0), ("attempt", -5), ("hints_used", -1)])
def test_impossible_attempt_or_hint_count_is_refused(field: str, value: int) -> None:
    fields = answer(1, correct=True).model_dump()
    fields[field] = value

    with pytest.raises(ValidationError):
        StepAnswer(**fields)


def mastered_choice_skill() -> tuple[Course, MasteryState, list[StepAnswer]]:
    """A course, a state at 0.99 on CHOICE_SKILL, and a streak of right first tries."""
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")
    state.mastery[CHOICE_SKILL] = 0.99
    rights = [answer(1, correct=True, minute=minute) for minute in range(MASTERY_STREAK)]
    return course, state, rights


def test_streak_ignores_other_students_answers() -> None:
    course, state, rights = mastered_choice_skill()
    alex_miss = answer(1, correct=False, minute=30).model_copy(update={"nickname": "alex"})

    assert is_mastered(state, [*rights, alex_miss], CHOICE_SKILL, course) is True


def test_streak_ignores_answers_to_steps_no_longer_in_the_course() -> None:
    course, state, rights = mastered_choice_skill()
    removed = answer(1, correct=False, minute=30).model_copy(update={"problem_id": "gone"})

    assert is_mastered(state, [*rights, removed], CHOICE_SKILL, course) is True


def test_streak_with_mixed_time_zones_is_refused() -> None:
    course, state, rights = mastered_choice_skill()
    with_zone = answer(1, correct=True).model_copy(
        update={"answered_at": datetime(2026, 11, 21, tzinfo=UTC)}
    )

    with pytest.raises(ValueError, match="time zone"):
        is_mastered(state, [*rights, with_zone], CHOICE_SKILL, course)


def test_is_mastered_and_chance_correct_refuse_another_course() -> None:
    course, state, rights = mastered_choice_skill()
    other = state.model_copy(update={"course_id": "other-course"})

    with pytest.raises(ValueError, match="other-course"):
        is_mastered(other, rights, CHOICE_SKILL, course)
    with pytest.raises(ValueError, match="other-course"):
        chance_correct(other, course.problems[0].steps[0], course)


def test_chance_correct_treats_a_missing_skill_as_new() -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")
    del state.mastery[CHOICE_SKILL]

    # Same as the starting value: 0.1 x 0.85 + 0.9 x 0.25 = 0.31
    assert START_MASTERY == 0.1
    assert chance_correct(state, course.problems[0].steps[0]) == pytest.approx(0.31)


# The shared helpers, used by selection.py and storage.py too.


def test_counts_as_right_needs_a_right_answer_with_no_hint() -> None:
    assert counts_as_right(answer(1, True)) is True
    assert counts_as_right(answer(1, True, hints_used=1)) is False
    assert counts_as_right(answer(1, False)) is False


def test_right_after_hint_is_only_a_right_answer_with_a_hint() -> None:
    assert right_after_hint(answer(1, True, hints_used=2)) is True
    assert right_after_hint(answer(1, True)) is False
    assert right_after_hint(answer(1, False, hints_used=1)) is False


def test_find_step_gives_the_step_or_a_plain_error() -> None:
    course = load_course(COURSE)

    assert find_step(course, "push_cart", 2).skill == NUMBER_SKILL
    with pytest.raises(ValueError, match="no step 9"):
        find_step(course, "push_cart", 9)
    with pytest.raises(ValueError, match="no problem 'gone'"):
        find_step(course, "gone", 1)


def test_step_table_has_every_step_by_problem_and_position() -> None:
    course = load_course(COURSE)

    table = step_table(course)

    assert len(table) == sum(len(problem.steps) for problem in course.problems)
    assert table[("push_cart", 1)].skill == CHOICE_SKILL
    assert table[("push_cart", 2)] is find_step(course, "push_cart", 2)
    assert ("push_cart", 0) not in table


def test_has_mastery_streak_looks_at_the_newest_first_tries_only() -> None:
    right = [answer(2, True, minute=i) for i in range(MASTERY_STREAK)]
    hinted = answer(2, True, hints_used=1, minute=50)

    assert has_mastery_streak(right) is True
    assert has_mastery_streak(right[1:]) is False  # too few
    assert has_mastery_streak([answer(2, False, minute=-1)] + right) is True  # old miss
    assert has_mastery_streak(right + [answer(2, False, minute=60)]) is False  # new miss
    assert has_mastery_streak(right + [hinted]) is True  # a hinted right one is skipped
