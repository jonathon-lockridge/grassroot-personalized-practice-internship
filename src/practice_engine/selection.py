"""Choose a student's next problems, each with a reason (PRD decision 4).

One main helper:

- next_problems(course, state, history, now, count=3): a list of up to `count`
  picks. Each pick names a problem, the skill it is meant to practice, and one plain
  sentence telling the student why it was picked.

The rules, most important first:

1. A new student (no answers yet) gets a short starting check: one problem per
   skill that needs nothing before it, then problems that cover more skills,
   easiest first.
2. Follow-up: if the student missed a step and has not got that skill right since,
   practice that skill again. If the skill builds on a skill that is not ready yet,
   practice that earlier skill instead, and say so.
3. Skills the student is partway through, weakest first.
4. A skill is "ready" only when every skill it builds on is known well enough. A
   skill that is not ready is not picked. A course with no prerequisites at all
   switches this rule off.
5. Skills mastered a while ago and not practiced since come back for a refresher.
6. For each skill, prefer problems at the student's level for that skill, then the
   level above.
7. Each pick in a batch practices a different skill, so a batch of three covers
   three skills when the course allows.
8. No problem the student answered any step of in the last 24 hours.

When no problem fits a skill, the rules are loosened for that skill in this order:
any difficulty, then problems seen in the last 24 hours. Only after every skill from
rules 2, 3 and 5 has been tried is the last rule loosened: any skill. The list is
never empty while the course has a problem with at least one step. No randomness:
ties go to whichever skill or problem comes first in the course file.

How to read this file: see the note at the top of models.py. Also,
`key=lambda x: ...` tells sorted(), min() or max() what to compare each item by.

Nothing here knows about algebra or physics, and nothing here touches the web
server or stored data.
"""

from datetime import datetime, timedelta

from pydantic import BaseModel

from practice_engine.mastery import START_MASTERY
from practice_engine.models import Course, MasteryState, Problem, StepAnswer

# The numbers behind the rules, set by hand. T6's simulated students are where we test them.

# A skill with mastery from PARTWAY_MASTERY up to (but not including) MASTERED is
# "partway through": started but not yet known well.
PARTWAY_MASTERY = 0.3
# At or above this, the engine counts a skill as mastered.
MASTERED = 0.85
# A skill is ready when every skill it builds on has at least this mastery.
READY_MASTERY = 0.6
# A mastered skill not practiced for this many days is fading and comes back.
FADING_DAYS = 7
# A problem answered (any step of it) within this many hours is not picked again.
REPEAT_HOURS = 24
# The student's level for a skill, from that skill's mastery: below EASY_BELOW the
# level is 1 (easy), below MEDIUM_BELOW it is 2 (medium), otherwise 3 (hard).
EASY_BELOW = 0.4
MEDIUM_BELOW = 0.7


class MissedStep(BaseModel):
    """The step a student got wrong that a follow-up pick answers to."""

    problem_id: str
    step_position: int  # counting from 1, like the rest of the engine


class Pick(BaseModel):
    """One next problem for the student, and why it was picked."""

    problem_id: str
    reason: str  # one plain sentence the student sees
    is_follow_up: bool  # True when picked because of a specific missed step
    target_skill: str  # the id of the skill this pick is meant to practice
    missed_step: MissedStep | None = None  # filled in only for a follow-up


class _Target(BaseModel):
    """A skill the engine wants practiced, with the reason to show if it is used."""

    skill: str
    reason: str
    missed_step: MissedStep | None = None


