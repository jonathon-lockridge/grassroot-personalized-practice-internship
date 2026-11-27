"""What a course looks like, and the checks that keep a course file honest.

A course is data, not code: a list of skills and a list of problems, each problem
with a short title and made of steps, each step tagged with one skill. A choice
step also says, for each wrong option, why it is wrong. A course may also list its
units, each a list of lessons, and the skills each lesson teaches, following the
course's own curriculum (for AP courses, the College Board's units and topics).

A problem may be a template (decided 2026-11-27): its numbers change each time it is
given, within ranges, so a skill comes back as a new version, never the exact same
problem. Its texts have {blanks} for those numbers, and its answers are formulas
worked out from them. A step may also ask for a formula ("expression" steps), as AP
questions do ("derive an expression for v in terms of m, g and h").

This file describes those shapes and offers these helpers:

- load_course(path): read a course.json file into the shapes below. A file that is
  not valid JSON, or has a missing, misspelled or wrongly typed field, stops here
  with a plain message saying where.
- validate_course(course): check a course that loaded against the rules every
  course must follow, and return a list of plain-English complaints. An empty
  list means the course is sound. A template is checked in every variant.
- is_template(problem) and fill_problem(problem, variant): whether a problem's
  numbers change, and the problem with its numbers filled in for one variant (a
  whole number that picks the numbers; the same variant always gives the same ones).

How to read this file: `name: str` means the field holds text, `int` a whole
number, `float` a number with a decimal point, `list[str]` a list of texts,
`dict[str, str]` a look-up table from one text to another, and `|` means "or".
`-> list[str]` after a function means it gives back a list of texts. A name that
starts with `_` is a helper used only inside this file. An f"..." text has
blanks: whatever is inside {braces} is filled in.

Nothing here knows about algebra or physics, and nothing here touches the web
server or stored data.
"""

import functools
import json
import math
import random
import re
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from practice_engine.formulas import (
    FormulaError,
    blanks_in,
    equivalent,
    evaluate,
    fill,
    names_in,
    parse,
)

STEP_KINDS = ("choice", "number", "order", "expression")
# A template's variants are numbered 1 to this, and every one is filled in and checked
# when the course is checked, so a student is only ever given a checked variant.
TEMPLATE_VARIANTS = 200
# A number worked out by a template counts as right within this share of it (2%, as
# online homework systems often allow), unless the step gives its own tolerance, so an
# answer to 3 significant figures from rounded in-between values still counts.
TEMPLATE_TOLERANCE = 0.02
DIFFICULTIES = (1, 2, 3)  # 1 easy, 2 medium, 3 hard
# Skill and problem ids: lowercase words or digits joined by underscores, like kinetic_energy.
ID_PATTERN = re.compile(r"[a-z0-9]+(_[a-z0-9]+)*")
# A course id matches its folder name, like ap-physics-c-energy-momentum, so it may use hyphens.
COURSE_ID_PATTERN = re.compile(r"[a-z0-9]+([-_][a-z0-9]+)*")


class CourseShape(BaseModel):
    """Shared setting for the course shapes below.

    `extra="forbid"` refuses a field name we do not know, so a typo in the file,
    such as "prerequisite" instead of "prerequisites", is reported instead of
    being silently thrown away.
    """

    model_config = ConfigDict(extra="forbid")


class Skill(CourseShape):
    """One thing a student can master, such as "undo addition on both sides"."""

    id: str
    name: str
    # A skill may leave prerequisites out of the file; it then counts as an empty list.
    prerequisites: list[str] = []


