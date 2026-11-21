"""Choose a student's next problems, each with a reason (PRD decision 4).

One main helper:

- next_problems(course, state, history, now, count=3): a list of up to `count`
  picks. Each pick names a problem, the skill it is meant to practice, and one plain
  sentence telling the student why it was picked.

Only a step's first try counts as evidence here, as in mastery.py: a second try says
little about what the student knew, and a first try made after reading a hint
counts as missed (research report, change 1).

The rules, most important first:

1. A new student (no answers yet) gets a short starting check: one problem per
   skill that needs nothing before it, then problems that cover more skills,
   easiest first.
2. Follow-up: if the student missed a step and has not got that skill right since,
   practice that skill again. If the skill builds on a skill that is not ready yet,
   practice that earlier skill instead, and say so.
   Stuck: if a skill has had many first tries and its number is still low, more of
   the same is not helping. Practice its weakest prerequisite that is not mastered
   instead, or, if there is none, the easiest problem for the skill (research
   report, change 6). This also applies to rule 3.
3. Skills the student is partway through (tried at least once, not mastered),
   weakest first.
4. Review: a mastered skill comes back after 1 day, then 3, 7, 14 and 30 days; a
   miss starts the gaps over (research report, change 5).
5. New skills: a skill never tried whose prerequisites are ready.

Throughout:

- A skill is "ready" only when every skill it builds on is known well enough. A
  skill that is not ready is not picked by rules 3 and 5. A course with no
  prerequisites at all switches this off.
- For each skill, prefer a problem the student should get about 70 to 85 percent of
  steps right on, closest to the middle, then the lower difficulty (research report,
  change 7).
- Each pick in a batch practices a different skill, up to three skills; two picks in
  a row never practice the same skill when the course allows. When problems are
  otherwise equal, prefer one whose first step has a different answer from the
  previous problem's, so that problem types are mixed (research report, change 3).
- No problem the student answered any step of in the last 24 hours.

When no problem fits a skill, the rules are loosened for that skill in this order:
any predicted success, then problems seen in the last 24 hours. Only after every
skill from rules 2 to 5 has been tried is the last rule loosened: any skill. The
list is never empty while the course has a problem with at least one step. No
randomness: ties go to whichever skill or problem comes first in the course file.

How to read this file: see the note at the top of models.py. Also,
`key=lambda x: ...` tells sorted(), min() or max() what to compare each item by.

Nothing here knows about algebra or physics, and nothing here touches the web
server or stored data.
"""

from datetime import datetime, timedelta

from pydantic import BaseModel

from practice_engine.mastery import (
    MASTERED,
    MASTERY_STREAK,
    START_MASTERY,
    chance_correct,
    is_mastered,
    new_mastery_state,
    update_mastery,
)
from practice_engine.models import Course, MasteryState, Problem, StepAnswer

# The numbers behind the rules, set by hand. T6's simulated students are where we test them.

# A skill is ready when every skill it builds on has at least this mastery: known
# well enough to build on, though not yet "mastered".
READY_MASTERY = 0.85
# The gaps, in days, before a mastered skill comes back for review. A right first try
# once the gap has passed moves to the next gap; the last gap repeats.
REVIEW_DAYS = (1, 3, 7, 14, 30)
# A skill with at least this many first tries ...
STUCK_STEPS = 8
# ... whose mastery is still below this counts as stuck.
STUCK_BELOW = 0.5
# A problem answered (any step of it) within this many hours is not picked again.
REPEAT_HOURS = 24
# The predicted share of steps right to aim for: from 70 to 85 percent.
TARGET_SUCCESS = (0.70, 0.85)
# A batch practices at most this many different skills.
MAX_BATCH_SKILLS = 3


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
    easiest: bool = False  # True: pick the easiest problem (stuck, nothing to step back to)


