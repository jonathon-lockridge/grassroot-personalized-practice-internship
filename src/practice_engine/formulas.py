"""Read and work out formulas, such as sqrt(2*g*h), safely (decided 2026-11-27).

Formulas appear in two places:

- In a course file, a problem with changing numbers (a template; see models.py)
  works out its answers from its numbers, such as "0.5*m*v^2".
- A student types a formula as the answer to an "expression" step, such as
  "sqrt(2gh)", and it is right if it equals the course's formula for every value of
  the symbols (checked at many random values, as online homework systems do).

Nothing here runs Python code from the text: the text is cut into pieces (numbers,
names, + - * / ^ and brackets) and read by the small grammar below, so a formula can
only ever do arithmetic.

The helpers:

- parse(text, names): read a formula that may use only the given names (plus the
  functions and constants below). Stops with a FormulaError, in plain words, when it
  cannot be read.
- evaluate(formula, values): work it out for given values of its names.
- equivalent(given, answer, names): True if two formulas are equal for any values.
- fill(text, values): put values into a text's {blanks}, like "a {m} kg cart".
- show_number(x): a number as a student reads it, to 3 significant figures.
- pretty(text): a course formula as a student reads it, like √(2·g·h).

What a student may type: numbers, the given symbols, + - * / and ^ (or **) for
powers, brackets, sqrt, cbrt, sin, cos, tan, ln, exp, abs, and pi. Writing two things
side by side multiplies them, so "2gh" means 2*g*h and "mv^2" means m*v^2. A function
needs brackets, as "√gh" could mean √(gh) or √g·h, except sin, cos and tan before a
single angle, like "cos θ". Greek
letters may be typed as θ or theta, μ or mu, and so on. "×", "·", "−", "√", "²" and
"³" are read too, and a name with "=" in front, like "v = sqrt(2gh)", is skipped.
"""

import functools
import math
import random
import re
from collections.abc import Iterable

FUNCTIONS = {
    "sqrt": math.sqrt,
    "cbrt": lambda x: math.copysign(abs(x) ** (1 / 3), x),
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "ln": math.log,
    "exp": math.exp,
    "abs": abs,
}
CONSTANTS = {"pi": math.pi}
# Characters people type or paste, and what they mean.
_SWAPS = {
    "×": "*",
    "·": "*",
    "⋅": "*",
    "÷": "/",
    "−": "-",
    "√": "sqrt",
    "²": "^2",
    "³": "^3",
    "θ": "theta",
    "μ": "mu",
    "α": "alpha",
    "β": "beta",
    "ω": "omega",
    "φ": "phi",
    "λ": "lambda",
    "π": "pi",
    "₀": "0",
}
# The symbols' random values when two formulas are compared (see equivalent).
_SAMPLE_RANGE = (0.5, 1.5)
_SAMPLES = 40
_MAX_DRAWS = 400
_MIN_GOOD_SAMPLES = 8
_SAME = 1e-7  # relative difference below which two values count as equal
_TINY = 1e-12  # ...plus this, so two values that are both about 0 count as equal
_MAX_BRACKETS = 40
# Functions that may be written without brackets before a single angle, like "cos θ".
_TRIG = {"sin", "cos", "tan"}

# A formula after reading: a small tree of tuples, such as
# ("+", ("num", 2.0), ("name", "g")). The first item says what it is.
Formula = tuple


class FormulaError(ValueError):
    """A formula that cannot be read or worked out, with a plain message."""


def parse(text: str, names: Iterable[str]) -> Formula:
    """Read `text` as a formula that may use `names`, the functions and pi."""
    if not isinstance(text, str):
        raise FormulaError("The formula is empty.")
    return _parse(text, frozenset(names))