class Step(CourseShape):
    """One question inside a problem. The student answers the steps in order.

    `kind` says how the student answers:
    - "choice": pick one of `options`; `answer` is the text of the correct option.
    - "number": type a number; `answer` is that number, whole or up to two decimals.
      `tolerance` (number steps only, may be left out) says how far a typed number
      may be from the answer and still count as right, such as 0.05 for 5.48
      (useful when answers are rounded). Left out, the typed number must match.
    - "order": put items in order; `answer` is the list in the correct order, and
      the student sees it shuffled.
    - "expression": type a formula; `answer` is the right formula, such as
      "sqrt(2*g*h)", and `symbols` lists the names the student may use. Any formula
      equal to it for every value of the symbols is right (see formulas.py).

    In a template problem, a number step's `answer` may be a formula of the
    problem's numbers, such as "0.5*m*v^2", and texts may have {blanks}.

    `feedback` (choice steps only) is a look-up table: wrong option -> a one-line
    message saying why that option is wrong, shown right after the student picks
    it. Every wrong option needs one; the correct answer gets none.
    """

    prompt: str  # the question text
    kind: str
    # Only choice steps have options; for the other kinds this stays None (nothing).
    options: list[str] | None = None
    # Text for a choice step, a number for a number step, a list of texts for an order
    # step. `bool` is listed only so that a mistaken true/false in the file is kept as
    # written and reported, instead of being read as 1/0. _check_step makes sure the
    # answer matches the kind.
    answer: str | bool | int | float | list[str]
    hint: str
    skill: str
    # Only number steps may have a tolerance; see the kinds above.
    tolerance: float | None = None
    # Only choice steps have feedback; for the other kinds this stays None (nothing).
    # Saying why an answer is wrong teaches more than "right/wrong" alone
    # (research report, change 4).
    feedback: dict[str, str] | None = None
    # Only expression steps have symbols: the names the student may use, like "m".
    symbols: list[str] | None = None


class NumberRange(CourseShape):
    """The values a template number may take: `start`, `start` + `step`, ... up to
    `stop`. All three are written as numbers."""

    start: float
    stop: float
    step: float


class Graph(CourseShape):
    """A line graph the page draws above the steps, such as force against position.
    Each point is [x, y]; in a template, either may be a formula of its numbers."""

    x_label: str
    y_label: str
    points: list[list[float | str]]


class Problem(CourseShape):
    """A scenario, such as an equation, and the ordered steps that solve it."""

    id: str
    title: str  # a short name the student sees, like "Bullet into a hanging block"
    prompt: str
    difficulty: int
    steps: list[Step]
    # A template's changing numbers, such as {"m": {"start": 1, "stop": 3, "step": 0.5}}.
    numbers: dict[str, NumberRange] = {}
    # A template's changing words: one setting is picked per variant, such as
    # [{"thing": "crate"}, {"thing": "sled"}], so the details change too.
    settings: list[dict[str, str]] = []
    # Values worked out from the numbers, in order, such as {"K": "0.5*m*v^2"}.
    values: dict[str, str] = {}
    graph: Graph | None = None


class Lesson(CourseShape):
    """One lesson of a unit, such as "3.2 Work", and the skills it teaches.

    `notes` are a few short lines the page shows as the lesson (a stand-in for the
    real lesson material, which is not this project's job). A skill used everywhere,
    such as "which idea fits?", may belong to no lesson.
    """

    id: str
    title: str
    skills: list[str]
    notes: list[str] = []


class Unit(CourseShape):
    """One unit of the course, such as "Unit 3 · Work, Energy, and Power"."""

    title: str
    lessons: list[Lesson]


class Course(CourseShape):
    """A whole course: its skills, which skill depends on which, and its problems.

    `units` may be left out; a course without units is practiced as one whole.
    """

    id: str
    title: str
    skills: list[Skill]
    problems: list[Problem]
    units: list[Unit] = []


def load_course(path: str | Path) -> Course:
    """Read a course.json file into a Course.

    Stops with a plain message (a ValueError) if the file is not valid JSON, or if a
    field is missing, misspelled or holds the wrong sort of value. Positions in the
    message count from 1, the way a person counts. A course that loads is then
    checked by validate_course.
    """
    path = Path(path)
    # "utf-8-sig" also accepts files that some editors start with an invisible marker.
    text = path.read_text(encoding="utf-8-sig")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{path.name} is not valid JSON: {error.msg} at line {error.lineno}, "
            f"column {error.colno}."
        ) from None
    try:
        # pydantic turns the loaded data into a Course, checking each field's sort of value.
        return Course.model_validate(data)
    except ValidationError as error:
        faults = "\n".join(_describe_faults(error))
        raise ValueError(f"{path.name} does not match the course format:\n{faults}") from None


