"""Does the engine's order help students learn faster? (step T6)

Simulated students, run by the computer, practice a real course. Each one has a
hidden true knowledge of every skill. The engine never sees it. It sees only the
answers, as it would with a real student. Three orders of problems are compared on
the same students:

- Engine: next_problems picks each batch, and update_mastery follows every answer.
- Random: three problems drawn at random each time.
- Expert: a fixed order a teacher might use: the course's skills with prerequisites
  first, each skill's problems from easy to hard, then round again.

Two kinds of student, because students made to behave exactly like the engine's
own model would flatter it (research report, change 8):

- BKT-like: knows a skill or does not. Each step on a skill has a fixed chance of
  teaching it, and the student can still guess right or slip. This is the model
  the engine assumes.
- Learning-curve: a different model. The chance of a right answer grows a little
  with each step practiced, more slowly when a prerequisite is not known, and fades
  a little every day the skill is left alone.

For each order the report says how many steps it took until every skill was truly
known, when each skill was first known, how much students truly knew after 100,
200 and 300 steps, and how many steps went on skills the student already knew
(over-practice). It also prints a few checks on each order's batches, and two fixed
scenarios: a student who gets everything right, and students who always get one
skill wrong.

Run it from the repo folder:

    python -m practice_engine.simulate --students 50 --seed 1

The same seed always prints the same report. The numbers below were set once,
before the first run, and were not changed afterwards to help the engine win.

How to read this file: see the note at the top of models.py. Also, `rng` is a
random number maker from numpy; `rng.random()` gives a number from 0 to 1, so
`rng.random() < 0.3` is true 3 times in 10. A `@dataclass` is a simple record
with named fields. Nothing here knows about physics or math.
"""

import argparse
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from practice_engine.mastery import new_mastery_state, update_mastery
from practice_engine.models import Course, MasteryState, Step, StepAnswer, load_course
from practice_engine.selection import MAX_BATCH_SKILLS, Pick, next_problems
from practice_engine.selection import _skills_in_every_problem as skills_in_every_problem

# A policy is anything that is given (course, mastery state, answers so far, time now)
# and gives back the ids of the next problems to do, in order. It never gets the student.
Policy = Callable[[Course, MasteryState, list[StepAnswer], datetime], list[str]]

# How the simulated practice runs. Set once, not tuned to any result.

# Problems per batch for the random and expert orders, the same as the engine's default.
BATCH_SIZE = 3
# Minutes a simulated student spends on one step.
STEP_MINUTES = 2
# Problems a simulated student does in one day before stopping until the next day.
PROBLEMS_PER_DAY = 6
# Seconds recorded for every step: well above mastery.py's fast-guess cutoff.
STEP_SECONDS = 60
# A skill counts as truly known when the student's hidden knowledge is at least this.
TRULY_KNOWN = 0.9
# The number of first problems in which "new skills started" is counted.
NEW_SKILL_WINDOW = 30
# Added to a student's seed to seed the random order, so the problems it draws are
# not tied to the student's hidden numbers or answers.
RANDOM_ORDER_SEED_OFFSET = 1_000_000
# Steps after which each student's average true knowledge is written down.
CHECKPOINTS = (100, 200, 300)
# The engine's rule against repeating a problem within this many hours (checked here).
REPEAT_HOURS = 24

# BKT-like students. Each student gets their own numbers, drawn from these ranges.
BKT_LEARN = (0.1, 0.3)  # chance that one step on a skill teaches it
BKT_START_KNOWN = 0.1  # chance that a skill is already known at the start

# Both kinds of student: chances drawn per student from these ranges.
GUESS = (0.1, 0.3)  # right without knowing the skill
SLIP = (0.05, 0.15)  # wrong while knowing it