def next_problems(
    course: Course,
    state: MasteryState,
    history: list[StepAnswer],
    now: datetime,
    count: int = 3,
) -> list[Pick]:
    """Up to `count` next problems for the student, most important first.

    `history` is the step answers of this student (answers by other students are
    ignored), and `now` is the current date and time (passed in so that tests can
    choose it). A batch never goes past MAX_BATCH_SKILLS skills, so a `count` above
    that can give fewer picks once those skills run out of problems.
    Stops with a ValueError if the state is for a different course, or if the times
    mix ones with a time zone and ones without (they cannot be compared).
    """
    if state.course_id != course.id:
        raise ValueError(
            f"The mastery state for '{state.nickname}' is for course '{state.course_id}', "
            f"not '{course.id}'."
        )
    # Look-up table: (problem id, step position) -> the skill of that step.
    skill_of_step = {
        (problem.id, position): step.skill
        for problem in course.problems
        for position, step in enumerate(problem.steps, start=1)
    }
    # Keep only this student's answers to steps of this course.
    history = [
        answer
        for answer in history
        if answer.nickname == state.nickname
        and (answer.problem_id, answer.step_position) in skill_of_step
    ]
    # A time with a time zone cannot be compared with one without; say so plainly.
    if any((answer.answered_at.tzinfo is None) != (now.tzinfo is None) for answer in history):
        raise ValueError(
            "The answer times and the current time mix ones with a time zone and ones "
            "without, so they cannot be compared."
        )
    # Oldest first. sorted() keeps answers with the same time in the order they were given.
    history = sorted(history, key=lambda answer: answer.answered_at)
    if not history:
        return _starting_check(course, count)

    selector = _Selector(course, state, history, now, skill_of_step)
    picks: list[Pick] = []
    # Rules 2 to 5, most important first. Each skill gets its own loosening (any
    # predicted success, then problems seen in the last 24 hours, both built into
    # best_problem) before the next skill is tried, so a less important skill never
    # pushes a more important one out.
    targets = selector.follow_up() + selector.partway() + selector.reviews() + selector.new()
    for target in targets:
        if len(picks) >= count:
            return picks
        if not _skill_fits_batch(target.skill, picks):
            continue
        problem = selector.best_problem(target, picks)
        if problem is not None:
            picks.append(_make_pick(target, problem))
    # The last loosening: any skill, still one pick per skill.
    for target in selector.any_skill():
        if len(picks) >= count:
            return picks
        if not _skill_fits_batch(target.skill, picks):
            continue
        problem = selector.best_problem(target, picks)
        if problem is not None:
            picks.append(_make_pick(target, problem))
    # Still short (a course with few skills, or a large `count`): now a skill may fill
    # more than one place, as long as each problem appears only once and, when there
    # is a choice, two picks in a row practice different skills.
    while len(picks) < count:
        batch_skills = {pick.target_skill for pick in picks}
        options = []  # (target, problem) pairs that could fill the next place
        for target in selector.any_skill():
            if len(batch_skills) >= MAX_BATCH_SKILLS and target.skill not in batch_skills:
                continue  # the batch already has its three skills
            problem = selector.best_problem(target, picks)
            if problem is not None:
                options.append((target, problem))
        if not options:
            break  # every problem is already in the batch
        different = [option for option in options if option[0].skill != picks[-1].target_skill]
        target, problem = (different or options)[0]
        picks.append(_make_pick(target, problem))
    return picks


