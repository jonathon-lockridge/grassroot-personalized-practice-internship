"""Update a student's mastery after each step they answer (PRD decision 3).

The method is Bayesian Knowledge Tracing, a standard one. For each skill the engine
keeps one number from 0 to 1: how likely it thinks the student knows that skill.
After every step it does two things:

1. Ask "given this right or wrong answer, how likely is it now that they know it?"
   A right answer makes knowing more likely, unless it was easy to guess. A wrong
   answer makes it less likely, unless people who know it often slip anyway.
2. Allow for learning: doing the step may itself have taught them the skill.

Only a step's first try counts (research report, change 1): a second try says little
about what the student knew. A right first try made after reading a hint counts as
half a right answer (decided 2026-11-20): the student did some of the work, but not
alone. A wrong first try after a hint is an ordinary wrong answer.

Four main helpers:

- new_mastery_state(course, nickname): a new student's state, every skill at the
  starting value.
- update_mastery(state, answer, course): the state after one step answer. It gives
  back a new state and leaves the one passed in as it was.
- is_mastered(state, history, skill_id, course): True when a skill counts as
  mastered: a high number and a short streak of right first tries with no hint.
- chance_correct(state, step): how likely the student is to get a step right on the
  first try, for the next-problem rules.

And small shared ones, also used by selection.py and storage.py so the engine has
one version of each:

- has_mastery_streak(first_tries): the streak half of is_mastered, for a list of
  one skill's first tries that the caller already has.
- counts_as_right(answer): right with no hint. right_after_hint(answer): right, but
  after a hint.
- find_step(course, problem_id, step_position): one step, or a plain ValueError.
- step_table(course): a look-up table (problem id, step position) -> step, built once
  so a long history does not search the whole course for every answer.

Nothing here knows about algebra or physics, and nothing here touches the web
server or stored data.
"""

import math

from practice_engine.models import Course, MasteryState, Step, StepAnswer

# The fixed numbers behind the method. They are set by hand, not learned from data
# (PRD decision 3); T6's simulated students are where we test them. They were chosen
# so that, from the start, 4 to 6 right first tries in a row are needed to reach
# MASTERED, for every kind of step (research report, change 2).

# How likely we think a new student already knows a skill before any answer.
START_MASTERY = 0.1
# The chance that doing one step teaches the skill to a student who did not know it.
# Kept low so a few lucky steps cannot carry a student to "mastered". (At 0.1, the
# report's suggestion, a wrong first answer on a choice step would not lower a new
# student's number at all, so it is 0.05; T6 can tune it.)
LEARN_CHANCE = 0.05
# The chance that a student who knows the skill still answers wrong (a slip, such as
# a typo or a dropped minus sign).
SLIP_CHANCE = 0.15

# The chance that a student who does not know the skill still answers right (a guess).
# It depends on how the step is answered:
# - number: typing the exact number by pure luck is rare, but a student can still get
#   there without the skill (working back from a remembered answer, a half-right method
#   that lands close enough, help from a classmate), so it gets the lowest value allowed.
MIN_GUESS_CHANCE = 0.2
# - choice: 1 divided by the number of options, and
# - order: 1 divided by the number of possible orders (3 items: 1 in 6),
# but never below MIN_GUESS_CHANCE and never above this cap. So a 3-option choice
# (1 in 3) is lowered to 0.3, and a 2-option choice (1 in 2) is too; without the cap,
# a right answer on it would say almost nothing. Guess and
# slip must both stay below 0.5, or the method stops making sense.
MAX_GUESS_CHANCE = 0.3

# A wrong step answered faster than this looks like a guess, not a real attempt
# (PRD "Unusual cases"), so it moves mastery less.
FAST_ANSWER_SECONDS = 3
# The share of the usual change applied for such a fast wrong step: half.
FAST_WRONG_WEIGHT = 0.5

# A right first try made after reading a hint keeps this share of the change a right
# answer with no hint would make: half. So it raises mastery, but less.
HINT_CREDIT = 0.5

# A skill is mastered when its number is at least MASTERED ...
MASTERED = 0.95
# ... and the last MASTERY_STREAK first tries on it were right with no hint, a guard
# in case the numbers above are off (research report, change 2). A right first try
# after a hint is left out of the streak: it neither adds to it nor breaks it.
MASTERY_STREAK = 3


def new_mastery_state(course: Course, nickname: str) -> MasteryState:
    """A new student's state: one entry per skill of the course, at START_MASTERY."""
    return MasteryState(
        nickname=nickname,
        course_id=course.id,
        mastery={skill.id: START_MASTERY for skill in course.skills},
    )