# Learning-curve students. Their knowledge of a skill is a number from 0 to 1 that
# comes from a "strength" through the S-shaped logistic curve: strength 0 is
# knowledge 0.5, and each 1 added moves it a good way toward 1.
CURVE_START = -3.0  # starting strength: knowledge about 0.05
CURVE_LEARN = (0.5, 1.0)  # strength gained per step practiced, drawn per student
# The share of that gain kept while some prerequisite of the skill is not known.
CURVE_LEARN_WITHOUT_PREREQUISITE = 0.5
# Strength lost per day a skill is left alone (never below the starting strength).
CURVE_FORGET_PER_DAY = 0.1
# Strength taken off, for one answer, per prerequisite the student does not know:
# a student is less likely to get a step right when the basics under it are shaky.
CURVE_PREREQUISITE_PENALTY = 1.0


# The students. Each kind has the same four methods:
# answer(step, now) -> right or wrong (and learns from the step), knowledge_at(now)
# -> skill id -> hidden knowledge, knowledge() -> the same at the latest time seen,
# and knows(skill_id, now).


class _Student:
    """What every simulated student shares."""

    def __init__(self, course: Course):
        self._skills = [skill.id for skill in course.skills]
        self._prerequisites = {skill.id: skill.prerequisites for skill in course.skills}
        self._clock: datetime | None = None  # the latest time the student answered

    def knowledge_at(self, now: datetime | None) -> dict[str, float]:
        raise NotImplementedError  # each kind of student fills this in

    def knowledge(self) -> dict[str, float]:
        return self.knowledge_at(self._clock)

    def knows(self, skill_id: str, now: datetime | None) -> bool:
        return self.knowledge_at(now)[skill_id] >= TRULY_KNOWN


class BktStudent(_Student):
    """Knows each skill or does not, and may learn it on each step practiced."""

    def __init__(self, course: Course, rng: np.random.Generator):
        super().__init__(course)
        self._rng = rng
        self._learn = rng.uniform(*BKT_LEARN)  # `*` passes the two ends of the range
        self._guess = rng.uniform(*GUESS)
        self._slip = rng.uniform(*SLIP)
        self._known = {skill_id: rng.random() < BKT_START_KNOWN for skill_id in self._skills}

    def answer(self, step: Step, now: datetime) -> bool:
        self._clock = now
        knows = self._known[step.skill]
        right = self._rng.random() < (1 - self._slip if knows else self._guess)
        # Doing the step may teach the skill, whether the answer was right or not.
        if not knows and self._rng.random() < self._learn:
            self._known[step.skill] = True
        return right

    def knowledge_at(self, now: datetime | None) -> dict[str, float]:
        return {skill_id: 1.0 if known else 0.0 for skill_id, known in self._known.items()}


class CurveStudent(_Student):
    """Gets a little better with each step, slower without the basics, and forgets."""

    def __init__(self, course: Course, rng: np.random.Generator):
        super().__init__(course)
        self._rng = rng
        self._learn = rng.uniform(*CURVE_LEARN)
        self._guess = rng.uniform(*GUESS)
        self._slip = rng.uniform(*SLIP)
        self._strength = {skill_id: CURVE_START for skill_id in self._skills}
        self._last_practiced: dict[str, datetime] = {}

    def answer(self, step: Step, now: datetime) -> bool:
        self._clock = now
        skill = step.skill
        missing = [p for p in self._prerequisites[skill] if not self.knows(p, now)]
        strength = self._strength_at(skill, now)
        know = _logistic(strength - CURVE_PREREQUISITE_PENALTY * len(missing))
        # Right if they know it and do not slip, or by a guess.
        right = self._rng.random() < self._guess + (1 - self._guess - self._slip) * know
        gain = self._learn * (CURVE_LEARN_WITHOUT_PREREQUISITE if missing else 1)
        self._strength[skill] = strength + gain
        self._last_practiced[skill] = now
        return right

    def knowledge_at(self, now: datetime | None) -> dict[str, float]:
        return {skill_id: _logistic(self._strength_at(skill_id, now)) for skill_id in self._skills}

    def _strength_at(self, skill_id: str, now: datetime | None) -> float:
        """The skill's strength at `now`, after forgetting since it was last practiced."""
        strength = self._strength[skill_id]
        last = self._last_practiced.get(skill_id)
        if now is None or last is None:
            return strength
        days = max(0.0, (now - last) / timedelta(days=1))
        return max(CURVE_START, strength - CURVE_FORGET_PER_DAY * days)


