"""What a course looks like, and the checks that keep a course file honest.

A course is data, not code: a list of skills and a list of problems, each problem
made of steps, each step tagged with one skill. This file describes those shapes
and offers two helpers:

- load_course(path): read a course.json file into the shapes below. A file that is
  not valid JSON, or has a missing, misspelled or wrongly typed field, stops here
  with a plain message saying where.
- validate_course(course): check a course that loaded against the rules every
  course must follow, and return a list of plain-English complaints. An empty
  list means the course is sound.

How to read this file: `name: str` means the field holds text, `int` a whole
number, `float` a number with a decimal point, `list[str]` a list of texts, and
`|` means "or". `-> list[str]` after a function means it gives back a list of
texts. A name that starts with `_` is a helper used only inside this file. An
f"..." text has blanks: whatever is inside {braces} is filled in.

Nothing here knows about algebra or physics, and nothing here touches the web
server or stored data.
"""

import json
import math
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

STEP_KINDS = ("choice", "number", "order")
DIFFICULTIES = (1, 2, 3)  # 1 easy, 2 medium, 3 hard
# Skill and problem ids: lowercase words or digits joined by underscores, like undo_addition.
ID_PATTERN = re.compile(r"[a-z0-9]+(_[a-z0-9]+)*")
# A course id matches its folder name, like linear-equations, so hyphens are allowed too.
COURSE_ID_PATTERN = re.compile(r"[a-z0-9]+([-_][a-z0-9]+)*")


class CourseShape(BaseModel):
    """Shared setting for the four shapes below.

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
    - "order": put items in order; `answer` is the list in the correct order, and
      the student sees it shuffled.
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


class Problem(CourseShape):
    """A scenario, such as an equation, and the ordered steps that solve it."""

    id: str
    prompt: str
    difficulty: int
    steps: list[Step]


class Course(CourseShape):
    """A whole course: its skills, which skill depends on which, and its problems."""

    id: str
    title: str
    skills: list[Skill]
    problems: list[Problem]


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
    return complaints


def _check_ids(course: Course) -> list[str]:
    """Ids must be well formed, and no two skills or two problems may share one."""
    complaints = []
    if not COURSE_ID_PATTERN.fullmatch(course.id):
        complaints.append(
            f"Course id '{course.id}' must be lowercase words joined by hyphens, "
            "like 'linear-equations'."
        )
    seen: set[str] = set()  # a set remembers each value once: the ids met so far
    for skill in course.skills:
        if not ID_PATTERN.fullmatch(skill.id):
            complaints.append(
                f"Skill id '{skill.id}' must be lowercase words joined by underscores, "
                "like 'undo_addition'."
            )
        if skill.id in seen:
            complaints.append(f"Skill id '{skill.id}' is used more than once.")
        seen.add(skill.id)
    seen = set()  # start again: problem ids are a separate list from skill ids
    for problem in course.problems:
        if not ID_PATTERN.fullmatch(problem.id):
            complaints.append(
                f"Problem id '{problem.id}' must be lowercase words joined by underscores, "
                "like 'one_step_add'."
            )
        if problem.id in seen:
            complaints.append(f"Problem id '{problem.id}' is used more than once.")
        seen.add(problem.id)
    return complaints


def _check_names(course: Course) -> list[str]:
    """The course title and every skill name are shown to students, so they must exist."""
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
        where = f"Problem '{problem.id}'"  # the start of every complaint about this problem
        if not problem.prompt.strip():
            complaints.append(f"{where}: the prompt is empty.")
        if problem.difficulty not in DIFFICULTIES:
            complaints.append(f"{where}: difficulty must be 1, 2 or 3, not {problem.difficulty}.")
        if not problem.steps:
            complaints.append(f"{where}: it has no steps.")
        # Number the steps 1, 2, 3 the way a person counts, so a complaint says "step 1".
        for position, step in enumerate(problem.steps, start=1):
            complaints += _check_step(step, f"{where}, step {position}")
    return complaints


def _check_step(step: Step, where: str) -> list[str]:
    """Check one step. `where` starts every complaint, like "Problem 'two_step', step 3"."""
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
    if step.kind == "choice":
        complaints += _check_choice(step, where)
    elif step.kind == "number":
        complaints += _check_number(step, where)
    else:  # kind is "order", the only kind left
        complaints += _check_order(step, where)
    return complaints


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
    return complaints


def _check_number(step: Step, where: str) -> list[str]:
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
    # Rounding to two decimals changes the number only if it had more than two.
    if round(answer, 2) != answer:
        return [f"{where}: the answer {answer} has more than two decimals."]
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
