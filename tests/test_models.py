"""Checks for the course shapes, the loader and the course checker (step T1a)."""

import json
from pathlib import Path

import pytest

from practice_engine.models import Course, load_course, validate_course

# The tiny course file, found from this test file's own location: parents[1] is two
# folders up (out of tests/ to the project root), then data/linear-equations/course.json.
TINY_COURSE = Path(__file__).resolve().parents[1] / "data" / "linear-equations" / "course.json"


def test_tiny_course_loads_and_is_sound() -> None:
    course = load_course(TINY_COURSE)

    assert course.id == "linear-equations"
    assert len(course.skills) >= 2  # the course only grows from here (T1b)
    assert len(course.problems) >= 2
    # The tiny course must use all three answer kinds (TODO T1a asks for that).
    kinds_used = {step.kind for problem in course.problems for step in problem.steps}
    assert kinds_used == {"choice", "number", "order"}
    assert validate_course(course) == []


# The three broken copies that TODO T1a names.


def test_step_naming_a_missing_skill_is_reported() -> None:
    course = load_course(TINY_COURSE)
    course.problems[0].steps[0].skill = "does_not_exist"

    complaints = validate_course(course)

    # At least one complaint should mention the made-up skill id.
    assert any("does_not_exist" in complaint for complaint in complaints)


def test_prerequisite_loop_is_reported() -> None:
    course = load_course(TINY_COURSE)
    first, second = course.skills[0], course.skills[1]
    first.prerequisites = [second.id]
    second.prerequisites = [first.id]

    complaints = validate_course(course)

    # At least one complaint should mention the loop.
    assert any("loop" in complaint for complaint in complaints)


def test_choice_answer_must_be_one_of_the_options() -> None:
    course = load_course(TINY_COURSE)
    # The first step anywhere in the course whose kind is "choice".
    choice_step = next(
        step for problem in course.problems for step in problem.steps if step.kind == "choice"
    )
    choice_step.answer = "Something not offered"

    complaints = validate_course(course)

    # At least one complaint should say the answer is not among the options.
    assert any("not one of the options" in complaint for complaint in complaints)


# One row per remaining rule: how to break the tiny course, and words the complaint must
# contain. Each row becomes its own test.
OTHER_BREAKAGES = [
    ("empty course", lambda c: (c.skills.clear(), c.problems.clear()), "no skills"),
    ("bad skill id", lambda c: setattr(c.skills[0], "id", "Undo Addition"), "lowercase"),
    ("empty problem id", lambda c: setattr(c.problems[0], "id", ""), "lowercase"),
    ("empty skill name", lambda c: setattr(c.skills[0], "name", "   "), "empty name"),
    ("missing prerequisite", lambda c: setattr(c.skills[1], "prerequisites", ["nope"]), "nope"),
    (
        "unused skill",
        lambda c: c.skills.append(c.skills[0].model_copy(update={"id": "spare", "name": "Spare"})),
        "never be practiced",
    ),
    (
        "difficulty 4",
        lambda c: setattr(c.problems[0], "difficulty", 4),
        "difficulty must be 1, 2 or 3",
    ),
    ("no steps", lambda c: c.problems[0].steps.clear(), "no steps"),
    ("blank prompt", lambda c: setattr(c.problems[0].steps[0], "prompt", "  "), "prompt"),
    ("blank hint", lambda c: setattr(c.problems[0].steps[0], "hint", ""), "hint is empty"),
    (
        "unknown kind",
        lambda c: setattr(c.problems[0].steps[0], "kind", "essay"),
        "kind must be one of",
    ),
    (
        "options on a number step",
        lambda c: setattr(c.problems[0].steps[1], "options", ["a", "b"]),
        "only 'choice' steps",
    ),
    (
        "one option",
        lambda c: setattr(c.problems[0].steps[0], "options", ["Subtract 7"]),
        "at least 2 options",
    ),
    (
        "repeated option",
        lambda c: setattr(c.problems[0].steps[0], "options", ["Subtract 7", "subtract 7 "]),
        "more than once",
    ),
    ("quoted number", lambda c: setattr(c.problems[0].steps[1], "answer", "5"), "without quotes"),
    (
        "true as a number",
        lambda c: setattr(c.problems[0].steps[1], "answer", True),
        "without quotes",
    ),
    (
        "too many decimals",
        lambda c: setattr(c.problems[0].steps[1], "answer", 3.14159),
        "more than two decimals",
    ),
    (
        "one item to order",
        lambda c: setattr(c.problems[1].steps[0], "answer", ["only one"]),
        "at least 2 items",
    ),
    (
        "repeated item to order",
        lambda c: setattr(c.problems[1].steps[0], "answer", ["Same", "same"]),
        "more than once",
    ),
]


@pytest.mark.parametrize(
    ("name", "break_course", "expected_words"),
    OTHER_BREAKAGES,
    ids=[row[0] for row in OTHER_BREAKAGES],
)
def test_other_rules_are_enforced(name: str, break_course, expected_words: str) -> None:
    course = load_course(TINY_COURSE)
    break_course(course)

    complaints = validate_course(course)

    assert any(expected_words in complaint for complaint in complaints), (name, complaints)


# The loader's own messages, for files a person could easily write by hand.


def _write_variant(tmp_path: Path, change) -> Path:
    """Copy the tiny course as plain data, let `change` alter it, and save it to a file."""
    data = json.loads(TINY_COURSE.read_text())
    change(data)
    path = tmp_path / "course.json"
    path.write_text(json.dumps(data))
    return path


def test_missing_field_is_reported_counting_from_one(tmp_path: Path) -> None:
    path = _write_variant(tmp_path, lambda d: d["problems"][1]["steps"][2].pop("hint"))

    with pytest.raises(ValueError) as error:
        load_course(path)

    assert "problem 2, step 3, 'hint': is missing" in str(error.value)


def test_misspelled_field_name_is_reported(tmp_path: Path) -> None:
    path = _write_variant(
        tmp_path, lambda d: d["skills"][1].update(prerequisite=d["skills"][1].pop("prerequisites"))
    )

    with pytest.raises(ValueError) as error:
        load_course(path)

    assert "skill 2, 'prerequisite': is not a field name we know" in str(error.value)


def test_broken_json_is_reported_with_a_line_number(tmp_path: Path) -> None:
    path = tmp_path / "course.json"
    path.write_text('{\n  "id": "linear-equations",,\n}')

    with pytest.raises(ValueError) as error:
        load_course(path)

    assert "not valid JSON" in str(error.value)
    assert "line 2" in str(error.value)


def test_a_course_can_also_be_built_in_code() -> None:
    # The shapes work without a file too, which later steps will rely on.
    course = Course(id="demo", title="Demo", skills=[], problems=[])

    assert validate_course(course) == ["The course has no skills.", "The course has no problems."]
