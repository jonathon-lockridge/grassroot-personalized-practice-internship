"""Checks for the course shapes, the loader and the course checker (step T1a)."""

import json
from pathlib import Path

import pytest

from practice_engine.models import Course, load_course, validate_course

# The course file, found from this test file's own location: parents[1] is two folders
# up (out of tests/ to the project root), then data/ap-physics-c-energy-momentum/course.json.
COURSE = (
    Path(__file__).resolve().parents[1] / "data" / "ap-physics-c-energy-momentum" / "course.json"
)


def test_physics_course_is_full_size_and_sound() -> None:
    course = load_course(COURSE)

    assert len(course.skills) >= 8
    assert len(course.problems) >= 10
    kinds_used = {step.kind for problem in course.problems for step in problem.steps}
    assert kinds_used == {"choice", "number", "order"}
    # Every difficulty is used, so the engine can move a student up or down.
    assert {problem.difficulty for problem in course.problems} == {1, 2, 3}
    assert validate_course(course) == []


# The three broken copies that TODO T1a names.


def test_step_naming_a_missing_skill_is_reported() -> None:
    course = load_course(COURSE)
    course.problems[0].steps[0].skill = "does_not_exist"

    complaints = validate_course(course)

    # At least one complaint should mention the made-up skill id.
    assert any("does_not_exist" in complaint for complaint in complaints)


def test_prerequisite_loop_is_reported() -> None:
    course = load_course(COURSE)
    first, second = course.skills[0], course.skills[1]
    first.prerequisites = [second.id]
    second.prerequisites = [first.id]

    complaints = validate_course(course)

    # At least one complaint should mention the loop.
    assert any("loop" in complaint for complaint in complaints)


def test_choice_answer_must_be_one_of_the_options() -> None:
    course = load_course(COURSE)
    # The first step anywhere in the course whose kind is "choice".
    choice_step = next(
        step for problem in course.problems for step in problem.steps if step.kind == "choice"
    )
    choice_step.answer = "Something not offered"

    complaints = validate_course(course)

    # At least one complaint should say the answer is not among the options.
    assert any("not one of the options" in complaint for complaint in complaints)


# One row per remaining rule: how to break the course, and words the complaint must
# contain. Each row becomes its own test.
OTHER_BREAKAGES = [
    ("empty course", lambda c: (c.skills.clear(), c.problems.clear()), "no skills"),
    ("bad skill id", lambda c: setattr(c.skills[0], "id", "Kinetic Energy"), "lowercase"),
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
        lambda c: setattr(c.problems[0].steps[0], "options", ["Mechanical energy is conserved"]),
        "at least 2 options",
    ),
    (
        "repeated option",
        lambda c: setattr(
            c.problems[0].steps[0], "options", ["Momentum is conserved", "momentum is conserved "]
        ),
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
        "tolerance on a choice step",
        lambda c: setattr(c.problems[0].steps[0], "tolerance", 0.1),
        "only 'number' steps may have a tolerance",
    ),
    (
        "zero tolerance",
        lambda c: setattr(c.problems[0].steps[1], "tolerance", 0),
        "tolerance must be a number above 0",
    ),
    (
        "one item to order",
        lambda c: setattr(c.problems[3].steps[1], "answer", ["only one"]),
        "at least 2 items",
    ),
    (
        "repeated item to order",
        lambda c: setattr(c.problems[3].steps[1], "answer", ["Same", "same"]),
        "more than once",
    ),
    ("empty problem title", lambda c: setattr(c.problems[0], "title", " "), "empty title"),
    (
        "repeated problem title",
        lambda c: setattr(c.problems[1], "title", c.problems[0].title),
        "share the title",
    ),
    (
        "feedback on a number step",
        lambda c: setattr(c.problems[0].steps[1], "feedback", {"30": "Check the units."}),
        "only 'choice' steps may have feedback",
    ),
    (
        "feedback for an option that is not offered",
        lambda c: c.problems[0].steps[0].feedback.update({"Not offered": "Why not."}),
        "'Not offered', which is not one of the options",
    ),
    (
        "feedback for the correct answer",
        lambda c: (
            c.problems[0]
            .steps[0]
            .feedback.update({c.problems[0].steps[0].answer: "This one is right."})
        ),
        "feedback is given for the correct answer",
    ),
    (
        "missing feedback for a wrong option",
        lambda c: c.problems[0].steps[0].feedback.pop("Conservation of momentum"),
        "wrong option 'Conservation of momentum' needs a feedback message",
    ),
]