# Names pydantic adds to a location when it tried several sorts of value for one field.
_TYPE_NAMES = {"str", "bool", "int", "float", "list[str]"}


def _describe_faults(error: ValidationError) -> list[str]:
    """Turn pydantic's technical error list into one plain line per fault."""
    lines: dict[str, str] = {}  # location -> message; a dict keeps each location once
    for fault in error.errors():
        location = _describe_location(fault["loc"])
        if fault["type"] == "missing":
            message = "is missing"
        elif fault["type"] == "extra_forbidden":
            message = "is not a field name we know; check the spelling"
        elif location in lines:
            message = "holds the wrong sort of value"  # several complaints about one spot
        else:
            message = fault["msg"]
        lines[location] = message
    return [f"{location}: {message}." for location, message in lines.items()]


def _describe_location(loc: tuple) -> str:
    """('problems', 1, 'steps', 2, 'hint') becomes "problem 2, step 3, 'hint'"."""
    parts: list[str] = []
    names = list(loc)
    while names:
        name = names.pop(0)
        if isinstance(name, str) and name in _TYPE_NAMES:
            break  # what follows only says which sort of value pydantic tried
        if names and isinstance(names[0], int):
            index = names.pop(0)
            parts.append(f"{str(name).rstrip('s')} {index + 1}")  # count from 1, not 0
        else:
            parts.append(f"'{name}'")
    return ", ".join(parts) or "the whole file"


def is_template(problem: Problem) -> bool:
    """True if the problem's numbers or words change from one variant to the next."""
    return bool(problem.numbers or problem.settings)


def variant_values(problem: Problem, variant: int) -> dict[str, float | str]:
    """The numbers, words and worked-out values of one variant of a template. Stops
    with a FormulaError if a value cannot be worked out."""
    rng = random.Random(f"{problem.id}:{variant}")
    values: dict[str, float | str] = {}
    for name, span in problem.numbers.items():
        count = int(round((span.stop - span.start) / span.step)) if span.step > 0 else 0
        values[name] = round(span.start + rng.randint(0, max(count, 0)) * span.step, 10)
    if problem.settings:
        values.update(rng.choice(problem.settings))
    for name, text in problem.values.items():
        numeric = {k: v for k, v in values.items() if not isinstance(v, str)}
        values[name] = evaluate(parse(text, numeric), numeric)
    return values


def fill_problem(problem: Problem, variant: int | None) -> Problem:
    """The problem with one variant's numbers and words filled in. A problem that is
    not a template comes back as it is. Stops with a FormulaError if the template
    cannot be filled in (the course checker reports that before any student sees it).
    """
    if not is_template(problem):
        return problem
    values = variant_values(problem, variant or 0)
    numeric = {k: v for k, v in values.items() if not isinstance(v, str)}

    def text(value: str) -> str:
        return fill(value, values)

    steps = []
    for step in problem.steps:
        filled = step.model_copy(deep=True)
        filled.prompt, filled.hint = text(step.prompt), text(step.hint)
        if step.kind == "choice":
            filled.options = [text(option) for option in step.options or []]
            filled.answer = text(step.answer) if isinstance(step.answer, str) else step.answer
            if step.feedback is not None:
                filled.feedback = {text(k): text(v) for k, v in step.feedback.items()}
        elif step.kind == "order" and isinstance(step.answer, list):
            filled.answer = [text(item) for item in step.answer]
        elif step.kind == "number":
            if isinstance(step.answer, str):
                filled.answer = evaluate(parse(step.answer, numeric), numeric)
            if step.tolerance is None and not isinstance(filled.answer, bool):
                filled.tolerance = max(abs(filled.answer) * TEMPLATE_TOLERANCE, 1e-9)
        steps.append(filled)
    graph = None
    if problem.graph is not None:
        points = [
            [
                evaluate(parse(item, numeric), numeric) if isinstance(item, str) else item
                for item in point
            ]
            for point in problem.graph.points
        ]
        graph = Graph(
            x_label=text(problem.graph.x_label), y_label=text(problem.graph.y_label), points=points
        )
    return Problem(
        id=problem.id,
        title=text(problem.title),
        prompt=text(problem.prompt),
        difficulty=problem.difficulty,
        steps=steps,
        graph=graph,
    )


