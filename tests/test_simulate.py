"""Checks for the simulated students (step T6).

Most tests use a tiny course built in code, so a run takes a moment. One test runs
the real physics course with a few students, to make sure the command works on it.
"""

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from practice_engine import simulate
from practice_engine.mastery import new_mastery_state, update_mastery
from practice_engine.models import (
    Course,
    MasteryState,
    Problem,
    Skill,
    Step,
    StepAnswer,
    load_course,
)
from practice_engine.selection import Pick
from practice_engine.simulate import (
    CHECKPOINTS,
    STUDENT_TYPES,
    BktStudent,
    CurveStudent,
    RunResult,
    ScriptedStudent,
    _batch_faults,
    _head_to_head,
    compare,
    engine_policy,
    expert_order,
    format_report,
    main,
    make_random_policy,
    run_scenario,
    run_student,
)

COURSE = (
    Path(__file__).resolve().parents[1] / "data" / "ap-physics-c-energy-momentum" / "course.json"
)
START = datetime(2026, 1, 5, 16, 0, tzinfo=UTC)


def tiny_course() -> Course:
    """Three skills: "a", "b" (needs "a") and "c", and five problems of number
    steps. Every problem starts with a step on "a", so "a" is in every problem."""
    problems = {
        "p1": (1, ["a", "a"]),
        "p2": (1, ["a", "c"]),
        "p3": (2, ["a", "b", "b"]),
        "p4": (2, ["a", "c", "b"]),
        "p5": (3, ["a", "b", "c"]),
    }
    return Course(
        id="tiny",
        title="Tiny course",
        skills=[
            Skill(id="a", name="Skill a"),
            Skill(id="b", name="Skill b", prerequisites=["a"]),
            Skill(id="c", name="Skill c"),
        ],
        problems=[
            Problem(
                id=problem_id,
                title=f"Problem {problem_id}",
                prompt="A problem.",
                difficulty=difficulty,
                steps=[
                    Step(prompt="A step.", kind="number", answer=1, hint="A hint.", skill=skill)
                    for skill in skills
                ],
            )
            for problem_id, (difficulty, skills) in problems.items()
        ],
    )


def step_on(course: Course, skill_id: str) -> Step:
    """The first step of the course that practices `skill_id`."""
    return next(
        step for problem in course.problems for step in problem.steps if step.skill == skill_id
    )


# Students


def test_each_student_type_only_improves_the_skill_it_practices():
    course = tiny_course()
    for make_student in STUDENT_TYPES.values():
        student = make_student(course, np.random.default_rng(3))
        before = student.knowledge()
        for _ in range(30):
            student.answer(step_on(course, "c"), START)
        after = student.knowledge()
        assert after["c"] > before["c"]
        # No other skill rose. (A curve student may forget, so they may fall.)
        assert after["a"] <= before["a"]
        assert after["b"] <= before["b"]


def test_a_curve_student_forgets_a_skill_left_alone():
    course = tiny_course()
    student = CurveStudent(course, np.random.default_rng(3))
    for _ in range(10):
        student.answer(step_on(course, "c"), START)
    soon = student.knowledge_at(START)["c"]
    later = student.knowledge_at(START.replace(month=3))["c"]
    assert later < soon


def test_a_curve_student_learns_more_slowly_without_the_prerequisite():
    course = tiny_course()
    ready = CurveStudent(course, np.random.default_rng(3))
    not_ready = CurveStudent(course, np.random.default_rng(3))  # the same student
    for _ in range(40):
        ready.answer(step_on(course, "a"), START)
    assert ready.knows("a", START)
    for student in (ready, not_ready):
        for _ in range(4):
            student.answer(step_on(course, "b"), START)
    assert ready.knowledge()["b"] > not_ready.knowledge()["b"]