@functools.lru_cache(maxsize=4096)
def _parse(text: str, names: frozenset[str]) -> Formula:
    """parse, kept for texts read before: a template's formulas are read for every
    variant. The result is made of tuples, so it can never be changed by a caller."""
    if not text.strip():
        raise FormulaError("The formula is empty.")
    if len(text) > 300:
        raise FormulaError("The formula is too long.")
    # "v = sqrt(2gh)": a student may write what the formula is for; keep the right side.
    named = re.fullmatch(r"\s*[A-Za-z_][A-Za-z0-9_₀]*\s*=(.*)", text, flags=re.DOTALL)
    if named:
        text = named.group(1)
    opened, closed = text.count("("), text.count(")")
    if opened > _MAX_BRACKETS:
        raise FormulaError("The formula has too many brackets.")
    if opened > closed:
        raise FormulaError("A bracket is not closed.")
    if closed > opened:
        raise FormulaError("There is a closing bracket with no opening one.")
    tokens = _tokens(text, set(names))
    reader = _Reader(tokens)
    try:
        formula = reader.sum()
    except RecursionError:
        raise FormulaError("The formula is nested too deeply.") from None
    if reader.peek() is not None:
        raise FormulaError(f"Could not read the formula after '{reader.peek()[1]}'.")
    return formula


def evaluate(formula: Formula, values: dict[str, float]) -> float:
    """Work the formula out. Stops with a FormulaError if that is impossible, such as
    the square root of a negative number or a division by zero."""
    try:
        result = _work_out(formula, values)
    except (ValueError, ZeroDivisionError, OverflowError, RecursionError) as error:
        raise FormulaError(f"The formula cannot be worked out here ({error}).") from None
    if isinstance(result, complex) or not math.isfinite(result):
        raise FormulaError("The formula does not give an ordinary number here.")
    return float(result)


def names_in(formula: Formula) -> set[str]:
    """The names a formula uses."""
    if formula[0] == "name":
        return {formula[1]}
    found: set[str] = set()
    for part in formula[1:]:
        if isinstance(part, tuple):
            found |= names_in(part)
    return found


def equivalent(given: str, answer: str, names: Iterable[str]) -> bool:
    """True if the formula `given` equals `answer` for any values of `names`.

    Both are worked out at the same random values (the same every time, so a check
    never flips); values where `answer` cannot be worked out are skipped. `given`
    must not fail where `answer` works. Raises FormulaError if `given` cannot be read.
    """
    names = list(names)
    mine = parse(given, names)
    theirs = parse(answer, names)
    rng = random.Random(f"{answer}|{','.join(sorted(names))}")
    good = 0
    for _ in range(_MAX_DRAWS):  # draw until _SAMPLES usable points, or give up
        if good >= _SAMPLES:
            break
        values = {name: rng.uniform(*_SAMPLE_RANGE) for name in names}
        try:
            expected = evaluate(theirs, values)
        except FormulaError:
            continue
        try:
            got = evaluate(mine, values)
        except FormulaError:
            return False
        if abs(got - expected) > _SAME * max(abs(expected), abs(got)) + _TINY:
            return False
        good += 1
    return good >= _MIN_GOOD_SAMPLES


_BLANK = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?::([^{}]*))?\}")


def fill(text: str, values: dict[str, float | str]) -> str:
    """Put values into the {blanks} of `text`. {m} shows a number to 3 significant
    figures (show_number); {m:.1f} uses that Python format instead. Stops with a
    FormulaError for a blank with no value."""

    def one(match: re.Match) -> str:
        name, spec = match.group(1), match.group(2)
        if name not in values:
            raise FormulaError(f"The text uses {{{name}}}, which has no value.")
        value = values[name]
        if isinstance(value, str):
            return value
        if spec:
            try:
                shown = format(value, spec)
            except ValueError:
                raise FormulaError(f"{{{name}:{spec}}} is not a number format.") from None
            if float(shown.rstrip("%") or 0) == 0:
                shown = shown.lstrip("-")  # never "−0.0"
            return shown.replace("-", "−")
        return show_number(value)

    return _BLANK.sub(one, text)


