"""Checks for the mastery update (step T2)."""

from datetime import datetime
from pathlib import Path

import pytest

from practice_engine.mastery import START_MASTERY, new_mastery_state, update_mastery
from practice_engine.models import StepAnswer, load_course

# The course file, found from this test file's own location (see test_models.py).
COURSE = (
    Path(__file__).resolve().parents[1] / "data" / "ap-physics-c-energy-momentum" / "course.json"
)

# In the course, problem push_cart has three steps:
# step 1 is a choice step with 3 options, skill work_energy_theorem;
# step 2 is a number step, skill work_constant_force.
CHOICE_SKILL = "work_energy_theorem"
NUMBER_SKILL = "work_constant_force"


def answer(position: int, correct: bool, seconds: float = 20) -> StepAnswer:
    """A step answer by student "sam" on problem push_cart."""
    return StepAnswer(
        nickname="sam",
        problem_id="push_cart",
        step_position=position,
        correct=correct,
        seconds=seconds,
        hints_used=0,
        answered_at=datetime(2026, 11, 20, 10, 0),
    )


def test_new_student_has_every_skill_at_the_starting_value() -> None:
    course = load_course(COURSE)

    state = new_mastery_state(course, "sam")

    assert state.nickname == "sam"
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
    # Many wrong number steps push work_energy_theorem to its lowest number-step value
    # (problem drag_crate step 5 is a number step on that skill).
    number_miss = answer(5, correct=False).model_copy(update={"problem_id": "drag_crate"})
    for _ in range(50):
        state = update_mastery(state, number_miss, course)
    low = state.mastery[CHOICE_SKILL]

    # A wrong choice step on the same skill, slow or fast, must not lift it.
    for seconds in (20, 2):
        after = update_mastery(state, answer(1, correct=False, seconds=seconds), course)
        assert after.mastery[CHOICE_SKILL] <= low


def test_order_step_uses_its_own_guess_chance() -> None:
    course = load_course(COURSE)
    state = new_mastery_state(course, "sam")
    # Problem spring_launch step 1 orders 3 items (skill energy_conservation), so the
    # guess chance is 1 in 6. Right answer, from 0.2:
    #   knows and did not slip:      0.2 x 0.9   = 0.18
    #   does not know and guessed:   0.8 x 1/6   = 0.133333
    #   after the answer:            0.18 / (0.18 + 0.133333) = 0.574468
    #   after learning:              0.574468 + (1 - 0.574468) x 0.15 = 0.638298
    order_answer = answer(1, correct=True).model_copy(update={"problem_id": "spring_launch"})

    after = update_mastery(state, order_answer, course)

    assert after.mastery["energy_conservation"] == pytest.approx(0.638298, abs=1e-6)


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

    # Right answer on the number step (guess chance 0.05), from 0.2:
    #   knows and did not slip:      0.2 x 0.9  = 0.18
    #   does not know and guessed:   0.8 x 0.05 = 0.04
    #   after the answer:            0.18 / (0.18 + 0.04) = 0.818182
    #   after learning:              0.818182 + (1 - 0.818182) x 0.15 = 0.845455
    right = update_mastery(state, answer(2, correct=True), course)
    assert right.mastery[NUMBER_SKILL] == pytest.approx(0.845455, abs=1e-6)

    # Wrong answer on the choice step (3 options: 1 in 3, capped at 0.3), from 0.2:
    #   knows but slipped:             0.2 x 0.1 = 0.02
    #   does not know, did not guess:  0.8 x 0.7 = 0.56
    #   after the answer:              0.02 / (0.02 + 0.56) = 0.034483
    #   after learning:                0.034483 + (1 - 0.034483) x 0.15 = 0.179310
    wrong = update_mastery(state, answer(1, correct=False), course)
    assert wrong.mastery[CHOICE_SKILL] == pytest.approx(0.179310, abs=1e-6)

    # The same wrong answer in 2 seconds keeps half the change:
    #   0.2 + (0.179310 - 0.2) x 0.5 = 0.189655
    fast = update_mastery(state, answer(1, correct=False, seconds=2), course)
    assert fast.mastery[CHOICE_SKILL] == pytest.approx(0.189655, abs=1e-6)


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