def test_a_bkt_student_who_knows_a_skill_is_right_far_more_often():
    course = tiny_course()
    student = BktStudent(course, np.random.default_rng(5))
    student._known = {"a": True, "b": False, "c": False}  # set the hidden truth directly
    right_a = sum(student.answer(step_on(course, "a"), START) for _ in range(200))
    assert right_a > 150  # at most a few slips


# Policies


def test_the_random_order_repeats_with_the_same_seed():
    course = tiny_course()
    state = new_mastery_state(course, "sim")
    policy, same_seed = make_random_policy(7), make_random_policy(7)
    first = [policy(course, state, [], START) for _ in range(5)]
    again = [same_seed(course, state, [], START) for _ in range(5)]
    assert first == again
    assert all(len(batch) == 3 for batch in first)


def test_the_expert_order_puts_prerequisites_first():
    course = tiny_course()
    order = expert_order(course)
    # p1 practices only "a"; p2 adds "c"; p3, p4 and p5 need "b", which builds on "a".
    assert sorted(order) == ["p1", "p2", "p3", "p4", "p5"]
    assert order.index("p1") < order.index("p3")
    assert order.index("p1") < order.index("p4")


def test_the_engine_never_sees_the_students_true_knowledge():
    # The policy is handed only the course, the engine's own mastery numbers, the
    # answers and the time. The mastery numbers are exactly what replaying the
    # answers through update_mastery gives, so nothing else leaks into them.
    course = tiny_course()
    seen: list[tuple] = []

    def spy(course_seen, state, history, now):
        seen.append((course_seen, state, list(history), now))
        return engine_policy(course_seen, state, history, now)

    student = BktStudent(course, np.random.default_rng(1))
    run_student(course, student, spy, max_steps=40, start=START)
    assert seen
    for course_seen, state, history, now in seen:
        assert course_seen is course
        assert type(state) is MasteryState
        assert all(type(answer) is StepAnswer for answer in history)
        assert isinstance(now, datetime)
        replayed = new_mastery_state(course, state.nickname)
        for answer in history:
            replayed = update_mastery(replayed, answer, course)
        assert replayed == state


def test_the_random_order_draws_its_own_numbers_not_the_students(monkeypatch):
    # If the random order and the student started from the same seed, the problems
    # drawn would be tied to the student's hidden numbers and answers.
    order_seeds, student_seeds = [], []
    real_policy = simulate.make_random_policy

    def recording_policy(seed):
        order_seeds.append(seed)
        return real_policy(seed)

    def recording_student(course, rng):
        student_seeds.append(rng.bit_generator.seed_seq.entropy)
        return BktStudent(course, rng)

    monkeypatch.setattr(simulate, "make_random_policy", recording_policy)
    monkeypatch.setattr(simulate, "STUDENT_TYPES", {"BKT-like": recording_student})
    compare(tiny_course(), students=3, seed=1, max_steps=10)
    assert order_seeds and student_seeds
    assert not set(order_seeds) & set(student_seeds)


def pick(problem_id: str, skill: str) -> Pick:
    """A hand-made pick, for checking the batch rules."""
    return Pick(
        problem_id=problem_id,
        target_skill=skill,
        reason="A reason.",
        is_follow_up=False,
        rule="partway",
    )


def test_the_batch_checks_catch_each_broken_rule():
    course = tiny_course()
    assert _batch_faults(course, [pick("p2", "c"), pick("p3", "b")]) == []
    assert "empty" in _batch_faults(course, [])[0]
    assert "every problem" in _batch_faults(course, [pick("p1", "a")])[0]
    assert "not in the course" in _batch_faults(course, [pick("nope", "c")])[0]
    many = [pick("p2", "c"), pick("p3", "b"), pick("p4", "x"), pick("p5", "y")]
    assert any("more than" in fault for fault in _batch_faults(course, many))


def test_a_policy_that_gives_an_empty_batch_is_reported_as_a_rule_break():
    course = tiny_course()
    student = ScriptedStudent(course, wrong_skills={"c"})
    result = run_student(course, student, lambda *_: [], max_steps=30, start=START)
    assert result.steps_done == 0
    assert "empty batch" in result.rule_breaks[0]