class ScriptedStudent(_Student):
    """Not random: always right, except always wrong on the skills in `wrong_skills`.
    Used for the fixed scenarios."""

    def __init__(self, course: Course, wrong_skills: set[str]):
        super().__init__(course)
        self._wrong = set(wrong_skills)

    def answer(self, step: Step, now: datetime) -> bool:
        self._clock = now
        return step.skill not in self._wrong

    def knowledge_at(self, now: datetime | None) -> dict[str, float]:
        return {skill_id: 0.0 if skill_id in self._wrong else 1.0 for skill_id in self._skills}


# The two random kinds of student, by the name the report shows.
STUDENT_TYPES = {"BKT-like": BktStudent, "Learning-curve": CurveStudent}


def _logistic(strength: float) -> float:
    """The S-shaped curve: any number in, a number from 0 to 1 out."""
    return 1 / (1 + math.exp(-strength))


# The three orders.


class RuleBreak(Exception):
    """The engine gave a batch that breaks one of its own promises."""


def engine_policy(
    course: Course, state: MasteryState, history: list[StepAnswer], now: datetime
) -> list[str]:
    """The engine's next problems. Stops with a RuleBreak if the batch breaks a rule."""
    picks = next_problems(course, state, history, now)
    faults = _batch_faults(course, picks)
    if faults:
        raise RuleBreak("; ".join(faults))
    return [pick.problem_id for pick in picks]


def make_random_policy(seed: int) -> Policy:
    """A policy that draws BATCH_SIZE different problems at random each time. The same
    seed gives the same draws."""
    rng = np.random.default_rng(seed)

    def random_policy(course, state, history, now):
        size = min(BATCH_SIZE, len(course.problems))
        chosen = rng.choice(len(course.problems), size=size, replace=False)
        return [course.problems[index].id for index in chosen]

    return random_policy


def expert_order(course: Course) -> list[str]:
    """Every problem id once, in a fixed teacher's order: skills in course order with
    each skill's prerequisites first, and each problem placed at the latest skill it
    uses (leaving out a skill every problem has), easy before hard."""
    skill_order: list[str] = []
    prerequisites = {skill.id: skill.prerequisites for skill in course.skills}

    def place(skill_id: str) -> None:
        # Put a skill's prerequisites in the list before the skill itself.
        if skill_id in skill_order or skill_id not in prerequisites:
            return
        for prerequisite in prerequisites[skill_id]:
            place(prerequisite)
        skill_order.append(skill_id)

    for skill in course.skills:
        place(skill.id)
    everywhere = skills_in_every_problem(course)

    def latest_skill(index: int) -> int:
        skills = {step.skill for step in course.problems[index].steps}
        skills = (skills - everywhere) or skills
        return max(skill_order.index(skill_id) for skill_id in skills)

    indexes = sorted(
        range(len(course.problems)),
        key=lambda i: (latest_skill(i), course.problems[i].difficulty, i),
    )
    return [course.problems[i].id for i in indexes]


def expert_policy(
    course: Course, state: MasteryState, history: list[StepAnswer], now: datetime
) -> list[str]:
    """The next BATCH_SIZE problems of expert_order, going round again at the end."""
    order = expert_order(course)
    done = sum(1 for answer in history if answer.step_position == 1)  # problems started
    return [order[(done + k) % len(order)] for k in range(min(BATCH_SIZE, len(order)))]


def _batch_faults(course: Course, picks: list[Pick]) -> list[str]:
    """Plain complaints about an engine batch that breaks one of its promises."""
    faults = []
    if not picks and any(problem.steps for problem in course.problems):
        faults.append("the batch is empty although the course has problems")
    targets = {pick.target_skill for pick in picks}
    if len(targets) > MAX_BATCH_SKILLS:
        faults.append(f"the batch targets {len(targets)} skills, more than {MAX_BATCH_SKILLS}")
    for skill_id in targets & skills_in_every_problem(course):
        faults.append(f"a pick targets '{skill_id}', which every problem already practices")
    problem_ids = {problem.id for problem in course.problems}
    for pick in picks:
        if pick.problem_id not in problem_ids:
            faults.append(f"a pick names '{pick.problem_id}', which is not in the course")
    return faults