def update_mastery(state: MasteryState, answer: StepAnswer, course: Course) -> MasteryState:
    """The student's state after one step answer.

    Stops with a plain message (a ValueError) if the state is for a different course,
    the answer names a problem or step the course does not have, belongs to a
    different student than the state, or if the state has no usable number (0 to 1)
    for the step's skill.
    The state passed in is not changed; a new one is given back.

    Only a first try (attempt 1) changes mastery; any later try gives back an equal
    copy. A right first try made after reading a hint keeps only HINT_CREDIT (half)
    of the rise a right answer with no hint would give; a wrong one after a hint is
    an ordinary wrong answer.
    """
    _check_course(state, course)
    if answer.nickname != state.nickname:
        raise ValueError(
            f"This answer is from '{answer.nickname}', but the mastery state is "
            f"for '{state.nickname}'."
        )
    step = find_step(course, answer.problem_id, answer.step_position)
    before = state.mastery.get(step.skill)
    # A missing skill or an impossible number means the state and the course do not
    # match; say so instead of guessing. (`not 0 <= before <= 1` also catches "nan",
    # a broken number that is neither above nor below anything.)
    if before is None or not 0 <= before <= 1:
        raise ValueError(
            f"The mastery state for '{state.nickname}' has no number from 0 to 1 for "
            f"skill '{step.skill}'."
        )
    if answer.attempt > 1:
        # A second or later try: the student has already seen they were wrong, so
        # this try says little about what they knew. Leave mastery as it was.
        return state.model_copy(deep=True)

    guess = _guess_chance(step)
    right = answer.correct  # a hinted right answer is worked out as right, then halved below

    # Part 1: Bayes' rule. Of all the ways this answer could have happened, which
    # share comes from a student who knows the skill?
    if right:
        # Knows it and did not slip, versus does not know it and guessed.
        knows = before * (1 - SLIP_CHANCE)
        does_not_know = (1 - before) * guess
    else:
        # Knows it but slipped, versus does not know it and did not guess.
        knows = before * SLIP_CHANCE
        does_not_know = (1 - before) * (1 - guess)
    after_answer = knows / (knows + does_not_know)

    # Part 2: learning. A student who did not know it may have learned it on this step.
    after = after_answer + (1 - after_answer) * LEARN_CHANCE

    # A really wrong answer given very fast looks like a guess: keep only part of the
    # change from `before`. A hinted answer is not a fast guess, so it is left out.
    wrong_without_hint = not answer.correct and answer.hints_used == 0
    if wrong_without_hint and answer.seconds < FAST_ANSWER_SECONDS:
        after = before + (after - before) * FAST_WRONG_WEIGHT

    # A right answer after a hint is partial credit: keep only part of the rise.
    if right_after_hint(answer):
        after = before + (after - before) * HINT_CREDIT

    if not right:
        # The learning part (Part 2) can lift a low number above where it started,
        # because different step kinds settle at different lowest values. A wrong
        # answer must never raise mastery, so keep the lower of the two.
        after = min(after, before)

    # Keep the number between 0 and 1, in case rounding in the arithmetic nudged it out.
    after = min(1.0, max(0.0, after))

    # Copy the table, then change only this skill, so the state passed in stays as it was.
    mastery = dict(state.mastery)
    mastery[step.skill] = after
    return MasteryState(nickname=state.nickname, course_id=state.course_id, mastery=mastery)


def is_mastered(
    state: MasteryState, history: list[StepAnswer], skill_id: str, course: Course
) -> bool:
    """True if the student counts as having mastered `skill_id`.

    Both must hold: the skill's number is at least MASTERED, and the student's last
    MASTERY_STREAK first tries on steps of that skill were right with no hint. A right
    first try after a hint is skipped: it neither counts toward the streak nor breaks
    it (a wrong one after a hint does break it). `history` is the student's step
    answers. Answers by other students, and answers to problems or steps no longer in
    the course (it may have been edited since), are ignored. A skill missing from the
    state counts as new (START_MASTERY).
    Stops with a ValueError if the state is for a different course, or if the answer
    times cannot be put in order (some with a time zone and some without).
    """
    _check_course(state, course)
    if state.mastery.get(skill_id, START_MASTERY) < MASTERED:
        return False
    try:
        by_time = sorted(history, key=lambda answer: answer.answered_at)
    except TypeError:
        raise ValueError(
            "The answer times mix ones with a time zone and ones without, so they "
            "cannot be put in order."
        ) from None
    steps = step_table(course)
    # The student's first tries on this skill, oldest first, leaving out right ones
    # made after a hint. A step no longer in the course gives None, so it is left out.
    first_tries = [
        answer
        for answer in by_time
        if answer.nickname == state.nickname
        and answer.attempt == 1
        and _skill_in(steps, answer) == skill_id
    ]
    return has_mastery_streak(first_tries)