@pytest.mark.parametrize(
    ("name", "break_course", "expected_words"),
    OTHER_BREAKAGES,
    ids=[row[0] for row in OTHER_BREAKAGES],
)
def test_other_rules_are_enforced(name: str, break_course, expected_words: str) -> None:
    course = load_course(COURSE)
    break_course(course)

    complaints = validate_course(course)

    assert any(expected_words in complaint for complaint in complaints), (name, complaints)


# The loader's own messages, for files a person could easily write by hand.


def _write_variant(tmp_path: Path, change) -> Path:
    """Copy the course as plain data, let `change` alter it, and save it to a file."""
    data = json.loads(COURSE.read_text())
    change(data)
    path = tmp_path / "course.json"
    path.write_text(json.dumps(data))
    return path


def test_missing_field_is_reported_counting_from_one(tmp_path: Path) -> None:
    path = _write_variant(tmp_path, lambda d: d["problems"][1]["steps"][2].pop("hint"))

    with pytest.raises(ValueError) as error:
        load_course(path)

    assert "problem 2, step 3, 'hint': is missing" in str(error.value)


def test_missing_problem_title_is_reported(tmp_path: Path) -> None:
    path = _write_variant(tmp_path, lambda d: d["problems"][0].pop("title"))

    with pytest.raises(ValueError) as error:
        load_course(path)

    assert "problem 1, 'title': is missing" in str(error.value)


def test_misspelled_field_name_is_reported(tmp_path: Path) -> None:
    path = _write_variant(
        tmp_path, lambda d: d["skills"][1].update(prerequisite=d["skills"][1].pop("prerequisites"))
    )

    with pytest.raises(ValueError) as error:
        load_course(path)

    assert "skill 2, 'prerequisite': is not a field name we know" in str(error.value)


def test_broken_json_is_reported_with_a_line_number(tmp_path: Path) -> None:
    path = tmp_path / "course.json"
    path.write_text('{\n  "id": "ap-physics-c-energy-momentum",,\n}')

    with pytest.raises(ValueError) as error:
        load_course(path)

    assert "not valid JSON" in str(error.value)
    assert "line 2" in str(error.value)


def test_a_course_can_also_be_built_in_code() -> None:
    # The shapes work without a file too, which later steps will rely on.
    course = Course(id="demo", title="Demo", skills=[], problems=[])

    assert validate_course(course) == ["The course has no skills.", "The course has no problems."]


# Units and lessons (decided 2026-11-26): a course follows its own curriculum.


def test_physics_course_lessons_follow_the_curriculum() -> None:
    course = load_course(COURSE)
    lesson_of = {
        skill: lesson.title
        for unit in course.units
        for lesson in unit.lessons
        for skill in lesson.skills
    }

    # Every skill but the one used in every problem is taught in exactly one lesson.
    assert set(lesson_of) == {skill.id for skill in course.skills} - {"choose_principle"}
    assert lesson_of["gravitational_energy"].startswith("6.6")
    assert lesson_of["center_of_mass"].startswith("2.1")
    assert all(lesson.notes for unit in course.units for lesson in unit.lessons)


def test_a_course_without_units_is_still_sound() -> None:
    course = load_course(COURSE)
    course.units = []

    assert validate_course(course) == []


@pytest.mark.parametrize(
    ("name", "break_course", "expected_words"),
    [
        ("unknown skill", lambda c: c.units[0].lessons[0].skills.append("nope"), "'nope'"),
        (
            "skill in two lessons",
            lambda c: c.units[1].lessons[0].skills.append(c.units[1].lessons[1].skills[0]),
            "in two lessons",
        ),
        ("no skills", lambda c: c.units[0].lessons[0].skills.clear(), "teaches no skills"),
        ("bad id", lambda c: setattr(c.units[0].lessons[0], "id", "2.1"), "Lesson id '2.1'"),
        (
            "repeated id",
            lambda c: setattr(c.units[0].lessons[1], "id", c.units[0].lessons[0].id),
            "used more than once",
        ),
        ("empty title", lambda c: setattr(c.units[0], "title", " "), "Unit 1 has an empty title"),
        ("no lessons", lambda c: c.units[0].lessons.clear(), "Unit 1 has no lessons"),
        ("empty note", lambda c: c.units[0].lessons[0].notes.append(""), "empty note"),
        (
            "only everywhere skills",
            lambda c: setattr(c.units[0].lessons[0], "skills", ["choose_principle"]),
            "nothing of its own",
        ),
    ],
)
def test_lesson_rules_are_enforced(name: str, break_course, expected_words: str) -> None:
    course = load_course(COURSE)
    break_course(course)

    complaints = validate_course(course)

    assert any(expected_words in complaint for complaint in complaints), (name, complaints)