def validate_course(course: Course) -> list[str]:
    """Check a course against the rules every course must follow.

    Returns one plain-English complaint per fault, saying where it is. An empty
    list means the course is sound.
    """
    complaints = []
    if not course.skills:
        complaints.append("The course has no skills.")
    if not course.problems:
        complaints.append("The course has no problems.")
    complaints += _check_ids(course)  # += adds that helper's complaints onto the list
    complaints += _check_names(course)
    complaints += _check_skill_references(course)
    complaints += _check_prerequisites_have_no_loop(course)
    complaints += _check_every_skill_is_used(course)
    complaints += _check_problems_and_steps(course)
    complaints += _check_units(course)
    return complaints


def _check_units(course: Course) -> list[str]:
    """Units and lessons need titles and at least one lesson or skill; lesson ids are
    well formed and used once; every lesson skill is in the course, and a skill
    belongs to at most one lesson."""
    skill_ids = {skill.id for skill in course.skills}
    # Skills with a step in every problem (with 2 or more problems) are practiced
    # everywhere, so a lesson of only those has nothing of its own to practice.
    everywhere: set[str] = set()
    if len(course.problems) >= 2:
        everywhere = set.intersection(
            *({step.skill for step in problem.steps} for problem in course.problems)
        )
    complaints = []
    seen_lessons: set[str] = set()
    lesson_of: dict[str, str] = {}  # skill id -> the lesson that teaches it
    for number, unit in enumerate(course.units, start=1):
        if not unit.title.strip():
            complaints.append(f"Unit {number} has an empty title.")
        if not unit.lessons:
            complaints.append(f"Unit {number} has no lessons.")
        for lesson in unit.lessons:
            where = f"Lesson '{lesson.id}'"
            if not ID_PATTERN.fullmatch(lesson.id):
                complaints.append(
                    f"Lesson id '{lesson.id}' must be lowercase words or digits joined by "
                    "underscores, like '3_2_work'."
                )
            if lesson.id in seen_lessons:
                complaints.append(f"Lesson id '{lesson.id}' is used more than once.")
            seen_lessons.add(lesson.id)
            if not lesson.title.strip():
                complaints.append(f"{where} has an empty title.")
            if not lesson.skills:
                complaints.append(f"{where} teaches no skills.")
            elif set(lesson.skills) <= everywhere:
                complaints.append(
                    f"{where} only teaches skills used in every problem, so it has nothing "
                    "of its own to practice."
                )
            if any(not note.strip() for note in lesson.notes):
                complaints.append(f"{where} has an empty note.")
            for skill_id in lesson.skills:
                if skill_id not in skill_ids:
                    complaints.append(
                        f"{where} lists a skill '{skill_id}' that is not in the course."
                    )
                elif skill_id in lesson_of:
                    complaints.append(
                        f"Skill '{skill_id}' is in two lessons: '{lesson_of[skill_id]}' "
                        f"and '{lesson.id}'."
                    )
                else:
                    lesson_of[skill_id] = lesson.id
    return complaints