# One student practicing with one order.


@dataclass
class RunResult:
    """What happened when one simulated student practiced with one order."""

    steps_done: int = 0
    # Steps answered before every skill was truly known at once; None if that never
    # happened. 0 means the student knew everything from the start.
    steps_to_all_known: int | None = None
    knowledge_at_end: float = 0.0  # the student's average true knowledge at the end
    # Steps (from CHECKPOINTS) -> the student's average true knowledge right then.
    knowledge_at_checkpoint: dict[int, float] = field(default_factory=dict)
    # Skill id -> steps answered when the student first truly knew it (0: from the start).
    steps_to_known: dict[str, int] = field(default_factory=dict)
    # Of the steps before every skill was known: how many, and how many of those were
    # on a skill the student already truly knew (leaving out a skill every problem has).
    counted_steps: int = 0
    over_practice: int = 0
    batches: list[list[str]] = field(default_factory=list)  # each batch's problem ids
    repeats: int = 0  # picks of a problem done within the last REPEAT_HOURS
    rule_breaks: list[str] = field(default_factory=list)


def run_student(
    course: Course,
    student: _Student,
    policy: Policy,
    max_steps: float,
    start: datetime,
    max_batches: int | None = None,
) -> RunResult:
    """Let `student` practice `course` in the order `policy` gives, until `max_steps`
    steps are answered (a problem already begun is finished) or `max_batches` batches
    are done. Only first tries, never a hint."""
    result = RunResult()
    state = new_mastery_state(course, "sim")
    history: list[StepAnswer] = []
    problems = {problem.id: problem for problem in course.problems}
    everywhere = skills_in_every_problem(course)
    last_done: dict[str, datetime] = {}  # problem id -> when it was last done
    now, problems_today, day = start, 0, 0

    def all_known() -> bool:
        # Also notes each skill the first time it is known.
        knowledge = student.knowledge_at(now)
        for skill_id, value in knowledge.items():
            if value >= TRULY_KNOWN:
                result.steps_to_known.setdefault(skill_id, result.steps_done)
        return all(value >= TRULY_KNOWN for value in knowledge.values())

    if all_known():
        result.steps_to_all_known = 0
    while result.steps_done < max_steps:
        if max_batches is not None and len(result.batches) >= max_batches:
            break
        try:
            batch = policy(course, state, history, now)
        except RuleBreak as fault:
            result.rule_breaks.append(f"after {result.steps_done} steps: {fault}")
            break
        if not batch:
            result.rule_breaks.append(f"after {result.steps_done} steps: an empty batch")
            break
        result.batches.append(batch)
        for problem_id in batch:
            if problem_id in last_done and now - last_done[problem_id] < timedelta(
                hours=REPEAT_HOURS
            ):
                result.repeats += 1
        for problem_id in batch:
            problem = problems[problem_id]
            for position, step in enumerate(problem.steps, start=1):
                if result.steps_to_all_known is None:
                    result.counted_steps += 1
                    if step.skill not in everywhere and student.knows(step.skill, now):
                        result.over_practice += 1
                answer = StepAnswer(
                    nickname=state.nickname,
                    problem_id=problem_id,
                    step_position=position,
                    correct=student.answer(step, now),
                    seconds=STEP_SECONDS,
                    hints_used=0,
                    answered_at=now,
                )
                state = update_mastery(state, answer, course)
                history.append(answer)
                result.steps_done += 1
                if not 0 <= state.mastery[step.skill] <= 1:
                    result.rule_breaks.append(f"mastery of '{step.skill}' left 0 to 1")
                now += timedelta(minutes=STEP_MINUTES)
                if all_known() and result.steps_to_all_known is None:
                    result.steps_to_all_known = result.steps_done
                if result.steps_done in CHECKPOINTS:
                    knowledge = student.knowledge_at(now)
                    average = sum(knowledge.values()) / len(knowledge)
                    result.knowledge_at_checkpoint[result.steps_done] = average
            last_done[problem_id] = now
            problems_today += 1
            if problems_today == PROBLEMS_PER_DAY:  # done for today: start the next day
                problems_today, day = 0, day + 1
                now = start + timedelta(days=day)
    end = student.knowledge_at(now)
    result.knowledge_at_end = sum(end.values()) / len(end)
    return result


