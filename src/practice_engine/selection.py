"""Choose a student's next problems, each with a reason (PRD decision 4).

One main helper:

- next_problems(course, state, history, now, count=3, focus=None): a list of up to
  `count` picks. Each pick names a problem, the skill it is meant to practice, one plain
  sentence telling the student why it was picked, and `rule`: a short fixed word
  saying which rule below made the pick (one of PICK_RULES), for checking and
  counting the engine's choices, and `challenge`: "solid" or "stretch" (see "Solid
  and stretch" below), so the page can show how hard a pick is predicted to be.
- next_problem(course, state, history, now, focus): the one next problem for a
  student practicing one lesson (`focus` is its skills), or None when the lesson has
  nothing left for today. See "Practicing one lesson" below.

Only a step's first try counts as evidence here, as in mastery.py: a second try says
little about what the student knew (research report, change 1). A wrong first try
after a hint is a miss. A right first try after a hint gets half credit in mastery.py,
but here it brings the skill back like a miss (decided 2026-11-22): needing a hint
shows the skill is still shaky.

The rules, most important first:

1. A new student (no answers yet) gets a short starting check: one problem per
   skill that needs nothing before it, then problems that cover more skills,
   easiest first. (rule "starting_check")
2. Follow-up: each skill the student missed (or needed a hint on) goes on a watch
   list, and is practiced again in every batch, newest miss first, until it is right
   on the first try, with no hint, in WATCH_CLEAR_RIGHTS (2) different problems after
   the latest miss, at least one of them WATCH_LATER_HOURS (12) or more after the
   miss; a new miss starts that count over (Stanford review, 2026-11-22; later-session
   rule, 2026-11-26).
   One right answer is weak evidence, as a choice step can be guessed. Two rights in
   the same problem count once, and the problem of the miss itself does not count:
   a later step of it, minutes after the feedback, shows short-term memory. If the
   skill builds on a skill that is not ready yet, practice that earlier skill
   instead, and say so. If the missed
   step's skill is in every problem (see "Throughout"), practice the skill rule 3 or
   5 would pick first instead, and say so; this comes after the other follow-ups, so
   it never takes a skill that has a follow-up of its own. (rule "follow_up")
   Stuck: if a skill has had many first tries and its number is still low, more of
   the same is not helping. Practice its weakest prerequisite that is not mastered
   instead, or, if there is none, the easiest problem for the skill (research
   report, change 6). This also applies to rule 3. (rule "stuck"; a stuck follow-up
   is still a follow-up, so its is_follow_up stays True)
3. Skills the student is partway through (tried at least once, not mastered),
   weakest first. (rule "partway")
4. Review: a mastered skill comes back after 1 day, then 3, 7, 14 and 30 days; a
   miss starts the gaps over (research report, change 5). (rule "review")
5. New skills: a skill never tried whose prerequisites are ready. (rule "new_skill")

Mixing, so a batch always moves forward (decided 2026-11-22):

- Follow-ups never fill the whole batch. With 2 or more picks, at least one is not a
  follow-up, preferring a new skill, then a review, then a partway skill. With 3 or
  more picks, at most MAX_FOLLOW_UPS are follow-ups.
- With 3 or more picks, one of them starts a new skill whenever one is ready, so new
  ideas keep coming even while old ones are being fixed.

Throughout:

- A skill used by every problem of the course (such as a "which idea fits?" first
  step) gets practiced whatever is picked, so no problem is ever picked because of
  it: no rule targets it. Its mastery is still tracked as usual. This only applies
  when the course has more than one problem and at least one other skill.
- A skill is "ready" only when every skill it builds on is known well enough. A
  skill that is not ready is not picked by rules 3 and 5. A course with no
  prerequisites at all switches this off.
- Not too hard: a problem the student is predicted to get less than SUCCESS_FLOOR
  (50 percent) of steps right on never beats one at or above it (review board,
  2026-11-22): mostly-wrong practice is discouraging and teaches little.
- Solid and stretch (decided 2026-11-26): in a batch of 2 or more, the first pick is
  "solid" and the rest are "stretch"; a batch of 1 is stretch. A stretch problem is
  chosen by "most left to learn" below. A solid problem skips that and goes straight
  to the 70 to 85 percent target, closest to the middle (left to learn only breaks
  ties). Why both: harder practice that the student mostly gets right teaches more
  (Bjork, desirable difficulties), but learning is fastest at about 85 percent right
  (Wilson and others, 2019), and a success soon after a miss, or early in a new skill,
  helps the skill stick and keeps the student going. Why the first place: it is the
  most important pick (often a follow-up after a miss, or a new skill), and the
  session starts with a success. The starting check and a stuck skill's easiest
  problem also look for solid, as they are chosen easiest first. A pick says "solid"
  only if the problem found is predicted at least 70 percent right; otherwise it says
  "stretch", even in the first place (review board, 2026-11-26): the 24-hour, unseen
  and floor rules come first, so often no problem inside the target is left, and a
  new student's starting check is predicted about 30 percent right.
  What it costs, against all-stretch: in 20 simulated students, the solid place picks
  a different problem about 1 time in 8 (in the rest the two orders agree), and about
  2 in 3 first places end up saying "solid". In T6 (seeds 1, 7 and 11), for
  students who need prerequisites first, the same number finish and known share is
  at most 0.01 lower, but the median steps to finish rise (418 to 444, 425 to 431,
  386 to 388). BKT-like students are slower too: median steps 305 to 315, 279 to 299,
  278 to 305, and known share at 200 steps falls by 0.01 to 0.02, so on seeds 1 and
  11 it goes from level with or ahead of Expert to just behind it (0.82 and 0.83
  against 0.84);
  they still finish more often than Expert and Random (48 of 50 against 41 and 36 or
  fewer). A rule-based split, solid for new skills and follow-ups, finished 3 to 5
  fewer students who need prerequisites first, so it was dropped.
- Most left to learn: for each skill, prefer the problem with the most the student
  probably still has to learn, the average over its steps of 1 minus the skill's
  number (see left_to_learn), so fewer steps go on skills they already know (T6
  tuning, 2026-11-22; the goal is learning per minute of practice). A problem padded
  with steps on known skills wastes the student's time, even though those easy
  steps raise its predicted share of steps right. A step on a skill that is not
  ready counts as nothing left to learn, so a problem full of skills the student
  cannot do yet does not win this way.
- Then, among problems with the same left to learn, prefer one the student should
  get about 70 to 85 percent of steps right on, closest to the middle, then the
  lower difficulty (research report, change 7). When no problem is inside that range
  (mostly for a new student), the lower difficulty comes first, then the closest to
  the range (decided 2026-11-20): the predicted share can make a hard problem full
  of guessable choice steps look easier than an easy one.
- Unseen first: for each skill, a problem the student has never answered any step of
  beats one they have seen, even one inside the 70 to 85 percent range, because a
  seen problem's predicted share leaves out what the student remembers of it, and
  practice works best when the student must recall the skill, not an answer
  (Stanford review, 2026-11-22). This comes before "not too hard" and "most left to
  learn". For a stuck
  skill's easiest problem, the lowest difficulty still comes first and unseen only
  breaks ties; left to learn is not used there.
- Each pick in a batch practices a different skill, up to three skills; two picks in
  a row never practice the same skill when the course allows. When problems are
  otherwise equal, prefer one whose first step has a different answer from the
  previous problem's, so that problem types are mixed (research report, change 3).
- Mixing topics, only ever as a tiebreak: when a rule ranks two skills the same (say,
  two new skills, or two partway skills at the same number), or two problems fit
  equally well, prefer the one that shares no "family" with the previous problem.
  A skill's family is the skills with no prerequisites that it builds on (see
  skill_families), so it comes from the prerequisites alone. A course with no
  prerequisites has no families, and this does nothing (Rohrer and Taylor,
  interleaving; Stanford review, 2026-11-22).
- No problem the student answered any step of in the last 24 hours.

Practicing one lesson (`focus`, decided 2026-11-26): after a lesson, practice is
mostly on that lesson's skills, but not only, so earlier skills are not forgotten.
next_problem gives one problem at a time, in this order: a follow-up for a missed step
from any lesson; then, after LESSON_RUN problems in a row only on the lesson, a review
or partway skill from outside it (so about 1 problem in 4 or more practices an earlier
skill, since many problems already mix one in; never a new skill, as it has not been
taught yet); then the lesson's new skills, its weakest partway skill, its reviews,
and any of its skills. The lesson's skills count as ready (it has just taught them),
but a miss still steps down to a weak prerequisite, and skills outside the lesson keep
the usual readiness rule. A follow-up already right once since its miss stops jumping
the queue until WATCH_LATER_HOURS after the miss, when a right answer can clear it;
more follow-ups minutes later are massed practice. A problem answered in the last
REPEAT_HOURS hours is never offered: when nothing fresh is left on the lesson, it is
done for today, instead of drifting into other lessons. next_problems with `focus`
puts the lesson's skills first within each rule, for a batch.

When no problem fits a skill, the rules are loosened for that skill in this order:
any predicted success (first below the 70 to 85 percent target, then below
SUCCESS_FLOOR), then problems seen before, then problems seen in the last 24 hours
(see _fit). Only after every skill from rules 2 to 5 has been tried is the last rule
loosened: any skill (rule "relaxed", also used when a skill fills a second place in
the batch). Loosening inside one skill keeps that skill's rule. The list is never
empty while the course has a problem with at least one step. No randomness:
remaining ties go to whichever skill or problem comes first in the course file.

How to read this file: see the note at the top of models.py. Also,
`key=lambda x: ...` tells sorted(), min() or max() what to compare each item by.

Nothing here knows about algebra or physics, and nothing here touches the web
server or stored data.
"""