def _skill_fits_batch(skill_id: str, picks: list[Pick]) -> bool:
    """True if a first pick for `skill_id` may join the batch: the skill has no pick
    yet, and the batch has fewer than MAX_BATCH_SKILLS skills."""
    batch_skills = {pick.target_skill for pick in picks}
    return skill_id not in batch_skills and len(batch_skills) < MAX_BATCH_SKILLS


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
        self.state = state
        self.now = now
        self.skill_of_step = skill_of_step
        self.problem_by_id = {problem.id: problem for problem in course.problems}
        # A skill missing from the state counts as a new student's starting value.
        self.mastery = {
            skill.id: state.mastery.get(skill.id, START_MASTERY) for skill in course.skills
        }
        self.mastered = {
            skill.id: is_mastered(state, history, skill.id, course) for skill in course.skills
        }
        self.prerequisites_of = {skill.id: skill.prerequisites for skill in course.skills}
        # The ready rule switches off when no skill lists any prerequisite.
        self.uses_prerequisites = any(skill.prerequisites for skill in course.skills)
        # Only first tries are evidence, oldest first.
        self.first_tries = [answer for answer in history if answer.attempt == 1]
        # Look-up table: skill id -> the first tries on steps of that skill, oldest first.
        self.tries_of: dict[str, list[StepAnswer]] = {skill.id: [] for skill in course.skills}
        for answer in self.first_tries:
            self.tries_of[self.skill_of(answer)].append(answer)
        # Problems answered (any step, any try) within the last REPEAT_HOURS hours.
        since = now - timedelta(hours=REPEAT_HOURS)
        self.recent = {answer.problem_id for answer in history if answer.answered_at > since}
        # The problem answered last, for mixing problem types.
        self.last_problem = self.problem_by_id[history[-1].problem_id]

    def skill_of(self, answer: StepAnswer) -> str:
        """The skill of the step `answer` is for."""
        return self.skill_of_step[(answer.problem_id, answer.step_position)]

    def is_ready(self, skill_id: str) -> bool:
        """Every prerequisite is at READY_MASTERY or above (always true if switched off)."""
        if not self.uses_prerequisites:
            return True
        return all(self.mastery[p] >= READY_MASTERY for p in self.prerequisites_of[skill_id])

    def follow_up(self) -> list[_Target]:
        """Rule 2: the most recent missed first try whose skill has not been right since."""
        answered_right: set[str] = set()  # skills answered right after the miss
        for answer in reversed(self.first_tries):  # newest first
            skill = self.skill_of(answer)
            if _right(answer):
                answered_right.add(skill)
            elif skill not in answered_right:
                return [self._follow_up_target(answer, skill)]
        return []

    def _follow_up_target(self, answer: StepAnswer, missed_skill: str) -> _Target:
        missed = MissedStep(problem_id=answer.problem_id, step_position=answer.step_position)
        title = self.problem_by_id[answer.problem_id].title
        where = (
            f"you missed step {answer.step_position} of {title} "
            f"({_skill_name(self.course, missed_skill)})"
        )
        stuck = self._stuck_target(missed_skill)
        if stuck is not None:
            return _Target(
                skill=stuck.skill,
                reason=f"Picked for you: {where}. {stuck.reason}",
                missed_step=missed,
                easiest=stuck.easiest,
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

    def _stuck_target(self, skill_id: str) -> _Target | None:
        """The stuck rule: what to practice instead of `skill_id`, or None if not stuck."""
        stuck = len(self.tries_of[skill_id]) >= STUCK_STEPS and self.mastery[skill_id] < STUCK_BELOW
        if not stuck:
            return None
        name = _skill_name(self.course, skill_id)
        not_mastered = [p for p in self.prerequisites_of[skill_id] if not self.mastered[p]]
        if not_mastered:
            weakest = min(not_mastered, key=lambda p: self.mastery[p])  # first wins ties
            return _Target(
                skill=weakest,
                reason=(
                    f"{name} has been hard for a while, so this problem practices "
                    f"{_skill_name(self.course, weakest)}, which it builds on."
                ),
            )
        return _Target(
            skill=skill_id,
            reason=f"{name} has been hard for a while, so this is an easier problem on it.",
            easiest=True,
        )

    def partway(self) -> list[_Target]:
        """Rule 3: ready skills tried at least once and not mastered, weakest first."""
        skills = [
            skill.id
            for skill in self.course.skills
            if self.tries_of[skill.id] and not self.mastered[skill.id] and self.is_ready(skill.id)
        ]
        # sorted() keeps course order among skills with the same mastery.
        skills = sorted(skills, key=lambda skill_id: self.mastery[skill_id])
        targets = []
        for skill_id in skills:
            plain = _Target(
                skill=skill_id,
                reason=(
                    f"You are partway to mastering "
                    f"{_skill_name(self.course, skill_id)}, so this problem helps you finish it."
                ),
            )
            targets.append(self._stuck_target(skill_id) or plain)
        return targets

    def reviews(self) -> list[_Target]:
        """Rule 4: mastered skills whose review gap has passed, most overdue first."""
        due = []  # (how far past due, skill id, when it was mastered)
        for skill in self.course.skills:
            if not self.mastered[skill.id]:
                continue
            schedule = self._review_schedule(skill.id)
            if schedule is None:
                continue
            mastered_at, last_check, gap_days = schedule
            # Counted in calendar days, so "1 day" means any time the next day.
            overdue = (self.now.date() - last_check.date()).days - gap_days
            if overdue >= 0:
                due.append((overdue, skill.id, mastered_at))
        # Most overdue first; sorted() keeps course order among equal ones.
        due = sorted(due, key=lambda item: item[0], reverse=True)
        targets = []
        for _overdue, skill_id, mastered_at in due:
            days = (self.now.date() - mastered_at.date()).days
            ago = "1 day" if days == 1 else f"{days} days"
            targets.append(
                _Target(
                    skill=skill_id,
                    reason=(
                        f"Review: you mastered {_skill_name(self.course, skill_id)} {ago} ago; "
                        "a quick check keeps it fresh."
                    ),
                )
            )
        return targets

    def _review_schedule(
        self, skill_id: str, need_number: bool = True
    ) -> tuple[datetime, datetime, int] | None:
        """(when the skill was mastered, when it was last checked, the gap in days now).

        Walks the skill's first tries, oldest first, working its number out again with
        update_mastery (the engine keeps no record of past numbers). The skill counts
        as mastered at the first right first try after which the number is at least
        MASTERED and the last MASTERY_STREAK first tries were right. After that, a
        right first try once the current gap has passed is a review: it moves to the
        next gap. A right try before then does not, so the gaps only grow when the
        student remembered the skill across them (research report, change 5). A miss
        ends the mastery, so the gaps start over once it is earned again. None if the
        skill never counted as mastered.

        If the walk never reaches MASTERED (the state's number did not come from these
        answers), `need_number=False` tries again with the streak alone.
        """
        replay = new_mastery_state(self.course, self.state.nickname)
        mastered_at: datetime | None = None
        last_check = self.now
        gap = 0  # position in REVIEW_DAYS
        streak = 0
        for answer in self.tries_of[skill_id]:
            replay = update_mastery(replay, answer, self.course)
            if not _right(answer):
                streak = 0
                mastered_at = None
                continue
            streak += 1
            if mastered_at is None:
                high = replay.mastery[skill_id] >= MASTERED or not need_number
                if streak >= MASTERY_STREAK and high:
                    mastered_at = last_check = answer.answered_at
                    gap = 0
            elif (answer.answered_at.date() - last_check.date()).days >= REVIEW_DAYS[gap]:
                gap = min(gap + 1, len(REVIEW_DAYS) - 1)
                last_check = answer.answered_at
        if mastered_at is None:
            return self._review_schedule(skill_id, need_number=False) if need_number else None
        return mastered_at, last_check, REVIEW_DAYS[gap]

    def new(self) -> list[_Target]:
        """Rule 5: skills never tried whose prerequisites are ready, in course order."""
        return [
            _Target(
                skill=skill.id,
                reason=f"This problem starts you on {_skill_name(self.course, skill.id)}.",
            )
            for skill in self.course.skills
            if not self.tries_of[skill.id] and self.is_ready(skill.id)
        ]

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
            if self.tries_of[skill_id]:
                reason = f"More practice with {name}."
            else:
                reason = f"This problem starts you on {name}."
            targets.append(_Target(skill=skill_id, reason=reason))
        return targets

    def success(self, problem: Problem) -> float:
        """The predicted share of the problem's steps the student gets right first time."""
        chances = [chance_correct(self.state, step) for step in problem.steps]
        return sum(chances) / len(chances)

    def best_problem(self, target: _Target, picks: list[Pick]) -> Problem | None:
        """The best problem with a step on the target skill not already in `picks`, or None.

        The loosening order is built into the comparison (see _fit): a problem inside
        TARGET_SUCCESS beats one outside it, and any problem not answered in the last
        24 hours beats one that was. For a stuck target with nothing to step back to
        (`easiest`), the success target is not used: the lowest difficulty wins.
        """
        candidates = [
            problem
            for problem in self.course.problems
            if not any(pick.problem_id == problem.id for pick in picks)
            and any(step.skill == target.skill for step in problem.steps)
        ]
        if not candidates:
            return None
        previous = self.problem_by_id[picks[-1].problem_id] if picks else self.last_problem
        if target.easiest:
            return min(
                candidates, key=lambda problem: (problem.id in self.recent, problem.difficulty)
            )
        # min() keeps the first of equal problems, so course order breaks ties.
        return min(candidates, key=lambda problem: self._fit(problem, previous))

    def _fit(self, problem: Problem, previous: Problem) -> tuple:
        """How well a problem fits; smaller is better. Compared item by item:

        1. not answered in the last 24 hours first;
        2. inside TARGET_SUCCESS first;
        3. closest to the middle of the target;
        4. the lower difficulty;
        5. mixing: a first step whose answer differs from the previous problem's.
        """
        low, high = TARGET_SUCCESS
        success = self.success(problem)
        outside = not low <= success <= high
        distance = abs(success - (low + high) / 2)
        same_type = problem.steps[0].answer == previous.steps[0].answer
        return (problem.id in self.recent, outside, distance, problem.difficulty, same_type)


def _right(answer: StepAnswer) -> bool:
    """A first try counts as right only if it was right without any hint."""
    return answer.correct and answer.hints_used == 0


def _skill_name(course: Course, skill_id: str) -> str:
    """The skill's name as students see it."""
    for skill in course.skills:
        if skill.id == skill_id:
            return skill.name
    return skill_id