# Comparing the orders over many students.

ORDERS = ("Engine", "Random", "Expert")


def compare(
    course: Course, students: int, seed: int, max_steps: int, start: datetime | None = None
) -> dict[tuple[str, str], list[RunResult]]:
    """Run `students` students of each kind with each order. The same student (the
    same seed) is used for all three orders. Gives back (student kind, order) ->
    one result per student."""
    start = start or DEFAULT_START
    results: dict[tuple[str, str], list[RunResult]] = {}
    for kind_number, (kind, make_student) in enumerate(STUDENT_TYPES.items()):
        for number in range(students):
            student_seed = seed * 100_000 + kind_number * 10_000 + number
            policies = {
                "Engine": engine_policy,
                "Random": make_random_policy(student_seed + RANDOM_ORDER_SEED_OFFSET),
                "Expert": expert_policy,
            }
            for order in ORDERS:
                student = make_student(course, np.random.default_rng(student_seed))
                run = run_student(course, student, policies[order], max_steps, start)
                results.setdefault((kind, order), []).append(run)
    return results


def format_report(course: Course, results: dict[tuple[str, str], list[RunResult]]) -> str:
    """The comparison as plain text tables."""
    lines: list[str] = []
    kinds = list(dict.fromkeys(kind for kind, _ in results))  # in order, each once
    for kind in kinds:
        runs = {order: results[(kind, order)] for order in ORDERS}
        count = len(runs["Engine"])
        lines.append(f"{kind} students ({count} of them)")
        checkpoint_heads = "".join(f"{f'Known @{steps}':>12}" for steps in CHECKPOINTS)
        lines.append(
            f"  {'Order':<8}{'Finished':>10}{'Median steps':>14}"
            f"{checkpoint_heads}{'Over-practice':>15}"
        )
        for order in ORDERS:
            finished = [r.steps_to_all_known for r in runs[order]]
            done = sum(1 for steps in finished if steps is not None)
            median = _median_steps(finished)
            known = "".join(f"{_checkpoint(runs[order], steps):>12}" for steps in CHECKPOINTS)
            counted = sum(r.counted_steps for r in runs[order])
            over = sum(r.over_practice for r in runs[order]) / counted if counted else 0
            lines.append(f"  {order:<8}{f'{done} of {count}':>10}{median:>14}{known}{over:>15.0%}")
        for other in ("Random", "Expert"):
            fewer, tied, more, neither = _head_to_head(runs["Engine"], runs[other])
            lines.append(
                f"  Engine vs {other}: fewer steps for {fewer} students, the same for "
                f"{tied}, more for {more}, neither finished for {neither}."
            )
        lines.append("")
        lines.append(f"  Checks on each order's batches ({kind} students)")
        lines.append(
            f"  {'Order':<8}{f'Started in {NEW_SKILL_WINDOW}':>19}{'2+ principles':>15}"
            f"{'Repeats <24h':>14}{'Same first pick':>17}"
        )
        for order in ORDERS:
            new, mixed, repeats, run_length = _batch_checks(course, runs[order])
            lines.append(f"  {order:<8}{new:>19.1f}{mixed:>15.0%}{repeats:>14.0%}{run_length:>17}")
        for order in ORDERS:
            breaks = [fault for r in runs[order] for fault in r.rule_breaks]
            example = f" ({breaks[0]})" if breaks else ""
            lines.append(f"  {order} rule breaks: {len(breaks)}{example}")
        lines.append("")
        lines.append(f"  Median steps until each skill was first truly known ({kind} students)")
        lines.append(f"  {'Skill':<32}" + "".join(f"{order:>13}" for order in ORDERS))
        for skill in course.skills:
            medians = [
                _median_steps([r.steps_to_known.get(skill.id) for r in runs[order]])
                for order in ORDERS
            ]
            lines.append(f"  {skill.name[:31]:<32}" + "".join(f"{m:>13}" for m in medians))
        lines.append("")
    return "\n".join(lines)