def next_problems(
    course: Course,
    state: MasteryState,
    history: list[StepAnswer],
    now: datetime,
    count: int = 3,
) -> list[Pick]:
    """Up to `count` next problems for the student, most important first.

    `history` is every step this one student has answered in this course (the caller
    must not mix in other students' answers), and `now` is
    the current date and time (passed in so that tests can choose it).
    """
    # Look-up table: (problem id, step position) -> the skill of that step.
    skill_of_step = {
        (problem.id, position): step.skill
        for problem in course.problems
        for position, step in enumerate(problem.steps, start=1)
    }
    # Keep only answers that match a step of this course, oldest first. sorted() keeps
    # answers with the same time in the order they were given.
    history = sorted(
        (
            answer
            for answer in history
            if (answer.problem_id, answer.step_position) in skill_of_step
        ),
        key=lambda answer: answer.answered_at,
    )
    if not history:
        return _starting_check(course, count)

    selector = _Selector(course, state, history, now, skill_of_step)
    picks: list[Pick] = []
    # Rules 2, 3 and 5, most important first. Each skill gets its own loosening (any
    # difficulty, then problems seen in the last 24 hours) before the next skill is
    # tried, so a less important skill never pushes a more important one out.
    for target in selector.follow_up() + selector.partway() + selector.fading():
        if len(picks) >= count:
            return picks
        if any(pick.target_skill == target.skill for pick in picks):
            continue  # rule 7: this skill already has a pick in the batch
        # `or` moves on to the next, looser try only when the one before found nothing.
        problem = (
            selector.best_problem(target.skill, picks, keep_difficulty=True, keep_no_repeats=True)
            or selector.best_problem(
                target.skill, picks, keep_difficulty=False, keep_no_repeats=True
            )
            or selector.best_problem(
                target.skill, picks, keep_difficulty=False, keep_no_repeats=False
            )
        )
        if problem is not None:
            picks.append(_make_pick(target, problem))
    # The last loosening: any skill, still one pick per skill.
    for target in selector.any_skill():
        if len(picks) >= count:
            return picks
        if any(pick.target_skill == target.skill for pick in picks):
            continue
        problem = selector.best_problem(
            target.skill, picks, keep_difficulty=False, keep_no_repeats=False
        )
        if problem is not None:
            picks.append(_make_pick(target, problem))
    # Still short (a course with fewer skills than `count`): now a skill may fill more
    # than one place, as long as each problem appears only once.
    for target in selector.any_skill():
        while len(picks) < count:
            problem = selector.best_problem(
                target.skill, picks, keep_difficulty=False, keep_no_repeats=False
            )
            if problem is None:
                break  # this skill has no problems left; try the next skill
            picks.append(_make_pick(target, problem))
    return picks


def _make_pick(target: _Target, problem: Problem) -> Pick:
    """Turn a wanted skill and the problem found for it into a pick."""
    return Pick(
        problem_id=problem.id,
        reason=target.reason,
        is_follow_up=target.missed_step is not None,
        target_skill=target.skill,
        missed_step=target.missed_step,
    )


def _starting_check(course: Course, count: int) -> list[Pick]:
    """Rule 1: a short set for a new student, covering as many skills as it can.

    Each round takes the problem that covers the most not-yet-covered skills with
    no prerequisites, then the easiest, then the one that covers the most other new
    skills, then the first in the course file. It stops at `count` problems, or when
    no problem adds a skill.
    """
    starting_skills = {skill.id for skill in course.skills if not skill.prerequisites}
    covered: set[str] = set()
    picks: list[Pick] = []
    while len(picks) < count:
        best: Problem | None = None
        best_score: tuple = ()
        for problem in course.problems:
            if any(pick.problem_id == problem.id for pick in picks):
                continue
            new_skills = {step.skill for step in problem.steps} - covered
            # Python compares these tuples item by item, so the first item matters most.
            # A minus sign turns "smaller is better" into "bigger is better".
            score = (len(new_skills & starting_skills), -problem.difficulty, len(new_skills))
            if new_skills and (best is None or score > best_score):
                best, best_score = problem, score
        if best is None:
            break  # no problem adds a skill: the check is done
        # The skill this pick checks: the first new one in the problem, preferring a
        # starting skill.
        new_in_order = [step.skill for step in best.steps if step.skill not in covered]
        first_starting = [skill for skill in new_in_order if skill in starting_skills]
        target = (first_starting or new_in_order)[0]
        covered |= set(new_in_order)  # |= adds these skills to the covered set
        picks.append(
            Pick(
                problem_id=best.id,
                reason=(
                    "Starting check: you are new here, so this problem shows what you "
                    f"already know about {_skill_name(course, target)}."
                ),
                is_follow_up=False,
                target_skill=target,
            )
        )
    return picks