def _check_ids(course: Course) -> list[str]:
    """Ids must be well formed, and no two skills or two problems may share one."""
    complaints = []
    if not COURSE_ID_PATTERN.fullmatch(course.id):
        complaints.append(
            f"Course id '{course.id}' must be lowercase words joined by hyphens, "
            "like 'ap-physics-c-energy-momentum'."
        )
    seen: set[str] = set()  # a set remembers each value once: the ids met so far
    for skill in course.skills:
        if not ID_PATTERN.fullmatch(skill.id):
            complaints.append(
                f"Skill id '{skill.id}' must be lowercase words joined by underscores, "
                "like 'kinetic_energy'."
            )
        if skill.id in seen:
            complaints.append(f"Skill id '{skill.id}' is used more than once.")
        seen.add(skill.id)
    seen = set()  # start again: problem ids are a separate list from skill ids
    for problem in course.problems:
        if not ID_PATTERN.fullmatch(problem.id):
            complaints.append(
                f"Problem id '{problem.id}' must be lowercase words joined by underscores, "
                "like 'push_cart'."
            )
        if problem.id in seen:
            complaints.append(f"Problem id '{problem.id}' is used more than once.")
        seen.add(problem.id)
    return complaints


def _check_names(course: Course) -> list[str]:
    """The course title, every skill name and every problem title are shown to
    students, so they must exist, and no two skills or two problems may share one."""
    complaints = []
    # .strip() removes spaces at both ends, so a name made only of spaces counts as empty.
    if not course.title.strip():
        complaints.append("The course title is empty.")
    seen: set[str] = set()
    for skill in course.skills:
        if not skill.name.strip():
            complaints.append(f"Skill '{skill.id}' has an empty name.")
        if skill.name in seen:
            complaints.append(f"Two skills share the name '{skill.name}'.")
        seen.add(skill.name)
    seen = set()  # start again: problem titles are a separate list from skill names
    for problem in course.problems:
        if not problem.title.strip():
            complaints.append(f"Problem '{problem.id}' has an empty title.")
        if problem.title in seen:
            complaints.append(f"Two problems share the title '{problem.title}'.")
        seen.add(problem.title)
    return complaints


def _check_skill_references(course: Course) -> list[str]:
    """Every prerequisite and every step must point at a skill that exists."""
    skill_ids = {skill.id for skill in course.skills}
    complaints = []
    for skill in course.skills:
        for prerequisite in skill.prerequisites:
            if prerequisite not in skill_ids:
                complaints.append(
                    f"Skill '{skill.id}' lists a prerequisite '{prerequisite}' "
                    "that is not in the course."
                )
        # A set drops repeats, so if it is shorter than the list, a prerequisite repeats.
        if len(set(skill.prerequisites)) != len(skill.prerequisites):
            complaints.append(f"Skill '{skill.id}' lists the same prerequisite twice.")
    for problem in course.problems:
        # Number the steps 1, 2, 3 the way a person counts, so a complaint says "step 1".
        for position, step in enumerate(problem.steps, start=1):
            if step.skill not in skill_ids:
                complaints.append(
                    f"Problem '{problem.id}', step {position}: "
                    f"skill '{step.skill}' is not in the course."
                )
    return complaints


def _check_prerequisites_have_no_loop(course: Course) -> list[str]:
    """A loop would mean a skill needs itself, directly or through other skills.

    Start from each skill, follow its prerequisites, then their prerequisites, and
    so on, remembering the chain walked so far. Meeting a skill that is already in
    the chain means the chain has closed on itself: a loop.
    """
    # Look-up table: skill id -> that skill's list of prerequisite ids.
    prerequisites_of = {skill.id: skill.prerequisites for skill in course.skills}
    complaints = []
    # Skills whose chain has already been walked to the end. Walking them again would
    # waste time and would report the same loop once per skill in it.
    finished: set[str] = set()

    def walk(skill_id: str, path: list[str]) -> None:
        # A small helper kept inside this function so it can add to `complaints` and
        # `finished`. It calls itself once per prerequisite, which is how it follows a
        # chain as deep as it goes. `path` is the chain of skills followed to get here.
        if skill_id in path:
            # Cut the chain at the first visit to this skill and put the skill at the
            # end again, so the message reads a -> b -> a.
            loop = path[path.index(skill_id) :] + [skill_id]
            complaints.append("Prerequisites form a loop: " + " -> ".join(loop) + ".")
            return
        # A prerequisite that is not a real skill is reported by _check_skill_references,
        # so there is nothing to follow here.
        if skill_id in finished or skill_id not in prerequisites_of:
            return
        for prerequisite in prerequisites_of[skill_id]:
            walk(prerequisite, path + [skill_id])  # the same chain, one skill longer
        finished.add(skill_id)

    for skill_id in prerequisites_of:
        walk(skill_id, [])
    return complaints