from datetime import UTC, datetime, timedelta
from typing import Literal, get_args

from pydantic import BaseModel

from practice_engine.mastery import (
    MASTERED,
    MASTERY_STREAK,
    START_MASTERY,
    chance_correct,
    counts_as_right,
    has_mastery_streak,
    new_mastery_state,
    right_after_hint,
    step_table,
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
# A problem the student is predicted to get less than this share of right never beats
# one at or above it, however much it has left to learn: mostly-wrong practice is
# discouraging and teaches little (PRD decision 4).
SUCCESS_FLOOR = 0.5
# A batch practices at most this many different skills.
MAX_BATCH_SKILLS = 3
# A batch of 3 or more has at most this many follow-ups, so there is room for
# something new. (A batch of 2 has at most 1, and a batch of 1 is just the follow-up.)
MAX_FOLLOW_UPS = 2
# A skill missed (or needing a hint) stays on the watch list, and so keeps getting
# follow-ups, until it is right on the first try, with no hint, in this many different
# problems after the latest miss. One right answer is weak evidence: a choice step can
# be guessed 20 to 30 percent of the time.
WATCH_CLEAR_RIGHTS = 2
# ...and at least one of those right answers must come this many hours or more after
# the miss, so in a later study session: remembering a skill a day later shows it was
# learned, while getting it right minutes after the feedback may be short-term memory
# (decided 2026-11-26).
WATCH_LATER_HOURS = 12
# When practicing one lesson, after this many problems in a row only on the lesson, the
# next is a review from outside it, if one is due: about 1 in 4 (decided 2026-11-26).
LESSON_RUN = 3

# The rule that made a pick, one short fixed word each (see the list at the top).
# `Literal` means a Pick may hold only one of these words; any other is refused.
Rule = Literal["starting_check", "follow_up", "stuck", "partway", "review", "new_skill", "relaxed"]
PICK_RULES: tuple[str, ...] = get_args(Rule)  # the same words, as a tuple, for counting

# How hard a pick is (see "Solid and stretch" at the top): "solid" aims at
# TARGET_SUCCESS and says so only if it gets there; "stretch" aims at the most left to
# learn above SUCCESS_FLOOR.
Challenge = Literal["solid", "stretch"]
CHALLENGES: tuple[str, ...] = get_args(Challenge)  # the same words, as a tuple


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
    rule: Rule  # which rule made this pick, one of PICK_RULES
    challenge: Challenge  # "solid" (predicted at least 70% right) or "stretch"
    missed_step: MissedStep | None = None  # filled in only for a follow-up


class _Target(BaseModel):
    """A skill the engine wants practiced, with the reason to show if it is used."""

    skill: str
    reason: str
    rule: Rule
    missed_step: MissedStep | None = None
    easiest: bool = False  # True: pick the easiest problem (stuck, nothing to step back to)
    # What the rule sorted this target by. Targets with the same rank are tied, so the
    # mixing tiebreak may choose between them. None: never tied with another target.
    rank: tuple | None = None


def next_problems(
    course: Course,
    state: MasteryState,
    history: list[StepAnswer],
    now: datetime,
    count: int = 3,
    focus: set[str] | None = None,
) -> list[Pick]:
    """Up to `count` next problems for the student, most important first.

    `focus`, if given, is the skills of the lesson being practiced: they go first
    within each rule (see "Practicing one lesson" at the top).

    `history` is the step answers of this student (answers by other students are
    ignored), and `now` is the current date and time (passed in so that tests can
    choose it). A batch never goes past MAX_BATCH_SKILLS skills, so a `count` above
    that can give fewer picks once those skills run out of problems.
    Stops with a ValueError if the state is for a different course, or if the times
    mix ones with a time zone and ones without (they cannot be compared).
    """
    history, skill_of_step = _own_history(course, state, history, now)
    focus = focus or None  # an empty set means no lesson: the whole course
    if not history:
        return _starting_check(course, state, count, focus)

    selector = _Selector(course, state, history, now, skill_of_step, focus)
    return _fill_batch(selector, count)


def _own_history(
    course: Course, state: MasteryState, history: list[StepAnswer], now: datetime
) -> tuple[list[StepAnswer], dict[tuple[str, int], str]]:
    """This student's answers to steps of this course, oldest first, and a look-up
    table (problem id, step position) -> the skill of that step. Stops with a
    ValueError if the state is for another course or the times cannot be compared."""
    if state.course_id != course.id:
        raise ValueError(
            f"The mastery state for '{state.nickname}' is for course '{state.course_id}', "
            f"not '{course.id}'."
        )
    # Look-up table: (problem id, step position) -> the skill of that step.
    skill_of_step = {place: step.skill for place, step in step_table(course).items()}
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
    return sorted(history, key=lambda answer: answer.answered_at), skill_of_step


def _fill_batch(selector: "_Selector", count: int) -> list[Pick]:
    """Rules 2 to 5 and the mixing rules, for a student with answers (see the top)."""
    picks: list[Pick] = []
    # Each skill gets its own loosening (built into best_problem; see _fit for the
    # order) before the next skill is tried, so a less important skill never pushes a
    # more important one out.

    # Rule 2: the follow-ups, but never the whole batch.
    max_follow_ups = 1 if count <= 2 else MAX_FOLLOW_UPS
    follow_ups = selector.follow_ups()
    _add_picks(selector, picks, follow_ups, limit=min(count, max_follow_ups), count=count)

    # The mixing place: one pick kept for a new skill (batches of 3 or more) or, after a
    # follow-up, for any other skill (new, then review, then partway). It must not be a
    # skill that is waiting for a follow-up itself.
    partway, reviews, new = selector.partway(), selector.reviews(), selector.new()
    waiting = {target.skill for target in follow_ups}
    groups: list[list[_Target]] = []  # the candidates for the mixing place, best group first
    if count >= 3 or (picks and count >= 2):
        groups.append(selector.focus_first(new))
    if picks and count >= 2:
        groups.append(selector.focus_first([t for t in reviews if t.skill not in waiting]))
        groups.append(selector.focus_first([t for t in partway if t.skill not in waiting]))
    mixing = [target for group in groups for target in group]
    # The place is for the best group that has any skill in it.
    wanted = next(({target.skill for target in group} for group in groups if group), set())

    # Rules 3 to 5, leaving the last place free for mixing if it is still needed.
    places = min(count, MAX_BATCH_SKILLS)  # each pick here is for a skill of its own
    rest = selector.focus_first(partway + reviews + new)
    if mixing:
        _add_picks(selector, picks, rest, limit=places - 1, count=count)
        if not any(not pick.is_follow_up and pick.target_skill in wanted for pick in picks):
            _add_picks(selector, picks, mixing, limit=len(picks) + 1, count=count)
    _add_picks(selector, picks, rest, limit=count, count=count)
    # The last loosening: any skill, still one pick per skill.
    _add_picks(
        selector, picks, selector.focus_first(selector.any_skill()), limit=count, count=count
    )
    # Still short (a course with few skills, or a large `count`): now a skill may fill
    # more than one place, as long as each problem appears only once and, when there
    # is a choice, two picks in a row practice different skills.
    while len(picks) < count:
        batch_skills = {pick.target_skill for pick in picks}
        options = []  # (target, problem) pairs that could fill the next place
        for target in selector.focus_first(selector.any_skill()):
            if len(batch_skills) >= MAX_BATCH_SKILLS and target.skill not in batch_skills:
                continue  # the batch already has its three skills
            challenge = _challenge(target, picks, count)
            problem = selector.best_problem(target, picks, challenge)
            if problem is not None:
                options.append((target, problem, challenge))
        if not options:
            break  # every problem is already in the batch
        different = [option for option in options if option[0].skill != picks[-1].target_skill]
        target, problem, challenge = (different or options)[0]
        share = selector.success(problem)
        picks.append(_make_pick(target, problem, challenge, share))  # any_skill: "relaxed"
    return picks


def _add_picks(
    selector: "_Selector",
    picks: list[Pick],
    targets: list["_Target"],
    limit: int,
    count: int,
) -> None:
    """Add a pick for each target in turn, until `picks` has `limit` picks. A target is
    skipped when its skill is already in the batch, the batch has its MAX_BATCH_SKILLS
    skills, or no problem fits. `count` is the size of the whole batch, which decides
    whether a place is solid or stretch (see _challenge).

    Mixing topics, a tiebreak only: among the next target and any others its rule
    ranked the same (see _Target.rank), one whose family the previous problem does
    not share goes first.
    """
    waiting = list(targets)
    while waiting and len(picks) < limit:
        first = waiting[0]
        tied = [first]
        if first.rank is not None:
            tied = [target for target in waiting if target.rank == first.rank]
        previous = selector.previous_problem(picks)
        # sorted() keeps the rule's own order among targets that share a family or not.
        tied = sorted(tied, key=lambda target: selector.shares_family(target.skill, previous))
        for target in tied:
            # A target that cannot be picked now never can later in this batch (the
            # batch only fills up), so it is dropped.
            waiting.remove(target)
            if not _skill_fits_batch(target.skill, picks):
                continue
            challenge = _challenge(target, picks, count)
            problem = selector.best_problem(target, picks, challenge)
            if problem is not None:
                picks.append(_make_pick(target, problem, challenge, selector.success(problem)))
                break  # the others stay waiting, to be compared with this new pick


def _skill_fits_batch(skill_id: str, picks: list[Pick]) -> bool:
    """True if a first pick for `skill_id` may join the batch: the skill has no pick
    yet, and the batch has fewer than MAX_BATCH_SKILLS skills."""
    batch_skills = {pick.target_skill for pick in picks}
    return skill_id not in batch_skills and len(batch_skills) < MAX_BATCH_SKILLS


def _challenge(target: _Target, picks: list[Pick], count: int) -> Challenge:
    """Whether the next place in a batch of `count` looks for a solid or a stretch
    problem: solid for the first place of a batch of 2 or more, stretch for the rest. A
    stuck skill's easiest problem looks for solid wherever it is, since it is chosen
    easiest first (see best_problem). What the pick finally says is decided after the
    problem is found (see _label)."""
    if target.easiest:
        return "solid"
    return "solid" if count >= 2 and not picks else "stretch"


def _label(challenge: Challenge, share: float) -> Challenge:
    """What a pick tells the student about how hard it is. A place that looked for a
    solid problem says "solid" only if the problem found is predicted at least the low
    end of TARGET_SUCCESS right (`share`); otherwise it says "stretch". Often no problem
    inside the target is left (the 24-hour, unseen and floor rules come first), and a
    problem the student would get 30 percent right must not be shown as a gentle one
    (review board, 2026-11-26)."""
    return "solid" if challenge == "solid" and share >= TARGET_SUCCESS[0] else "stretch"


def _make_pick(target: _Target, problem: Problem, challenge: Challenge, share: float) -> Pick:
    """Turn a wanted skill and the problem found for it into a pick. `challenge` is
    what the place looked for and `share` the problem's predicted share right; the pick
    says what _label makes of the two."""
    return Pick(
        problem_id=problem.id,
        reason=target.reason,
        is_follow_up=target.missed_step is not None,
        target_skill=target.skill,
        rule=target.rule,
        challenge=_label(challenge, share),
        missed_step=target.missed_step,
    )


def next_problem(
    course: Course,
    state: MasteryState,
    history: list[StepAnswer],
    now: datetime,
    focus: set[str] | None = None,
) -> Pick | None:
    """The one next problem for a student practicing one lesson, whose skills are
    `focus` (None: the whole course), or None when nothing fresh is left today (see
    "Practicing one lesson" at the top). Never a problem answered in the last
    REPEAT_HOURS hours. Stops with a ValueError as next_problems does."""
    history, skill_of_step = _own_history(course, state, history, now)
    if focus is not None:
        # A lesson of only skills used everywhere keeps them; otherwise they go.
        focus = set(focus) - _skills_in_every_problem(course) or set(focus)
    if not history:
        picks = _starting_check(course, state, 1, focus)
        return picks[0] if picks else None
    selector = _Selector(course, state, history, now, skill_of_step, focus)

    def on_lesson(target: _Target) -> bool:
        return focus is None or target.skill in focus

    def first_fresh(targets: list[_Target]) -> Pick | None:
        """A pick for the first target with a problem not answered in the last day. A
        follow-up or a stuck skill's easiest problem looks for solid (a success soon
        after a miss helps it stick); the rest look for stretch."""
        for target in targets:
            challenge: Challenge = "solid" if target.missed_step or target.easiest else "stretch"
            problem = selector.best_problem(target, [], challenge, exclude=selector.recent)
            if problem is not None:
                return _make_pick(target, problem, challenge, selector.success(problem))
        return None

    # 1. A follow-up, from any lesson: a missed step comes first.
    pick = first_fresh(selector.follow_ups())
    if pick is not None:
        return pick
    # 2. After LESSON_RUN lesson problems in a row, a review or partway skill from
    #    outside the lesson, never a new one: the student has not been taught it yet.
    if focus is not None and _lesson_run(course, history, focus) >= LESSON_RUN:
        outside = [t for t in selector.reviews() + selector.partway() if not on_lesson(t)]
        pick = first_fresh(outside)
        if pick is not None:
            return pick
    # 3. The lesson: its new skills first, so the whole lesson gets started, then the
    #    weakest partway skill, then reviews, then any of its skills at all.
    lesson = [t for t in selector.new() + selector.partway() + selector.reviews() if on_lesson(t)]
    lesson += [t for t in selector.any_skill() if on_lesson(t)]
    # Nothing fresh on the lesson: done for today, rather than drifting into other lessons.
    return first_fresh(lesson)


def _lesson_run(course: Course, history: list[StepAnswer], focus: set[str]) -> int:
    """How many of the student's latest problems in a row were only on `focus`: every
    step on a lesson skill (or a skill used everywhere). A problem that also has a step
    on an earlier skill already practiced that skill, so it ends the run."""
    everywhere = _skills_in_every_problem(course)
    skills_of = {
        problem.id: {step.skill for step in problem.steps} - everywhere
        for problem in course.problems
    }
    latest_first: list[str] = []  # problem ids, most recently answered first, once each
    for answer in sorted(history, key=lambda answer: answer.answered_at, reverse=True):
        if answer.problem_id in skills_of and answer.problem_id not in latest_first:
            latest_first.append(answer.problem_id)
    run = 0
    for problem_id in latest_first:
        if not skills_of[problem_id] <= focus:
            break
        run += 1
    return run


def _starting_check(
    course: Course, state: MasteryState, count: int, focus: set[str] | None = None
) -> list[Pick]:
    """Rule 1: a short set for a new student, covering as many skills as it can.

    Each round takes the problem that covers the most not-yet-covered skills with
    no prerequisites, then the easiest, then the one that covers the most other new
    skills, then the first in the course file. It stops at `count` problems, or when
    no problem adds a skill. Each pick looks for solid (easiest first), but says solid
    only if `state` predicts it at least the low end of TARGET_SUCCESS right (see
    _label); for a brand-new student that is rarely so.

    With `focus` (a lesson's skills), only problems with a step on the lesson count,
    and only the lesson's skills are covered: the check is on what was just taught.
    """
    starting_skills = {skill.id for skill in course.skills if not skill.prerequisites}
    # A skill in every problem gets checked anyway, so it counts as covered from the start.
    covered: set[str] = _skills_in_every_problem(course)
    if focus:
        starting_skills &= focus
        # Skills outside the lesson count as covered, so only the lesson's are sought.
        covered |= {skill.id for skill in course.skills if skill.id not in focus}
        if focus <= covered:
            covered -= focus  # a lesson of only "everywhere" skills: check those
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
                rule="starting_check",
                challenge=_label("solid", _predicted_share(state, best)),
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
        focus: set[str] | None = None,
    ) -> None:
        self.course = course
        self.focus = focus  # the skills of the lesson being practiced, or None
        self.state = state
        self.now = now
        self.skill_of_step = skill_of_step
        self.problem_by_id = {problem.id: problem for problem in course.problems}
        # A skill missing from the state counts as a new student's starting value.
        self.mastery = {
            skill.id: state.mastery.get(skill.id, START_MASTERY) for skill in course.skills
        }
        self.prerequisites_of = {skill.id: skill.prerequisites for skill in course.skills}
        # Skills practiced by every problem: tracked, but never a reason to pick a problem.
        self.everywhere = _skills_in_every_problem(course)
        # The ready rule switches off when no skill lists any prerequisite.
        self.uses_prerequisites = any(skill.prerequisites for skill in course.skills)
        # Only first tries are evidence, oldest first.
        self.first_tries = [answer for answer in history if answer.attempt == 1]
        # Look-up table: skill id -> the first tries on steps of that skill, oldest first.
        self.tries_of: dict[str, list[StepAnswer]] = {skill.id: [] for skill in course.skills}
        for answer in self.first_tries:
            self.tries_of[self.skill_of(answer)].append(answer)
        # The same test as mastery.is_mastered (a high number and a streak), worked out
        # from the lists just built instead of searching the whole history per skill.
        self.mastered = {
            skill.id: self.mastery[skill.id] >= MASTERED
            and has_mastery_streak(self.tries_of[skill.id])
            for skill in course.skills
        }
        # Problems answered (any step, any try) within the last REPEAT_HOURS hours.
        since = now - timedelta(hours=REPEAT_HOURS)
        self.recent = {answer.problem_id for answer in history if answer.answered_at > since}
        # Problems answered ever (any step, any try): "seen", for the unseen-first rule.
        self.seen = {answer.problem_id for answer in history}
        # The problem answered last, for mixing problem types.
        self.last_problem = self.problem_by_id[history[-1].problem_id]
        # Skill id -> its family, for mixing unrelated topics (see skill_families).
        self.families = skill_families(course)
        # Problem id -> every family its skills belong to, worked out once.
        self.families_of_problem = {
            problem.id: set().union(*(self.families[step.skill] for step in problem.steps))
            for problem in course.problems
        }

    def focus_first(self, targets: list["_Target"]) -> list["_Target"]:
        """With a lesson being practiced, its skills first, keeping each side's order.
        The lesson also goes into each target's rank, so the mixing tiebreak in
        _add_picks never puts a skill outside the lesson ahead of one inside it."""
        if self.focus is None:
            return targets
        marked = [
            target
            if target.rank is None
            else target.model_copy(update={"rank": (target.skill not in self.focus, *target.rank)})
            for target in targets
        ]
        return sorted(marked, key=lambda target: target.skill not in self.focus)

    def resting(self, miss: StepAnswer, rights_since: int) -> bool:
        """Practicing one lesson: a watched skill already right once since its miss
        stops jumping the queue as a follow-up until WATCH_LATER_HOURS after the miss,
        when a right answer can clear it. It can still come as an ordinary lesson skill."""
        if self.focus is None or rights_since < 1:
            return False
        later = miss.answered_at.astimezone(UTC) + timedelta(hours=WATCH_LATER_HOURS)
        return self.now.astimezone(UTC) < later

    def previous_problem(self, picks: list[Pick]) -> Problem:
        """The problem just before the next place: the batch's last pick, or else the
        problem the student answered last."""
        return self.problem_by_id[picks[-1].problem_id] if picks else self.last_problem

    def shares_family(self, skill_id: str, problem: Problem) -> bool:
        """True if the skill belongs to a family the problem's skills belong to."""
        return bool(self.families[skill_id] & self.families_of_problem[problem.id])

    def skill_of(self, answer: StepAnswer) -> str:
        """The skill of the step `answer` is for."""
        return self.skill_of_step[(answer.problem_id, answer.step_position)]

    def can_start(self, skill_id: str) -> bool:
        """Ready, or taught by the lesson being practiced: a lesson has just taught its
        skills, so they are practiced even before everything they build on is known well.
        A miss still steps down to a weak prerequisite (see _follow_up_target)."""
        return (self.focus is not None and skill_id in self.focus) or self.is_ready(skill_id)

    def is_ready(self, skill_id: str) -> bool:
        """Every prerequisite is at READY_MASTERY or above (always true if switched off)."""
        if not self.uses_prerequisites:
            return True
        return all(self.mastery[p] >= READY_MASTERY for p in self.prerequisites_of[skill_id])

    def watch_list(self) -> list[tuple[StepAnswer, int]]:
        """The skills on the watch list, newest miss first: for each, its latest first
        try that was missed or needed a hint, and in how many different problems it has
        been right (first try, no hint) since. A skill leaves the list once that number
        reaches WATCH_CLEAR_RIGHTS and at least one of those rights came
        WATCH_LATER_HOURS or more after the miss."""
        watched = []
        for skill in self.course.skills:
            tries = self.tries_of[skill.id]
            # The position of the latest miss (or hint) in this skill's first tries.
            misses = [i for i, answer in enumerate(tries) if not counts_as_right(answer)]
            if not misses:
                continue
            latest = misses[-1]
            # Each problem counts once, however many of its steps were right. The problem
            # of the miss itself does not count: a later step of it, minutes after the
            # miss and its feedback, shows short-term memory, not that the skill was kept.
            right_in = {answer.problem_id for answer in tries[latest + 1 :]}
            right_in.discard(tries[latest].problem_id)
            # At least one right answer must come in a later session, not minutes later.
            # Times are compared in UTC so a clock change does not shift the 12 hours.
            later = tries[latest].answered_at.astimezone(UTC) + timedelta(hours=WATCH_LATER_HOURS)
            right_later = any(
                answer.answered_at.astimezone(UTC) >= later
                for answer in tries[latest + 1 :]
                if answer.problem_id in right_in
            )
            if len(right_in) < WATCH_CLEAR_RIGHTS or not right_later:
                watched.append((tries[latest], len(right_in)))
        # Newest miss first. sorted() keeps course order for misses at the same time.
        return sorted(watched, key=lambda item: item[0].answered_at, reverse=True)

    def follow_ups(self) -> list[_Target]:
        """Rule 2: one target per skill on the watch list, newest miss first."""
        watched = self.watch_list()
        # A skill in every problem goes last, so its follow-up (on another skill) never
        # takes the place of that other skill's own follow-up. sorted() keeps newest first.
        watched = sorted(watched, key=lambda item: self.skill_of(item[0]) in self.everywhere)
        targets: list[_Target] = []
        for answer, rights_since in watched:
            if self.resting(answer, rights_since):
                continue
            taken = {target.skill for target in targets}
            target = self._follow_up_target(answer, self.skill_of(answer), taken, rights_since)
            # Two misses can lead to the same skill (say, a shared prerequisite): keep one.
            if target is not None and target.skill not in taken:
                targets.append(target)
        return targets

    def _follow_up_target(
        self, answer: StepAnswer, missed_skill: str, taken: set[str], rights_since: int = 0
    ) -> _Target | None:
        """The follow-up for one missed (or hinted) step. `taken` is the skills earlier
        follow-ups already target; `rights_since` is how many different problems the
        skill has been right in since (see watch_list)."""
        missed = MissedStep(problem_id=answer.problem_id, step_position=answer.step_position)
        title = self.problem_by_id[answer.problem_id].title
        what = "needed a hint on" if right_after_hint(answer) else "missed"
        where = (
            f"you {what} step {answer.step_position} of {title} "
            f"({_skill_name(self.course, missed_skill)})"
        )
        if missed_skill in self.everywhere:
            # Every problem practices this skill anyway, so work on another one: the
            # first that rule 3 (weakest first) or rule 5 would pick and that no other
            # follow-up has.
            others = [t for t in self.partway() + self.new() if t.skill not in taken]
            if not others:
                return None
            other = others[0]
            name = _skill_name(self.course, missed_skill)
            if right_after_hint(answer):
                practice = f"you needed a hint on {name}, so you'll practice it again here"
            else:
                practice = f"you'll practice {name} again here"
            return _Target(
                skill=other.skill,
                reason=(
                    f"Picked for you: {practice}, and this problem also works on "
                    f"{_skill_name(self.course, other.skill)}."
                ),
                # The other skill's own rule may be the stuck rule; then that is what
                # chose the problem.
                rule="stuck" if other.rule == "stuck" else "follow_up",
                missed_step=missed,
                easiest=other.easiest,
            )
        stuck = self._stuck_target(missed_skill)
        if stuck is not None:
            return _Target(
                skill=stuck.skill,
                reason=f"Picked for you: {where}. {stuck.reason}",
                rule="stuck",
                missed_step=missed,
                easiest=stuck.easiest,
            )
        # If the missed skill is not ready, step down to its weakest unready prerequisite,
        # and again if that one is not ready either. A skill in every problem is never
        # stepped down to. `seen` stops a broken course with a loop of prerequisites
        # from going round forever.
        target = missed_skill
        seen = {target}
        while not self.is_ready(target):
            unready = [
                p
                for p in self.prerequisites_of[target]
                if self.mastery[p] < READY_MASTERY and p not in self.everywhere
            ]
            if not unready:
                break
            weakest = min(unready, key=lambda p: self.mastery[p])  # first in the list wins ties
            if weakest in seen:
                break
            target = weakest
            seen.add(target)
        if target == missed_skill and rights_since:
            # Tell the student why a skill they just got right is back.
            if rights_since == 1:
                reason = (
                    f"Picked for you: {where} and have got it right once since, "
                    "so this problem checks it again."
                )
            else:
                reason = (
                    f"Picked for you: {where} and have got it right in {rights_since} "
                    "problems since, so this problem checks that you still know it today."
                )
        elif target == missed_skill:
            reason = f"Picked for you: {where}, so this problem practices that skill again."
        else:
            reason = (
                f"Picked for you: {where}, which builds on "
                f"{_skill_name(self.course, target)}, so this problem practices that first."
            )
        return _Target(skill=target, reason=reason, rule="follow_up", missed_step=missed)

    def _stuck_target(self, skill_id: str) -> _Target | None:
        """The stuck rule: what to practice instead of `skill_id`, or None if not stuck."""
        stuck = len(self.tries_of[skill_id]) >= STUCK_STEPS and self.mastery[skill_id] < STUCK_BELOW
        if not stuck:
            return None
        name = _skill_name(self.course, skill_id)
        not_mastered = [
            p
            for p in self.prerequisites_of[skill_id]
            if not self.mastered[p] and p not in self.everywhere
        ]
        if not_mastered:
            weakest = min(not_mastered, key=lambda p: self.mastery[p])  # first wins ties
            return _Target(
                skill=weakest,
                reason=(
                    f"{name} has been hard for a while, so this problem practices "
                    f"{_skill_name(self.course, weakest)}, which it builds on."
                ),
                rule="stuck",
            )
        return _Target(
            skill=skill_id,
            reason=f"{name} has been hard for a while, so this is an easier problem on it.",
            rule="stuck",
            easiest=True,
        )

    def partway(self) -> list[_Target]:
        """Rule 3: ready skills tried at least once and not mastered, weakest first."""
        skills = [
            skill.id
            for skill in self.course.skills
            if self.tries_of[skill.id]
            and not self.mastered[skill.id]
            and self.can_start(skill.id)
            and skill.id not in self.everywhere
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
                rule="partway",
            )
            target = self._stuck_target(skill_id) or plain
            target.rank = ("partway", self.mastery[skill_id])
            targets.append(target)
        return targets

    def reviews(self) -> list[_Target]:
        """Rule 4: mastered skills whose review gap has passed, most overdue first."""
        due = []  # (how far past due, skill id, when it was mastered)
        for skill in self.course.skills:
            if not self.mastered[skill.id] or skill.id in self.everywhere:
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
        for overdue, skill_id, mastered_at in due:
            days = (self.now.date() - mastered_at.date()).days
            ago = "1 day" if days == 1 else f"{days} days"
            targets.append(
                _Target(
                    skill=skill_id,
                    reason=(
                        f"Review: you mastered {_skill_name(self.course, skill_id)} {ago} ago; "
                        "a quick check keeps it fresh."
                    ),
                    rule="review",
                    rank=("review", overdue),
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
            if right_after_hint(answer):
                continue  # skipped, as in is_mastered: neither builds nor breaks the streak
            if not counts_as_right(answer):
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
                rule="new_skill",
                rank=("new_skill",),  # new ready skills are all equal: any may go first
            )
            for skill in self.course.skills
            if not self.tries_of[skill.id]
            and self.can_start(skill.id)
            and skill.id not in self.everywhere
        ]

    def any_skill(self) -> list[_Target]:
        """The last loosening: every skill, ready ones first, then weakest first."""
        # Sort by "not ready" (False comes before True), then by mastery.
        skills = sorted(
            (skill.id for skill in self.course.skills if skill.id not in self.everywhere),
            key=lambda skill_id: (not self.can_start(skill_id), self.mastery[skill_id]),
        )
        targets = []
        for skill_id in skills:
            name = _skill_name(self.course, skill_id)
            if self.tries_of[skill_id]:
                reason = f"More practice with {name}."
            else:
                reason = f"This problem starts you on {name}."
            rank = ("relaxed", not self.can_start(skill_id), self.mastery[skill_id])
            targets.append(_Target(skill=skill_id, reason=reason, rule="relaxed", rank=rank))
        return targets

    def success(self, problem: Problem) -> float:
        """The predicted share of the problem's steps the student gets right first time."""
        return _predicted_share(self.state, problem)

    def left_to_learn(self, problem: Problem, target_skill: str) -> float:
        """How much of the problem the student most likely can learn now: for each step,
        1 minus the mastery of its skill, averaged over the steps. A step on a skill that
        is not ready (and is not the target skill) counts as 0: the student cannot yet
        build it, so it is not learning time but a step they will most likely get wrong.
        A skill in every problem is left out (every problem has it, so it tells problems
        nothing apart), unless the problem has nothing else."""
        steps = [step for step in problem.steps if step.skill not in self.everywhere]
        steps = steps or problem.steps
        left = sum(
            1 - self.mastery[step.skill]
            for step in steps
            if step.skill == target_skill or self.can_start(step.skill)
        ) / len(steps)
        # Rounded, so two problems whose numbers differ only by computer rounding
        # still count as a tie and the later items decide.
        return round(left, 6)

    def best_problem(
        self,
        target: _Target,
        picks: list[Pick],
        challenge: Challenge = "stretch",
        exclude: set[str] | frozenset[str] = frozenset(),
    ) -> Problem | None:
        """The best problem with a step on the target skill not already in `picks`, or None.

        The loosening order is built into the comparison (see _fit): any problem not
        answered in the last 24 hours beats one that was, any problem never seen beats
        one seen before, one at or above SUCCESS_FLOOR beats one below it, and then the
        most left to learn wins, before TARGET_SUCCESS. For a "solid" `challenge`,
        TARGET_SUCCESS comes before the most left to learn instead.
        For a stuck target with nothing to step back to (`easiest`), the success target
        is not used: the lowest difficulty wins, then an unseen problem. Problem ids in
        `exclude` are never chosen.
        """
        candidates = [
            problem
            for problem in self.course.problems
            if problem.id not in exclude
            and not any(pick.problem_id == problem.id for pick in picks)
            and any(step.skill == target.skill for step in problem.steps)
        ]
        if not candidates:
            return None
        previous = self.previous_problem(picks)
        if target.easiest:
            return min(
                candidates,
                key=lambda problem: (
                    problem.id in self.recent,
                    problem.difficulty,
                    problem.id in self.seen,
                ),
            )
        # min() keeps the first of equal problems, so course order breaks ties.
        return min(
            candidates, key=lambda problem: self._fit(problem, previous, target.skill, challenge)
        )

    def _fit(
        self, problem: Problem, previous: Problem, target_skill: str, challenge: Challenge
    ) -> tuple:
        """How well a problem fits; smaller is better. Compared item by item:

        1. not answered in the last 24 hours first;
        2. never seen (no step of it ever answered) first: practice on a new problem
           makes the student recall the skill, not the answer they remember. This comes
           before the success target, because the predicted share of a seen problem
           leaves out what the student remembers of it, so "inside the target" is not
           trustworthy there;
        3. predicted share right at or above SUCCESS_FLOOR first, so a problem the
           student would get mostly wrong never wins while a gentler one is there;
        4. the most left to learn (see left_to_learn): fewer steps on skills the
           student already knows, and none on skills not ready yet. For steps that
           type in a number, more left to learn always means a lower predicted share,
           so items 5 to 7 mostly decide between problems that differ in their choice
           or order steps;
        5. inside TARGET_SUCCESS first;
        6. only for a problem outside TARGET_SUCCESS: the lower difficulty, since the
           predicted share is a weak guide there (a hard problem with many guessable
           choice steps can look easier than an easy one);
        7. closest to the middle of the target;
        8. the lower difficulty;
        9. mixing: a first step whose answer differs from the previous problem's;
        10. mixing topics: a problem whose skills share no family with the previous
            problem's (see skill_families).

        For a "solid" `challenge`, item 4 moves to just after item 8, so the 70 to 85
        percent target decides first and left to learn only breaks ties.
        """
        low, high = TARGET_SUCCESS
        success = self.success(problem)
        outside = not low <= success <= high
        # 0 for every problem inside the target, so this item only sorts the ones outside.
        difficulty_if_outside = problem.difficulty if outside else 0
        distance = abs(success - (low + high) / 2)
        same_type = problem.steps[0].answer == previous.steps[0].answer
        same_family = bool(
            self.families_of_problem[problem.id] & self.families_of_problem[previous.id]
        )
        left = -self.left_to_learn(problem, target_skill)
        if challenge == "solid":
            return (
                problem.id in self.recent,
                problem.id in self.seen,
                success < SUCCESS_FLOOR,
                outside,
                difficulty_if_outside,
                distance,
                problem.difficulty,
                left,
                same_type,
                same_family,
            )
        return (
            problem.id in self.recent,
            problem.id in self.seen,
            success < SUCCESS_FLOOR,
            left,  # the minus sign: more left to learn first
            outside,
            difficulty_if_outside,
            distance,
            problem.difficulty,
            same_type,
            same_family,
        )