def _checkpoint(runs: list[RunResult], steps: int) -> str:
    """The average true knowledge after `steps` steps, over the runs that got that far."""
    values = [r.knowledge_at_checkpoint[steps] for r in runs if steps in r.knowledge_at_checkpoint]
    return f"{np.mean(values):.2f}" if values else "-"


def _median_steps(finished: list[int | None]) -> str:
    """The middle number of steps, counting a student who never finished as slowest."""
    ordered = sorted(finished, key=lambda steps: math.inf if steps is None else steps)
    middle = ordered[(len(ordered) - 1) // 2] if ordered else None
    return "not reached" if middle is None else str(middle)


def _head_to_head(engine: list[RunResult], other: list[RunResult]) -> tuple[int, int, int, int]:
    """For the same students: how often the engine needed fewer, the same, or more steps,
    and how often neither order finished. A student who finished with only one order
    counts as fewer steps for that order."""
    fewer = tied = more = neither = 0
    for mine, theirs in zip(engine, other, strict=True):
        a = math.inf if mine.steps_to_all_known is None else mine.steps_to_all_known
        b = math.inf if theirs.steps_to_all_known is None else theirs.steps_to_all_known
        if a == b == math.inf:
            neither += 1
        else:
            fewer, tied, more = fewer + (a < b), tied + (a == b), more + (a > b)
    return fewer, tied, more, neither


def _batch_checks(course: Course, runs: list[RunResult]) -> tuple[float, float, float, int]:
    """Four checks over every batch of `runs`: how many skills were started in the first
    NEW_SKILL_WINDOW problems (not counting a skill every problem has); the share of
    batches whose problems start with 2 or more different first-step answers (different
    principles); the share of picks that
    repeat a problem from the last day; and the longest run of the same first pick.
    The principles check assumes a problem's first step is its "which principle?" step."""
    problems = {problem.id: problem for problem in course.problems}
    everywhere = skills_in_every_problem(course)
    started_counts, mixed, multi, repeats, picks, longest = [], 0, 0, 0, 0, 0
    for run in runs:
        order = [problem_id for batch in run.batches for problem_id in batch]
        started = {
            step.skill
            for problem_id in order[:NEW_SKILL_WINDOW]
            for step in problems[problem_id].steps
        } - everywhere
        started_counts.append(len(started))
        for batch in run.batches:
            if len(batch) >= 2:
                multi += 1
                firsts = {str(problems[problem_id].steps[0].answer) for problem_id in batch}
                mixed += len(firsts) >= 2
        repeats += run.repeats
        picks += len(order)
        longest = max(longest, _longest_run([batch[0] for batch in run.batches]))
    return (
        float(np.mean(started_counts)) if started_counts else 0.0,
        mixed / multi if multi else 0.0,
        repeats / picks if picks else 0.0,
        longest,
    )


def _longest_run(items: list[str]) -> int:
    """The length of the longest stretch of one item repeated back to back."""
    longest = current = 0
    for index, item in enumerate(items):
        current = current + 1 if index and item == items[index - 1] else 1
        longest = max(longest, current)
    return longest


# Fixed scenarios. Printed, not pass/fail, because the next-problem rules are still
# changing; they show what the engine does in two cases reviewers worried about.


@dataclass
class ScenarioResult:
    """What the engine picked for a scripted student over a number of batches."""

    first_picks: list[str]  # the first problem of each batch
    first_targeted: dict[str, int]  # skill id -> the pick number when first targeted
    never_targeted: list[str]  # skills never targeted (not counting an every-problem skill)
    longest_same_first_pick: int


def run_scenario(
    course: Course, wrong_skills: set[str], rounds: int, start: datetime | None = None
) -> ScenarioResult:
    """A scripted student (always right except on `wrong_skills`) does `rounds` engine
    batches. Records which skill each pick targeted."""
    all_picks: list[Pick] = []

    def recording_policy(course_seen, state, history, now):
        picks = next_problems(course_seen, state, history, now)
        all_picks.extend(picks)
        return [pick.problem_id for pick in picks]

    student = ScriptedStudent(course, wrong_skills)
    run = run_student(
        course, student, recording_policy, math.inf, start or DEFAULT_START, max_batches=rounds
    )
    first_targeted: dict[str, int] = {}
    for number, pick in enumerate(all_picks, start=1):
        first_targeted.setdefault(pick.target_skill, number)
    everywhere = skills_in_every_problem(course)
    never = [s.id for s in course.skills if s.id not in first_targeted and s.id not in everywhere]
    first_picks = [batch[0] for batch in run.batches]
    return ScenarioResult(first_picks, first_targeted, never, _longest_run(first_picks))


def format_scenarios(course: Course, rounds: int) -> str:
    """The two scenarios as plain text."""
    names = {skill.id: skill.name for skill in course.skills}
    lines = [f"Scenario: a student who gets every step right ({rounds} batches)"]
    right = run_scenario(course, set(), rounds)
    for skill_id, number in sorted(right.first_targeted.items(), key=lambda item: item[1]):
        lines.append(f"  pick {number:>3}: first targets {names[skill_id]}")
    if right.never_targeted:
        lines.append("  never targeted: " + ", ".join(names[s] for s in right.never_targeted))
    lines.append("")
    lines.append(f"Scenario: a student who always gets one skill wrong ({rounds} batches)")
    lines.append(f"  {'Skill always wrong':<32}{'Same first pick':>16}{'Never targeted':>16}")
    everywhere = skills_in_every_problem(course)
    for skill in course.skills:
        if skill.id in everywhere:
            continue
        wrong = run_scenario(course, {skill.id}, rounds)
        lines.append(
            f"  {skill.name[:31]:<32}{wrong.longest_same_first_pick:>16}"
            f"{len(wrong.never_targeted):>16}"
        )
    lines.append("  (Same first pick: the longest run of batches that begin with one problem.)")
    return "\n".join(lines)


# The command.

DEFAULT_START = datetime.fromisoformat("2026-01-05T16:00:00+00:00")
DEFAULT_COURSE = (
    Path(__file__).resolve().parents[2] / "data" / "ap-physics-c-energy-momentum" / "course.json"
)
SCENARIO_ROUNDS = 40


def main(argv: list[str] | None = None) -> None:
    """Print the comparison and the scenarios."""
    parser = argparse.ArgumentParser(description="Compare the engine with simpler orders.")
    parser.add_argument("--students", type=int, default=50, help="students of each kind")
    parser.add_argument("--seed", type=int, default=1, help="the same seed repeats a run")
    parser.add_argument("--max-steps", type=int, default=600, help="steps per student")
    parser.add_argument("--course", default=str(DEFAULT_COURSE), help="a course.json file")
    args = parser.parse_args(argv)
    if args.students < 1 or args.max_steps < 1:
        parser.error("--students and --max-steps must be at least 1")
    course = load_course(args.course)
    print(f"Course {course.id}: {len(course.skills)} skills, {len(course.problems)} problems.")
    print(
        f"Each student answers up to {args.max_steps} steps, first tries only, no hints, "
        f"{PROBLEMS_PER_DAY} problems a day. Seed {args.seed}."
    )
    print("Finished: every skill truly known at the same time. Over-practice: share of")
    print("steps, before finishing, spent on a skill the student already knew.")
    print("Known @N: average true knowledge after N steps (only students who got that far).")
    print(f"Started in {NEW_SKILL_WINDOW}: skills begun in the first {NEW_SKILL_WINDOW} problems,")
    print("out of the skills not in every problem.")
    print("Repeats <24h: each simulated day starts at the same clock time, so yesterday's")
    print("problems are just under 24 hours old and the engine's 24-hour rule still blocks them.")
    print()
    results = compare(course, args.students, args.seed, args.max_steps)
    print(format_report(course, results))
    print(format_scenarios(course, SCENARIO_ROUNDS))


if __name__ == "__main__":
    main()
