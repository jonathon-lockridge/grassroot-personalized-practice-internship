"""Checks for saying whether a student's answer to a step is right (step T1c)."""

from pathlib import Path

import pytest

from practice_engine.checking import can_read, check_answer
from practice_engine.models import Step, load_course

# The course file, found from this test file's own location (see test_models.py).
COURSE = (
    Path(__file__).resolve().parents[1] / "data" / "ap-physics-c-energy-momentum" / "course.json"
)


def real_step(problem_id: str, position: int) -> Step:
    """One step from the physics course. `position` counts from 1, like a person."""
    course = load_course(COURSE)
    problem = next(problem for problem in course.problems if problem.id == problem_id)
    return problem.steps[position - 1]


def made_up_step(kind: str, answer: object, **fields: object) -> Step:
    """A small step written here, for cases the course file does not have."""
    return Step(prompt="A question", kind=kind, answer=answer, hint="A hint", skill="s", **fields)


# A right and a wrong answer for each of the three kinds (the Done-when in TODO.md),
# using real steps from the physics course.


def test_choice_right_and_wrong() -> None:
    step = real_step("push_cart", 1)  # answer: "Work-energy theorem (net work ...)"

    assert check_answer(step, "Work-energy theorem (net work equals change in kinetic energy)")
    assert not check_answer(step, "Conservation of momentum")


def test_number_right_and_wrong() -> None:
    step = real_step("drag_crate", 4)  # answer: -240, no tolerance

    assert check_answer(step, -240)
    assert not check_answer(step, 240)  # the sign matters


def test_order_right_and_wrong() -> None:
    step = real_step("spring_launch", 2)
    right = list(step.answer)

    assert check_answer(step, right)
    assert not check_answer(step, list(reversed(right)))
    assert not check_answer(step, [right[1], right[0], *right[2:]])  # two items swapped


# Choice steps.


def test_choice_ignores_capitals_and_end_spaces() -> None:
    step = real_step("push_cart", 1)

    assert check_answer(step, "  work-ENERGY theorem (net work equals change in kinetic energy) ")


def test_choice_wrong_sort_of_answer_is_wrong() -> None:
    step = real_step("push_cart", 1)

    assert not check_answer(step, None)
    assert not check_answer(
        step, ["Work-energy theorem (net work equals change in kinetic energy)"]
    )
    assert not check_answer(step, 0)  # a position number, not the option's text
    assert not check_answer(step, True)


# Number steps.


def test_number_typed_as_text_with_spaces() -> None:
    step = real_step("push_cart", 3)  # answer: 5.48, tolerance 0.05

    assert check_answer(step, " 5.48 ")


def test_negative_number_typed_as_text() -> None:
    step = real_step("drag_crate", 4)  # answer: -240

    assert check_answer(step, "-240")
    assert not check_answer(step, "240")


@pytest.mark.parametrize("given", [5.43, 5.53, "5.43", "5.53"])
def test_tolerance_edge_counts_as_right(given: object) -> None:
    # 5.43 is exactly 0.05 below 5.48, but a computer works it out as slightly more.
    step = real_step("push_cart", 3)

    assert check_answer(step, given)


@pytest.mark.parametrize("given", [5.42, 5.54])
def test_just_outside_tolerance_is_wrong(given: float) -> None:
    step = real_step("push_cart", 3)

    assert not check_answer(step, given)


def test_whole_number_and_decimal_are_the_same() -> None:
    step = made_up_step("number", 5)

    assert check_answer(step, 5)
    assert check_answer(step, 5.0)
    assert check_answer(step, "5.0")
    assert not check_answer(step, 5.01)  # no tolerance, so it must match


@pytest.mark.parametrize("given", ["five", "", "   ", "5 m", "nan", "inf", "5,48"])
def test_text_that_is_not_a_number_is_wrong(given: str) -> None:
    step = real_step("push_cart", 3)

    assert not check_answer(step, given)