_LOOKS = {
    "theta": "θ",
    "mu": "μ",
    "alpha": "α",
    "beta": "β",
    "omega": "ω",
    "phi": "φ",
    "lambda": "λ",
    "pi": "π",
    "v0": "v₀",
    "x0": "x₀",
}


def pretty(text: str) -> str:
    """A course formula as a student reads it: √( ) for sqrt( ), · for *, ² and ³ for
    powers of 2 and 3, and Greek letters, such as "(3·m·v₀²/(2·β))^(1/3)"."""
    text = re.sub(r"\bsqrt\(", "√(", text)
    # Names first: "²" counts as a letter-like character, so it would hide "v0" in "v0²".
    text = re.sub(r"\b(" + "|".join(_LOOKS) + r")\b", lambda m: _LOOKS[m.group(1)], text)
    text = re.sub(r"\^2(?![\d.])", "²", text)
    text = re.sub(r"\^3(?![\d.])", "³", text)
    return text.replace("*", "·").replace("-", "−")


def blanks_in(text: str) -> set[str]:
    """The names of the {blanks} in a text."""
    return {match.group(1) for match in _BLANK.finditer(text)}


def show_number(x: float) -> str:
    """A number as a physics text writes it, with the minus sign "−": whole numbers
    from 10 up to 10,000,000 as they are (1400), others to 3 significant figures,
    dropping a last 0 while at least 2 remain (2.0, 1.5, 0.50, 3.06, 0.486, 1230)."""
    if x == 0:
        return "0"
    if x == int(x) and 10 <= abs(x) < 1e7:
        return str(int(x)).replace("-", "−")
    if not 1e-3 <= abs(x) < 1e7:
        return f"{x:.3g}".replace("-", "−")  # rare: 1.23e+09
    x = float(f"{x:.3g}")  # 3 significant figures first, so 99.95 becomes 100
    if x == int(x) and abs(x) >= 100:
        return str(int(x)).replace("-", "−")
    digits = max(0, 2 - math.floor(math.log10(abs(x))))
    text = f"{x:.{digits}f}"
    significant = len(text.lstrip("-").replace(".", "").lstrip("0"))
    if digits > 0 and text.endswith("0") and significant > 2:
        text = text[:-1]
    return text.rstrip(".").replace("-", "−")


# ---------- reading ----------

_TOKEN = re.compile(r"\s*(?:(\d+\.?\d*|\.\d+)|([A-Za-z_][A-Za-z0-9_]*)|(\*\*|[-+*/^()]))")


def _tokens(text: str, names: set[str]) -> list[tuple[str, str]]:
    """Cut the text into ("num", "2"), ("name", "g"), ("op", "*") and so on. A run of
    letters is split into the longest known names, so "mgh" with names m, g, h gives
    m, g, h; anything else is refused."""
    for old, new in _SWAPS.items():
        text = text.replace(old, new)
    vocabulary = names | set(FUNCTIONS) | set(CONSTANTS)
    tokens: list[tuple[str, str]] = []
    position = 0
    text = text.rstrip()
    while position < len(text):
        match = _TOKEN.match(text, position)
        if not match:
            raise FormulaError(f"'{text[position:].strip()[:1]}' cannot be used in a formula.")
        number, word, operator = match.groups()
        if number is not None:
            if text[match.end() : match.end() + 1] == ".":
                raise FormulaError(f"'{number}.' is not a number.")
            tokens.append(("num", number))
        elif word is not None:
            for piece in _split_word(word, vocabulary):
                if piece.isdigit():
                    tokens.append(("num", piece))  # "v2" means v times 2
                else:
                    tokens.append(("func" if piece in FUNCTIONS else "name", piece))
        else:
            tokens.append(("op", "^" if operator == "**" else operator))
        position = match.end()
    return tokens