def _check_every_skill_is_used(course: Course) -> list[str]:
    """A skill no step points at can never be practiced, so it is a mistake."""
    # Every skill id that some step points at: for each problem, for each of its steps,
    # take step.skill. A set keeps each id once.
    used = {step.skill for problem in course.problems for step in problem.steps}
    # One complaint per skill whose id is not in that set.
    return [
        f"Skill '{skill.id}' is not used by any step, so it can never be practiced."
        for skill in course.skills
        if skill.id not in used
    ]


def _check_problems_and_steps(course: Course) -> list[str]:
    complaints = []
    for problem in course.problems:
        if is_template(problem) or problem.values:
            complaints += _check_template(problem)
            continue
        complaints += _check_one_problem(problem)
    return complaints


def _check_template(problem: Problem) -> list[str]:
    """Check a template: its ranges, then many filled-in variants, each by the same
    rules as an ordinary problem. Each complaint is given once."""
    where = f"Problem '{problem.id}'"
    complaints = []
    for name, span in problem.numbers.items():
        if not (span.step > 0 and span.stop >= span.start):
            complaints.append(
                f"{where}: number '{name}' needs a step above 0 and a stop at or above its start."
            )
    if not problem.numbers and not problem.settings:
        complaints.append(f"{where}: it has worked-out values but no numbers or settings.")
    if complaints:
        return complaints
    seen: dict[str, None] = {}  # complaints in order, each once
    for variant in range(1, TEMPLATE_VARIANTS + 1):
        try:
            filled = fill_problem(problem, variant)
        except FormulaError as error:
            seen[f"{where}, variant {variant}: {error}"] = None
            break
        for complaint in _check_one_problem(filled, template=True):
            seen.setdefault(complaint, None)
    return list(seen)


def _check_one_problem(problem: Problem, template: bool = False) -> list[str]:
    """Check one problem that is not a template, or one filled-in variant of one."""
    complaints = []
    where = f"Problem '{problem.id}'"  # the start of every complaint about this problem
    if not problem.prompt.strip():
        complaints.append(f"{where}: the prompt is empty.")
    if problem.difficulty not in DIFFICULTIES:
        complaints.append(f"{where}: difficulty must be 1, 2 or 3, not {problem.difficulty}.")
    if not problem.steps:
        complaints.append(f"{where}: it has no steps.")
    # Number the steps 1, 2, 3 the way a person counts, so a complaint says "step 1".
    for position, step in enumerate(problem.steps, start=1):
        complaints += _check_step(step, f"{where}, step {position}", template)
    if problem.graph is not None:
        complaints += _check_graph(problem, where)
    texts = [problem.title, problem.prompt] + [s.prompt for s in problem.steps]
    if any(blanks_in(text) for text in texts):
        complaints.append(
            f"{where}: a text has a {{blank}} but the problem has no numbers to fill it."
        )
    return complaints