def _predicted_share(state: MasteryState, problem: Problem) -> float:
    """The predicted share of the problem's steps the student gets right first time."""
    chances = [chance_correct(state, step) for step in problem.steps]
    return sum(chances) / len(chances)


def _skills_in_every_problem(course: Course) -> set[str]:
    """The skills that every problem of the course has a step on.

    Empty when the course has one problem or none (then "every problem" means
    nothing special), or when these are all the skills the problems use (leaving
    them out would leave nothing to pick).
    """
    if len(course.problems) < 2:
        return set()
    skill_sets = [{step.skill for step in problem.steps} for problem in course.problems]
    everywhere = set.intersection(*skill_sets)  # the skills found in every set
    all_used = set.union(*skill_sets)  # the skills found in any set
    return everywhere if everywhere != all_used else set()


def skill_families(course: Course) -> dict[str, set[str]]:
    """Skill id -> its family: the skills with no prerequisites that it builds on,
    directly or through other skills (a skill with none is its own family).

    Worked out from the prerequisites alone, so it knows nothing about the subject.
    A skill in every problem belongs to no family and is no other skill's root (it is
    practiced whatever is picked). Every family is empty when no skill lists any
    prerequisite: then there is nothing to tell topics apart by, and the mixing
    tiebreak does nothing.
    """
    if not any(skill.prerequisites for skill in course.skills):
        return {skill.id: set() for skill in course.skills}
    everywhere = _skills_in_every_problem(course)
    prerequisites_of = {skill.id: skill.prerequisites for skill in course.skills}

    def roots(skill_id: str, seen: set[str]) -> set[str]:
        # `seen` stops a broken course with a loop of prerequisites from going round forever.
        below = [p for p in prerequisites_of.get(skill_id, []) if p not in everywhere | seen]
        if not below:
            return {skill_id}
        found: set[str] = set()
        for p in below:
            found |= roots(p, seen | {skill_id})
        return found

    return {
        skill.id: set() if skill.id in everywhere else roots(skill.id, set())
        for skill in course.skills
    }


def _skill_name(course: Course, skill_id: str) -> str:
    """The skill's name as students see it."""
    for skill in course.skills:
        if skill.id == skill_id:
            return skill.name
    return skill_id