def has_mastery_streak(first_tries: list[StepAnswer]) -> bool:
    """True if the newest MASTERY_STREAK of these first tries were right with no hint.

    `first_tries` is one student's first tries on one skill, oldest first. A right one
    after a hint is skipped: it neither counts toward the streak nor breaks it. This
    is the streak half of is_mastered, for callers that already have the list.
    """
    counted = [answer for answer in first_tries if not right_after_hint(answer)]
    last = counted[-MASTERY_STREAK:]  # the newest few (all of them if fewer)
    return len(last) == MASTERY_STREAK and all(counts_as_right(answer) for answer in last)


def chance_correct(state: MasteryState, step: Step, course: Course | None = None) -> float:
    """How likely the student is to get `step` right on the first try, from 0 to 1.

    Either they know the skill and do not slip, or they do not know it and guess:
    mastery x (1 - slip) + (1 - mastery) x guess. A skill missing from the state is
    treated as a new one (START_MASTERY). If `course` is given, it must be the
    state's course, or this stops with a ValueError.
    """
    if course is not None:
        _check_course(state, course)
    mastery = state.mastery.get(step.skill, START_MASTERY)
    return mastery * (1 - SLIP_CHANCE) + (1 - mastery) * _guess_chance(step)


def _check_course(state: MasteryState, course: Course) -> None:
    """Stop with a plain message if the state belongs to a different course."""
    if state.course_id != course.id:
        raise ValueError(
            f"The mastery state for '{state.nickname}' is for course '{state.course_id}', "
            f"not '{course.id}'."
        )


def counts_as_right(answer: StepAnswer) -> bool:
    """A step counts as right only if it was answered right without any hint."""
    return answer.correct and answer.hints_used == 0


def right_after_hint(answer: StepAnswer) -> bool:
    """True for a step answered right, but after reading a hint (partial credit)."""
    return answer.correct and answer.hints_used > 0


def find_step(course: Course, problem_id: str, step_position: int) -> Step:
    """The step at `step_position` (counting from 1) of the problem with `problem_id`.

    Stops with a plain message (a ValueError) if the course has no such problem or step.
    """
    for problem in course.problems:
        if problem.id == problem_id:
            if not 1 <= step_position <= len(problem.steps):
                raise ValueError(
                    f"Problem '{problem_id}' has steps 1 to {len(problem.steps)}, "
                    f"so there is no step {step_position}."
                )
            return problem.steps[step_position - 1]  # the list counts from 0
    raise ValueError(f"There is no problem '{problem_id}' in course '{course.id}'.")


def step_table(course: Course) -> dict[tuple[str, int], Step]:
    """Look-up table: (problem id, step position counting from 1) -> that step.

    Build it once and look steps up in it, instead of searching the course each time.
    It is built fresh from the course, so it always matches the course as it is now.
    """
    return {
        (problem.id, position): step
        for problem in course.problems
        for position, step in enumerate(problem.steps, start=1)
    }


def _skill_in(steps: dict[tuple[str, int], Step], answer: StepAnswer) -> str | None:
    """The skill of the step `answer` is for, or None if the table has no such step."""
    step = steps.get((answer.problem_id, answer.step_position))
    return step.skill if step is not None else None


def _guess_chance(step: Step) -> float:
    """How likely a student who does not know the skill gets this step right by luck."""
    if step.kind == "choice":
        # `or []` treats a missing options line as no options; max(..., 1) avoids
        # dividing by 0 (the course checker rejects such a step anyway).
        options = step.options or []
        chance = 1 / max(len(options), 1)
    elif step.kind == "order":
        # Items can be put in order in 1 x 2 x 3 x ... ways (math.factorial), and
        # only one is right.
        items = step.answer if isinstance(step.answer, list) else []
        chance = 1 / math.factorial(len(items))
    else:
        return MIN_GUESS_CHANCE  # a number step, the only kind left
    # Keep the chance between the lowest and highest values allowed.
    return min(MAX_GUESS_CHANCE, max(MIN_GUESS_CHANCE, chance))