def _check_graph(problem: Problem, where: str) -> list[str]:
    graph = problem.graph
    complaints = []
    if not graph.x_label.strip() or not graph.y_label.strip():
        complaints.append(f"{where}: the graph needs a label on each axis.")
    if len(graph.points) < 2 or any(len(point) != 2 for point in graph.points):
        complaints.append(f"{where}: the graph needs at least 2 points, each [x, y].")
    elif not all(
        isinstance(value, int | float) and math.isfinite(value)
        for point in graph.points
        for value in point
    ):
        complaints.append(f"{where}: every graph point must be an ordinary number.")
    return complaints


def _check_step(step: Step, where: str, template: bool = False) -> list[str]:
    """Check one step. `where` starts every complaint, like "Problem 'push_cart', step 3"."""
    complaints = []
    if not step.prompt.strip():
        complaints.append(f"{where}: the prompt (the question text) is empty.")
    if not step.hint.strip():
        complaints.append(f"{where}: the hint is empty.")
    if step.kind not in STEP_KINDS:
        kinds = ", ".join(STEP_KINDS)  # one text: "choice, number, order"
        complaints.append(f"{where}: kind must be one of {kinds}, not '{step.kind}'.")
        return complaints  # the rules below depend on knowing the kind
    if step.kind != "choice" and step.options is not None:
        complaints.append(
            f"{where}: only 'choice' steps may have options; remove the options line "
            "or change the kind to 'choice'."
        )
    if step.kind != "number" and step.tolerance is not None:
        complaints.append(f"{where}: only 'number' steps may have a tolerance.")
    if step.kind != "choice" and step.feedback is not None:
        complaints.append(f"{where}: only 'choice' steps may have feedback.")
    if step.kind != "expression" and step.symbols is not None:
        complaints.append(f"{where}: only 'expression' steps may have symbols.")
    if step.kind == "choice":
        complaints += _check_choice(step, where)
    elif step.kind == "number":
        complaints += _check_number(step, where, template)
    elif step.kind == "expression":
        complaints += _check_expression(step, where)
    else:  # kind is "order", the only kind left
        complaints += _check_order(step, where)
    return complaints


@functools.cache
def _answer_can_be_checked(answer: str, symbols: tuple[str, ...]) -> bool:
    """The formula can be worked out at enough values to compare typed answers with it.
    Kept once per formula: a template's every variant asks the same."""
    return equivalent(answer, answer, symbols)


def _check_expression(step: Step, where: str) -> list[str]:
    """An expression step lists its symbols, and its answer is a formula of them."""
    symbols = step.symbols or []
    if not symbols or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", s) for s in symbols):
        return [f"{where}: an expression step needs symbols, each a name like 'm' or 'v0'."]
    if not isinstance(step.answer, str):
        return [f"{where}: an expression step's answer must be a formula written as text."]
    try:
        formula = parse(step.answer, symbols)
    except FormulaError as error:
        return [f"{where}: the answer formula cannot be read: {error}"]
    unused = set(symbols) - names_in(formula)
    if unused:
        return [f"{where}: the symbols {sorted(unused)} are listed but not in the answer."]
    if not _answer_can_be_checked(step.answer, tuple(symbols)):
        return [
            f"{where}: the answer formula cannot be worked out for most values of its "
            "symbols, so no typed answer could be checked."
        ]
    return []


def _repeats(texts: list[str]) -> bool:
    """True if two texts are the same once capitals and spaces at the ends are ignored."""
    trimmed = [text.strip().casefold() for text in texts]
    # A set drops repeats, so if it is shorter than the list, something repeats.
    return len(set(trimmed)) != len(trimmed)


def _check_choice(step: Step, where: str) -> list[str]:
    complaints = []
    # A choice step may have no options line at all (options is then None); treat that
    # as an empty list so the counts below still work.
    options = step.options or []
    if len(options) < 2:
        complaints.append(f"{where}: a choice step needs at least 2 options.")
    if any(not option.strip() for option in options):
        complaints.append(f"{where}: an option is empty.")
    if _repeats(options):
        complaints.append(f"{where}: the same option appears more than once.")
    if not isinstance(step.answer, str):
        complaints.append(
            f"{where}: a choice step's answer must be the text of one option, "
            "not its position number."
        )
    elif step.answer not in options:
        complaints.append(
            f"{where}: the answer '{step.answer}' is not one of the options "
            "(it must match one option exactly, including capital letters and spaces)."
        )
    complaints += _check_feedback(step, options, where)
    return complaints