def _split_word(word: str, vocabulary: set[str]) -> list[str]:
    """Split a run like "mgh" or "v0t" into known names, longest first, and digits
    after a name, like "v2", into the name and a number. Worked out once per position
    (so a long run never takes long), preferring the fewest pieces."""
    if word in vocabulary:
        return [word]
    # best[i]: the fewest pieces that spell word[i:], or None if it cannot be spelled.
    best: list[list[str] | None] = [None] * (len(word) + 1)
    best[len(word)] = []
    for start in range(len(word) - 1, -1, -1):
        options = []
        for end in range(len(word), start, -1):
            piece = word[start:end]
            rest = best[end]
            if rest is None:
                continue
            if piece in vocabulary or (piece.isdigit() and start > 0):
                options.append([piece, *rest])
        if options:
            best[start] = min(options, key=len)
    if best[0] is None:
        raise FormulaError(f"'{word}' is not one of the symbols you can use.")
    return best[0]


class _Reader:
    """Reads tokens by the grammar, lowest priority first:
    sum = product (('+' | '-') product)*
    product = signed (('*' | '/') signed | signed written right after)*
    signed = ('+' | '-') signed | power
    power = atom ('^' signed)?
    atom = number | name | function '(' sum ')' | function atom | '(' sum ')'
    """

    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.tokens = tokens
        self.position = 0

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def take(self) -> tuple[str, str]:
        token = self.peek()
        if token is None:
            raise FormulaError("The formula stops too early.")
        self.position += 1
        return token

    def sum(self) -> Formula:
        left = self.product()
        while self.peek() in (("op", "+"), ("op", "-")):
            operator = self.take()[1]
            left = (operator, left, self.product())
        return left

    def product(self) -> Formula:
        left = self.signed()
        while True:
            token = self.peek()
            if token in (("op", "*"), ("op", "/")):
                operator = self.take()[1]
                left = (operator, left, self.signed())
            elif token is not None and (token[0] != "op" or token[1] == "("):
                left = ("*", left, self.power())  # side by side: multiply
            else:
                return left

    def signed(self) -> Formula:
        if self.peek() == ("op", "-"):
            self.take()
            return ("neg", self.signed())
        if self.peek() == ("op", "+"):
            self.take()
            return self.signed()
        return self.power()

    def power(self) -> Formula:
        base = self.atom()
        if self.peek() == ("op", "^"):
            self.take()
            return ("^", base, self.signed())
        return base

    def atom(self) -> Formula:
        kind, text = self.take()
        if kind == "num":
            return ("num", float(text))
        if kind == "name":
            if text in CONSTANTS:
                return ("num", CONSTANTS[text])
            return ("name", text)
        if kind == "func":
            if self.peek() == ("op", "("):
                return ("call", text, self.atom())
            if text in _TRIG and self.peek() is not None and self.peek()[0] in ("name", "num"):
                # "cos θ" is how physics texts write it: the angle right after.
                return ("call", text, self.atom())
            # "√gh" could mean √(gh) or √g·h, so ask instead of guessing.
            raise FormulaError(f"Put brackets after {text}, like {text}(2gh).")
        if text == "(":
            inside = self.sum()
            if self.take() != ("op", ")"):
                raise FormulaError("A bracket is not closed.")
            return inside
        raise FormulaError(f"'{text}' is in the wrong place.")


def _work_out(formula: Formula, values: dict[str, float]) -> float:
    kind = formula[0]
    if kind == "num":
        return formula[1]
    if kind == "name":
        if formula[1] not in values:
            raise FormulaError(f"'{formula[1]}' has no value.")
        return values[formula[1]]
    if kind == "neg":
        return -_work_out(formula[1], values)
    if kind == "call":
        return FUNCTIONS[formula[1]](_work_out(formula[2], values))
    left = _work_out(formula[1], values)
    right = _work_out(formula[2], values)
    if kind == "+":
        return left + right
    if kind == "-":
        return left - right
    if kind == "*":
        return left * right
    if kind == "/":
        return left / right
    if abs(right) > 100:
        raise FormulaError("A power is too large.")
    return left**right