@pytest.mark.parametrize("given", [True, False, None, [5.48], {"answer": 5.48}, 10**400])
def test_number_wrong_sort_of_answer_is_wrong(given: object) -> None:
    step = made_up_step("number", 1)  # True would pass as 1 if it were not refused

    assert not check_answer(step, given)


def test_typographic_minus_is_a_minus() -> None:
    step = real_step("drag_crate", 4)  # answer: -240

    assert check_answer(step, "\u2212240")  # "−240", as phones and pasted text write it
    assert check_answer(step, " \u2212240 ")
    assert not check_answer(step, "240")


@pytest.mark.parametrize(
    ("given", "number"),
    [
        ("1,400", 1400),
        ("12,000.5", 12000.5),
        ("-1,400", -1400),
        ("\u22121,400", -1400),  # the typographic minus and a comma together
        ("1,234,567", 1234567),
        (" 1,400 ", 1400),
    ],
)
def test_commas_between_groups_of_three(given: str, number: float) -> None:
    step = made_up_step("number", number)

    assert can_read(step, given)
    assert check_answer(step, given)


@pytest.mark.parametrize(
    "given",
    ["5,48", "1,40", "1,4000", ",400", "1,400,", "1,,400", "1.400,5", "01,400", "0,400", "000,000"],
)
def test_other_commas_cannot_be_read(given: str) -> None:
    step = made_up_step("number", 1400)

    assert not can_read(step, given)
    assert not check_answer(step, given)


# can_read: can the answer be read at all? Readable but wrong still gives True.


def test_can_read_number_step() -> None:
    step = real_step("push_cart", 3)  # answer: 5.48

    assert can_read(step, 5.48)
    assert can_read(step, "5.48")
    assert can_read(step, "999")  # wrong, but it is a number
    assert can_read(step, "\u22125.48")


@pytest.mark.parametrize(
    "given",
    [
        "five",
        "",
        "   ",
        "5.48 m/s",
        "5.48m",
        "nan",
        "inf",
        "1_000",
        "5_48",
        None,
        True,
        [5.48],
        10**400,
    ],
)
def test_can_read_number_step_refuses(given: object) -> None:
    step = real_step("push_cart", 3)

    assert not can_read(step, given)


def test_can_read_choice_step() -> None:
    step = real_step("push_cart", 1)

    assert can_read(step, "Work-energy theorem (net work equals change in kinetic energy)")
    assert can_read(step, "Conservation of momentum")  # wrong, but it is a text
    assert not can_read(step, None)
    assert not can_read(step, 0)
    assert not can_read(step, ["Conservation of momentum"])


def test_can_read_order_step() -> None:
    step = real_step("spring_launch", 2)
    right = list(step.answer)

    assert can_read(step, right)
    assert can_read(step, list(reversed(right)))  # wrong, but a list of texts
    assert can_read(step, right[:-1])  # too short is wrong, not unreadable
    assert not can_read(step, None)
    assert not can_read(step, right[0])
    assert not can_read(step, tuple(right))
    assert not can_read(step, [right[0], 3])


def test_can_read_unknown_kind() -> None:
    step = made_up_step("drawing", "x")

    assert not can_read(step, "x")


# Order steps.


def test_order_ignores_capitals_and_end_spaces() -> None:
    step = real_step("spring_launch", 2)
    given = [f"  {item.upper()} " for item in step.answer]

    assert check_answer(step, given)


def test_order_wrong_length_is_wrong() -> None:
    step = real_step("spring_launch", 2)
    right = list(step.answer)

    assert not check_answer(step, right[:-1])  # one item missing
    assert not check_answer(step, right + [right[0]])  # one item extra
    assert not check_answer(step, [])


def test_order_wrong_sort_of_answer_is_wrong() -> None:
    step = real_step("spring_launch", 2)
    right = list(step.answer)

    assert not check_answer(step, None)
    assert not check_answer(step, right[0])  # one text, not a list
    assert not check_answer(step, tuple(right))  # a list is expected
    assert not check_answer(step, [right[0], right[1], 3])  # an item that is not text