class _Selector:
    """What the rules need to know about one student, worked out once.

    A class bundles these facts with the helpers that use them, so each helper can
    read them as `self.something` instead of being handed them one by one.
    """

    def __init__(
        self,
        course: Course,
        state: MasteryState,
        history: list[StepAnswer],
        now: datetime,
        skill_of_step: dict[tuple[str, int], str],
    ) -> None:
        self.course = course
        self.history = history  # only this course's answers, oldest first
        self.now = now
        self.skill_of_step = skill_of_step
        # A skill missing from the state counts as a new student's starting value.
        self.mastery = {
            skill.id: state.mastery.get(skill.id, START_MASTERY) for skill in course.skills
        }
        self.prerequisites_of = {skill.id: skill.prerequisites for skill in course.skills}
        # Rule 4 switches off when no skill lists any prerequisite.
        self.uses_prerequisites = any(skill.prerequisites for skill in course.skills)
        # Problems answered (any step) within the last REPEAT_HOURS hours.
        since = now - timedelta(hours=REPEAT_HOURS)
        self.recent = {answer.problem_id for answer in history if answer.answered_at > since}
        # Look-up table: skill id -> when a step of that skill was last answered.
        # Later answers overwrite earlier ones, so the latest time is kept.
        self.last_practiced = {
            skill_of_step[(answer.problem_id, answer.step_position)]: answer.answered_at
            for answer in history
        }

    def is_ready(self, skill_id: str) -> bool:
        """Rule 4: every prerequisite is at READY_MASTERY or above (always true if off)."""
        if not self.uses_prerequisites:
            return True
        return all(self.mastery[p] >= READY_MASTERY for p in self.prerequisites_of[skill_id])

    def follow_up(self) -> list[_Target]:
        """Rule 2: the most recent missed step whose skill has not been answered right since."""
        answered_right: set[str] = set()  # skills answered right after the miss
        for answer in reversed(self.history):  # newest first
            skill = self.skill_of_step[(answer.problem_id, answer.step_position)]
            if answer.correct:
                answered_right.add(skill)
            elif skill not in answered_right:
                return [self._follow_up_target(answer, skill)]
        return []

    def _follow_up_target(self, answer: StepAnswer, missed_skill: str) -> _Target:
        missed = MissedStep(problem_id=answer.problem_id, step_position=answer.step_position)
        where = (
            f"you missed step {answer.step_position} of {answer.problem_id} "
            f"({_skill_name(self.course, missed_skill)})"
        )
        # If the missed skill is not ready, step down to its weakest unready prerequisite,
        # and again if that one is not ready either. `seen` stops a broken course with a
        # loop of prerequisites from going round forever.
        target = missed_skill
        seen = {target}
        while not self.is_ready(target):
            unready = [p for p in self.prerequisites_of[target] if self.mastery[p] < READY_MASTERY]
            weakest = min(unready, key=lambda p: self.mastery[p])  # first in the list wins ties
            if weakest in seen:
                break
            target = weakest
            seen.add(target)
        if target == missed_skill:
            reason = f"Picked for you: {where}, so this problem practices that skill again."
        else:
            reason = (
                f"Picked for you: {where}, which builds on "
                f"{_skill_name(self.course, target)}, so this problem practices that first."
            )
        return _Target(skill=target, reason=reason, missed_step=missed)

    def partway(self) -> list[_Target]:
        """Rule 3: ready skills partway to mastery, weakest first."""
        skills = [
            skill.id
            for skill in self.course.skills
            if PARTWAY_MASTERY <= self.mastery[skill.id] < MASTERED and self.is_ready(skill.id)
        ]
        # sorted() keeps course order among skills with the same mastery.
        skills = sorted(skills, key=lambda skill_id: self.mastery[skill_id])
        return [
            _Target(
                skill=skill_id,
                reason=(
                    f"You are partway to mastering "
                    f"{_skill_name(self.course, skill_id)}, so this problem helps you finish it."
                ),
            )
            for skill_id in skills
        ]

    def fading(self) -> list[_Target]:
        """Rule 5: mastered skills not practiced for FADING_DAYS days, longest-ago first."""
        cutoff = self.now - timedelta(days=FADING_DAYS)
        skills = [
            skill.id
            for skill in self.course.skills
            if self.mastery[skill.id] >= MASTERED
            and skill.id in self.last_practiced
            and self.last_practiced[skill.id] <= cutoff
            and self.is_ready(skill.id)
        ]
        skills = sorted(skills, key=lambda skill_id: self.last_practiced[skill_id])
        targets = []
        for skill_id in skills:
            days = (self.now - self.last_practiced[skill_id]).days
            targets.append(
                _Target(
                    skill=skill_id,
                    reason=(
                        f"You mastered {_skill_name(self.course, skill_id)} "
                        f"but have not practiced it in {days} days, so this is a refresher."
                    ),
                )
            )
        return targets

    def any_skill(self) -> list[_Target]:
        """The last loosening: every skill, ready ones first, then weakest first."""
        # Sort by "not ready" (False comes before True), then by mastery.
        skills = sorted(
            (skill.id for skill in self.course.skills),
            key=lambda skill_id: (not self.is_ready(skill_id), self.mastery[skill_id]),
        )
        targets = []
        for skill_id in skills:
            name = _skill_name(self.course, skill_id)
            if skill_id in self.last_practiced:
                reason = f"More practice with {name}."
            else:
                reason = f"This problem starts you on {name}, which you have not tried yet."
            targets.append(_Target(skill=skill_id, reason=reason))
        return targets

    def best_problem(
        self, skill_id: str, picks: list[Pick], keep_difficulty: bool, keep_no_repeats: bool
    ) -> Problem | None:
        """The best problem with a step on `skill_id` not already in `picks`, or None.

        Best means: not answered in the last 24 hours, then closest to the student's
        level (the level itself, then one above, then the rest by distance), then
        first in the course file. `keep_difficulty` allows only the level and the one
        above (rule 6); `keep_no_repeats` leaves out recent problems (rule 8).
        """
        level = self.level(skill_id)
        candidates = []
        for problem in self.course.problems:
            if any(pick.problem_id == problem.id for pick in picks):
                continue
            if all(step.skill != skill_id for step in problem.steps):
                continue  # this problem does not practice the skill
            if keep_difficulty and problem.difficulty not in (level, level + 1):
                continue
            if keep_no_repeats and problem.id in self.recent:
                continue
            candidates.append(problem)
        if not candidates:
            return None
        # min() keeps the first of equal problems, so course order breaks ties.
        return min(
            candidates,
            key=lambda problem: (problem.id in self.recent, _closeness(problem.difficulty, level)),
        )

    def level(self, skill_id: str) -> int:
        """Rule 6: the student's level for a skill, 1 easy to 3 hard."""
        if self.mastery[skill_id] < EASY_BELOW:
            return 1
        if self.mastery[skill_id] < MEDIUM_BELOW:
            return 2
        return 3


def _closeness(difficulty: int, level: int) -> int:
    """0 for the student's level, 1 for one above, then 2, 3, ... further away."""
    if difficulty == level:
        return 0
    if difficulty == level + 1:
        return 1
    return 1 + abs(difficulty - level)


def _skill_name(course: Course, skill_id: str) -> str:
    """The skill's name as students see it."""
    for skill in course.skills:
        if skill.id == skill_id:
            return skill.name
    return skill_id
