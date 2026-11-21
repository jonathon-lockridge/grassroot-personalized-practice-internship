"""Say whether a student's answer to one step is right or wrong.

One helper:

- check_answer(step, given): `given` is what the student typed or picked. Gives back
  True if it is right by the rules of the step's kind, and False if not. An answer of
  the wrong sort, such as nothing at all or a word where a number belongs, is simply
  wrong; it never stops the program.

The step is expected to come from a course that passed validate_course in models.py,
so its own answer already has the right sort of value for its kind.

Nothing here knows about algebra or physics, and nothing here touches the web
server or stored data.
"""

import math

from practice_engine.models import Step

# Numbers on a computer are stored in binary, so 5.48 - 5.43 comes out as
# 0.05000000000000071 instead of exactly 0.05. This tiny extra allowance makes an
# answer that sits exactly on the edge of the tolerance count as right.
_ROUNDING_SLACK = 1e-9


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
        try:
            number = float(given)  # float() itself ignores spaces at the ends
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