def _check_feedback(step: Step, options: list[str], where: str) -> list[str]:
    """Every wrong option needs a message saying why it is wrong; the answer needs none."""
    complaints = []
    # No feedback line at all counts as an empty table, so every wrong option is reported.
    feedback = step.feedback or {}
    for option in feedback:  # going through a look-up table gives its keys: the option texts
        if option not in options:
            complaints.append(
                f"{where}: feedback is given for '{option}', which is not one of the options "
                "(it must match one option exactly, including capital letters and spaces)."
            )
        elif option == step.answer:
            complaints.append(
                f"{where}: feedback is given for the correct answer '{option}'; "
                "feedback is only for wrong options."
            )
    for option in options:
        if option != step.answer and not feedback.get(option, "").strip():
            complaints.append(
                f"{where}: the wrong option '{option}' needs a feedback message "
                "saying why it is wrong."
            )
    return complaints


def _check_number(step: Step, where: str, template: bool = False) -> list[str]:
    answer = step.answer
    # int is a whole number, float a number with a decimal point. A true/false or a
    # number written in quotes is neither.
    if isinstance(answer, bool) or not isinstance(answer, int | float):
        return [
            f"{where}: a number step's answer must be a number written without quotes, "
            'like 5 or 2.5 (not "5").'
        ]
    if not math.isfinite(answer):
        return [f"{where}: the answer must be an ordinary number."]
    # Rounding to two decimals changes the number only if it had more than two. A
    # template works its answers out, so they may have more (they are checked within
    # TEMPLATE_TOLERANCE instead).
    if not template and round(answer, 2) != answer:
        return [f"{where}: the answer {answer} has more than two decimals."]
    tolerance = step.tolerance
    if tolerance is not None and not (math.isfinite(tolerance) and tolerance > 0):
        return [f"{where}: the tolerance must be a number above 0, not {tolerance}."]
    return []


def _check_order(step: Step, where: str) -> list[str]:
    answer = step.answer
    if not isinstance(answer, list):
        return [f"{where}: an order step's answer must be a list of items in the correct order."]
    complaints = []
    if len(answer) < 2:
        complaints.append(f"{where}: an order step needs at least 2 items.")
    if _repeats(answer):
        complaints.append(f"{where}: the same item appears more than once in the order.")
    if any(not item.strip() for item in answer):
        complaints.append(f"{where}: an item in the order is empty.")
    return complaints


# What the engine knows about one student (step T2). These are not part of a course
# file; they describe a student's answers and how well the engine thinks they know
# each skill. Like the course shapes, they hold only nicknames, never personal data.


class MasteryState(CourseShape):
    """How well the engine thinks one student knows each skill of a course.

    `mastery` is a look-up table: skill id -> a number from 0 to 1, where 0 means
    "surely does not know it" and 1 means "surely knows it".
    """

    nickname: str
    course_id: str  # which course these skills belong to, so a state is never used on another
    mastery: dict[str, float]


class StepAnswer(CourseShape):
    """One step a student answered, as the page reports it."""

    nickname: str
    problem_id: str
    step_position: int  # which step of the problem, counting from 1 like the rest of this file
    correct: bool  # True if right, False if wrong
    seconds: float  # how long the student took on this step
    hints_used: int = Field(ge=0)  # how many hints they opened; never below 0
    answered_at: datetime  # the date and time of the answer
    # Which try at this step this was: 1 is the first try, 2 the second, and so on
    # (never below 1). Only the first try changes mastery (see mastery.py).
    attempt: int = Field(default=1, ge=1)
    # Which version of a template problem was answered (see fill_problem); None for
    # a problem whose numbers never change.
    variant: int | None = None
