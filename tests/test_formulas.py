"""Checks for reading and comparing formulas (formulas.py, decided 2026-11-27)."""

import pytest

from practice_engine.formulas import (
    FormulaError,
    equivalent,
    evaluate,
    fill,
    parse,
    pretty,
    show_number,
)

NAMES = ["F", "theta", "mu", "m", "g", "d", "v0", "beta", "alpha", "D", "h"]


@pytest.mark.parametrize(
    "typed",
    [
        "sqrt(2*g*h)",
        "sqrt(2gh)",
        "√(2gh)",
        "(2*g*h)^(1/2)",
        "(2gh)**0.5",
        "sqrt(2) * sqrt(g h)",
    ],
)
def test_the_same_formula_typed_many_ways_is_right(typed: str) -> None:
    assert equivalent(typed, "sqrt(2*g*h)", NAMES)


@pytest.mark.parametrize("typed", ["sqrt(g*h)", "2*g*h", "sqrt(2*g)*h", "-sqrt(2gh)"])
def test_a_different_formula_is_wrong(typed: str) -> None:
    assert not equivalent(typed, "sqrt(2*g*h)", NAMES)


def test_greek_letters_and_side_by_side_names_are_read() -> None:
    answer = "sqrt(2*d*(F*cos(theta) - mu*(m*g - F*sin(theta)))/m)"

    assert equivalent("sqrt(2d(Fcosθ − μ(mg − Fsinθ))/m)", answer, NAMES)
    assert not equivalent("sqrt(2d(Fcosθ − μmg)/m)", answer, NAMES)  # forgot the lift
    assert equivalent("(3mv0²/(2β))^(1/3)", "(3*m*v0^2/(2*beta))^(1/3)", NAMES)


@pytest.mark.parametrize(
    ("typed", "words"),
    [
        ("__import__('os')", "not one of the symbols"),
        ("m; g", "cannot be used"),
        ("import os", "not one of the symbols"),
        ("x + 1", "not one of the symbols"),
        ("(m + g", "bracket is not closed"),
        ("m + g)", "closing bracket"),
        ("m +", "stops too early"),
        ("", "empty"),
        ("m" * 400, "too long"),
    ],
)
def test_anything_that_is_not_arithmetic_is_refused_plainly(typed: str, words: str) -> None:
    with pytest.raises(FormulaError, match=words):
        parse(typed, NAMES)


def test_impossible_values_are_a_formula_error_not_a_crash() -> None:
    with pytest.raises(FormulaError):
        evaluate(parse("sqrt(m - 10)", NAMES), {"m": 1})
    with pytest.raises(FormulaError):
        evaluate(parse("m/(g - g)", NAMES), {"m": 1, "g": 9.8})
    with pytest.raises(FormulaError):
        evaluate(parse("m^9999", NAMES), {"m": 2})


def test_a_name_written_in_front_is_skipped() -> None:
    assert equivalent("v = sqrt(2gh)", "sqrt(2*g*h)", NAMES)
    assert equivalent("v₀=√(2gh)", "sqrt(2*g*h)", NAMES)


def test_pretty_shows_a_formula_as_a_student_reads_it() -> None:
    assert pretty("(3*m*v0^2/(2*beta))^(1/3)") == "(3·m·v₀²/(2·β))^(1/3)"
    assert pretty("sqrt(2*d*(F*cos(theta) - mu*m*g)/m)") == "√(2·d·(F·cos(θ) − μ·m·g)/m)"


def test_powers_and_signs_follow_the_usual_order() -> None:
    values = {"m": 3.0, "g": 2.0}
    assert evaluate(parse("-m^2", NAMES), values) == -9
    assert evaluate(parse("2^-1", NAMES), values) == 0.5
    assert evaluate(parse("m g^2", NAMES), values) == 12
    assert evaluate(parse("m/g/2", NAMES), values) == 0.75


def test_blanks_are_filled_with_numbers_as_physics_texts_write_them() -> None:
    values = {"m": 2.0, "x": 1.5, "W": -239.2, "v": 0.4864, "thing": "sled"}

    assert fill("A {m} kg {thing} moves {x} m", values) == "A 2.0 kg sled moves 1.5 m"
    assert fill("W = {W:.0f} J, v = {v}", values) == "W = −239 J, v = 0.486"
    with pytest.raises(FormulaError, match="no value"):
        fill("{nope}", values)


@pytest.mark.parametrize(
    ("x", "shown"),
    [
        (2, "2.0"),
        (0.5, "0.50"),
        (12, "12"),
        (1400, "1400"),
        (5.4772, "5.48"),
        (-0.6214, "−0.621"),
        (0, "0"),
    ],
)
def test_show_number(x: float, shown: str) -> None:
    assert show_number(x) == shown


# Found by a review, 2026-11-27.


def test_digits_after_a_name_multiply_it() -> None:
    assert equivalent("v2", "2*v", ["v"])
    assert equivalent("v√(2)", "v*sqrt(2)", ["v"])


def test_a_function_needs_brackets_except_sin_cos_tan_before_one_angle() -> None:
    with pytest.raises(FormulaError, match="Put brackets after sqrt"):
        parse("2√gh", NAMES)
    assert equivalent("F cos θ d", "F*cos(theta)*d", NAMES)


def test_a_number_with_two_points_is_refused() -> None:
    with pytest.raises(FormulaError, match="not a number"):
        parse("1.5.5", NAMES)


def test_a_long_run_of_letters_is_split_quickly() -> None:
    with pytest.raises(FormulaError):
        parse("mu" * 140 + "q", ["m", "u", "mu"])


def test_an_answer_defined_only_for_some_values_still_matches_itself() -> None:
    assert equivalent("sqrt(v^2 - 2gh)", "sqrt(v^2 - 2*g*h)", ["v", "g", "h"])


def test_bad_format_specs_and_minus_zero() -> None:
    with pytest.raises(FormulaError, match="not a number format"):
        fill("{m:d}", {"m": 2.5})
    assert fill("{a:.1f}", {"a": -0.04}) == "0.0"


@pytest.mark.parametrize(("x", "shown"), [(99.95, "100"), (1234.5, "1230"), (1e300, "1e+300")])
def test_show_number_rounds_to_three_figures_first(x: float, shown: str) -> None:
    assert show_number(x) == shown
