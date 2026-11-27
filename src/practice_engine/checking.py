"""Say whether a student's answer to one step is right or wrong.

Two helpers:

- can_read(step, given): `given` is what the student typed or picked. Gives back
  False when it cannot be read at all, such as "five" or "5.48 m/s" typed into a
  number step, so the page can ask the student to type it again instead of marking
  it wrong. The page should call this first, before check_answer.
- check_answer(step, given): gives back True if `given` is right by the rules of the
  step's kind, and False if not. A typed formula (an "expression" step) is right
  when it equals the answer formula for every value of its symbols (formulas.py).
- why_unreadable(step, given): for an expression step, why a typed formula cannot
  be read, or None. An answer of the wrong sort, such as nothing at all
  or a word where a number belongs, is simply wrong; it never stops the program.

A number may be typed with the minus sign "−" that some keyboards and pasted text
use, and with commas between groups of three digits, like 1,400 or -12,000.5. Any
other comma, like 5,48 or 01,400, cannot be read, because it might mean 5.48 or 548.
An underscore, like 1_4, cannot be read either, so a slip is not taken as 14.
Python's own other number forms, such as 1e3 for 1000, are also read.

The step is expected to come from a course that passed validate_course in models.py,
so its own answer already has the right sort of value for its kind.

Nothing here knows about algebra or physics, and nothing here touches the web
server or stored data.
"""

import math
import re

from practice_engine.formulas import FormulaError, equivalent, parse
from practice_engine.models import Step

# The minus sign "−" (a different character from the hyphen "-" on most keyboards)
# that phones, word processors and pasted text often use. It is read as a minus.
_TYPOGRAPHIC_MINUS = "\u2212"
# A number with commas between groups of three digits, like 1,400 or -12,000.5:
# an optional sign, one to three digits not starting with 0, then one or more ",ddd"
# groups, then an optional decimal part. Any other use of a comma does not match.
_THOUSANDS_PATTERN = re.compile(r"[+-]?[1-9]\d{0,2}(,\d{3})+(\.\d*)?")

# Numbers on a computer are stored in binary, so 5.48 - 5.43 comes out as
# 0.05000000000000071 instead of exactly 0.05. This tiny extra allowance makes an
# answer that sits exactly on the edge of the tolerance count as right.
_ROUNDING_SLACK = 1e-9


def can_read(step: Step, given: object) -> bool:
    """False if `given` cannot be read as an answer to `step` at all, True otherwise.

    A wrong answer that can be read, such as 240 instead of -240, gives True here;
    check_answer then says it is wrong. A typing slip should not cost the student
    their first try (PRD decision 9; research report, change 1).
    """
    if step.kind == "choice":
        return isinstance(given, str)
    if step.kind == "number":
        return _read_number(given) is not None
    if step.kind == "order":
        return isinstance(given, list) and all(isinstance(item, str) for item in given)
    if step.kind == "expression":
        return why_unreadable(step, given) is None
    return False  # a kind we do not know; validate_course reports it


def why_unreadable(step: Step, given: object) -> str | None:
    """For an expression step: why the typed formula cannot be read, in plain words,
    or None if it can. A slip like a missing bracket asks again instead of counting
    as wrong."""
    if not isinstance(given, str):
        return "Type a formula."
    try:
        parse(given, step.symbols or [])
    except FormulaError as error:
        return str(error)
    return None


def check_answer(step: Step, given: object) -> bool:
    """True if `given` is a right answer to `step`, False otherwise.

    `object` means `given` may be any sort of value; each kind checks for itself
    that it got the sort it expects.
    """
    if step.kind == "choice":
        return _check_choice(step, given)
    if step.kind == "number":
        return _check_number(step, given)
    if step.kind == "order":
        return _check_order(step, given)
    if step.kind == "expression":
        if why_unreadable(step, given) is not None:
            return False
        return equivalent(given, step.answer, step.symbols or [])
    return False  # a kind we do not know; validate_course reports it


def _same_text(first: str, second: str) -> bool:
    """True if two texts match once capitals and spaces at the ends are ignored.

    The same idea as _repeats in models.py.
    """
    return first.strip().casefold() == second.strip().casefold()


def _check_choice(step: Step, given: object) -> bool:
    # A choice is picked as a text; anything else, such as a list or nothing, is wrong.
    if not isinstance(given, str):
        return False
    return _same_text(given, step.answer)


def _check_number(step: Step, given: object) -> bool:
    number = _read_number(given)
    if number is None:
        return False
    if step.tolerance is None:
        # No tolerance: the number must match. 5 and 5.0 count as the same number.
        return number == step.answer
    return abs(number - step.answer) <= step.tolerance + _ROUNDING_SLACK


def _read_number(given: object) -> float | None:
    """Turn what the student gave into a number, or None if it is not one."""
    # A true/false is not a number here, even though Python treats True as 1.
    if isinstance(given, bool):
        return None
    if isinstance(given, int | float):
        try:
            number = float(given)
        except OverflowError:
            return None  # a whole number far too big to be an answer, such as 10**400
    elif isinstance(given, str):
        text = given.strip().replace(_TYPOGRAPHIC_MINUS, "-")
        if "_" in text:
            return None  # Python would read 1_4 as 14, hiding a typing slip
        if "," in text:
            if not _THOUSANDS_PATTERN.fullmatch(text):
                return None  # a comma that is not between groups of three, like 5,48
            text = text.replace(",", "")
        try:
            number = float(text)
        except ValueError:
            return None  # the text is not a number, such as "five" or ""
    else:
        return None  # nothing, a list, or some other sort of value
    # "nan" and "inf" read as special numbers that are never an ordinary answer.
    if not math.isfinite(number):
        return None
    return number


def _check_order(step: Step, given: object) -> bool:
    # The order is given as a list of texts, one per item.
    if not isinstance(given, list) or len(given) != len(step.answer):
        return False
    # zip pairs the student's first item with the answer's first item, and so on.
    # strict=True would stop with an error if the lengths differed (ruled out above).
    for item, correct in zip(given, step.answer, strict=True):
        if not isinstance(item, str) or not _same_text(item, correct):
            return False
    return True