# Runs


def test_a_run_counts_steps_until_every_skill_is_known():
    course = tiny_course()
    # A scripted student who already knows everything is known from the start.
    student = ScriptedStudent(course, wrong_skills=set())
    result = run_student(course, student, engine_policy, max_steps=30, start=START)
    assert result.steps_to_all_known == 0
    assert result.knowledge_at_end == 1.0


def test_a_student_who_never_learns_never_finishes():
    course = tiny_course()
    student = ScriptedStudent(course, wrong_skills={"c"})
    result = run_student(course, student, engine_policy, max_steps=30, start=START)
    assert result.steps_to_all_known is None
    assert result.steps_done >= 30


def test_the_engine_breaks_none_of_its_batch_rules_on_the_tiny_course():
    course = tiny_course()
    for make_student in STUDENT_TYPES.values():
        student = make_student(course, np.random.default_rng(2))
        result = run_student(course, student, engine_policy, max_steps=120, start=START)
        assert result.rule_breaks == []


def test_a_run_records_true_knowledge_at_each_checkpoint_and_when_each_skill_was_known():
    course = tiny_course()
    student = CurveStudent(course, np.random.default_rng(4))
    result = run_student(course, student, engine_policy, max_steps=CHECKPOINTS[0], start=START)
    assert set(result.knowledge_at_checkpoint) == {CHECKPOINTS[0]}
    assert 0 <= result.knowledge_at_checkpoint[CHECKPOINTS[0]] <= 1
    assert set(result.steps_to_known) <= {"a", "b", "c"}
    assert all(0 < steps <= result.steps_done for steps in result.steps_to_known.values())


def test_head_to_head_counts_neither_finished_apart_from_ties():
    done = [RunResult(steps_to_all_known=n) for n in (10, 20, None, None, 5)]
    other = [RunResult(steps_to_all_known=n) for n in (20, 20, None, 9, 1)]
    # fewer, the same, more, neither finished
    assert _head_to_head(done, other) == (1, 1, 2, 1)


def test_the_same_seed_gives_the_same_report():
    course = tiny_course()
    first = format_report(course, compare(course, students=3, seed=11, max_steps=80))
    again = format_report(course, compare(course, students=3, seed=11, max_steps=80))
    assert first == again


def test_the_report_names_every_order_and_student_type():
    course = tiny_course()
    report = format_report(course, compare(course, students=2, seed=1, max_steps=60))
    for word in ("Engine", "Random", "Expert", "BKT-like", "Learning-curve"):
        assert word in report


# Scenarios


def test_the_all_correct_scenario_lists_when_each_skill_was_first_targeted():
    course = tiny_course()
    scenario = run_scenario(course, wrong_skills=set(), rounds=10, start=START)
    # "a" is in every problem, so the engine never targets it.
    assert "a" not in scenario.first_targeted
    assert set(scenario.first_targeted) | set(scenario.never_targeted) == {"b", "c"}


def test_the_always_wrong_scenario_reports_the_longest_run_of_one_first_pick():
    course = tiny_course()
    scenario = run_scenario(course, wrong_skills={"c"}, rounds=10, start=START)
    assert 1 <= scenario.longest_same_first_pick <= 10
    assert len(scenario.first_picks) == 10


# The command


def test_the_command_runs_on_the_physics_course(capsys):
    main(["--students", "2", "--seed", "1", "--max-steps", "150", "--course", str(COURSE)])
    printed = capsys.readouterr().out
    assert "Engine" in printed
    assert load_course(COURSE).id in printed


@pytest.mark.parametrize("flag", ["--students", "--max-steps"])
def test_the_command_refuses_a_count_below_one(flag):
    with pytest.raises(SystemExit):
        main([flag, "0", "--course", str(COURSE)])
