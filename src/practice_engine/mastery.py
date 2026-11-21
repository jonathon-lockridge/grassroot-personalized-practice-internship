"""Update a student's mastery after each step they answer (PRD decision 3).

The method is Bayesian Knowledge Tracing, a standard one. For each skill the engine
keeps one number from 0 to 1: how likely it thinks the student knows that skill.
After every step it does two things:

1. Ask "given this right or wrong answer, how likely is it now that they know it?"
   A right answer makes knowing more likely, unless it was easy to guess. A wrong
   answer makes it less likely, unless people who know it often slip anyway.
2. Allow for learning: doing the step may itself have taught them the skill.

Two helpers:

- new_mastery_state(course, nickname): a new student's state, every skill at the
  starting value.
- update_mastery(state, answer, course): the state after one step answer. It gives
  back a new state and leaves the one passed in as it was.

Nothing here knows about algebra or physics, and nothing here touches the web
server or stored data.
"""

import math

from practice_engine.models import Course, MasteryState, Step, StepAnswer

# The fixed numbers behind the method. They are set by hand, not learned from data
# (PRD decision 3); T6's simulated students are where we test them.

# How likely we think a new student already knows a skill before any answer.
# 0.2 is a common textbook default: most students have seen some of it, few know it well.
START_MASTERY = 0.2
# The chance that doing one step teaches the skill to a student who did not know it.
# 0.15 is a middle value; published fits for school math are often between 0.05 and 0.3.
LEARN_CHANCE = 0.15
# The chance that a student who knows the skill still answers wrong (a slip, such as
# a typo or a dropped minus sign). 0.1 is the usual default.
SLIP_CHANCE = 0.1

# The chance that a student who does not know the skill still answers right (a guess).
# It depends on how the step is answered:
# - number: typing the right number by luck is rare.
NUMBER_GUESS_CHANCE = 0.05
# - choice: 1 divided by the number of options (3 options: 1 in 3, which the cap
#   below lowers to 0.3), and
# - order: 1 divided by the number of possible orders (3 items: 1 in 6),
# but never above this cap. Without it, a 2-option choice (1 in 2) would make a right
# answer say almost nothing; 0.3 is the usual upper limit for guessing in this method.
MAX_GUESS_CHANCE = 0.3

# A wrong step answered faster than this looks like a guess, not a real attempt
# (PRD "Unusual cases"), so it moves mastery less.
FAST_ANSWER_SECONDS = 3
# The share of the usual change applied for such a fast wrong step: half.
FAST_WRONG_WEIGHT = 0.5


def new_mastery_state(course: Course, nickname: str) -> MasteryState:
    """A new student's state: one entry per skill of the course, at START_MASTERY."""
    return MasteryState(
        nickname=nickname,
        mastery={skill.id: START_MASTERY for skill in course.skills},
    )


def update_mastery(state: MasteryState, answer: StepAnswer, course: Course) -> MasteryState:
    """The student's state after one step answer.

    Stops with a plain message (a ValueError) if the answer names a problem or step
    the course does not have, belongs to a different student than the state, or
    if the state has no usable number (0 to 1) for the step's skill.
    The state passed in is not changed; a new one is given back.

    Hints used are recorded in the answer but do not change the update for now.
    """
    if answer.nickname != state.nickname:
        raise ValueError(
            f"This answer is from '{answer.nickname}', but the mastery state is "
            f"for '{state.nickname}'."
        )
    step = _find_step(course, answer.problem_id, answer.step_position)
    before = state.mastery.get(step.skill)
    # A missing skill or an impossible number means the state and the course do not
    # match; say so instead of guessing. (`not 0 <= before <= 1` also catches "nan",
    # a broken number that is neither above nor below anything.)
    if before is None or not 0 <= before <= 1:
        raise ValueError(
            f"The mastery state for '{state.nickname}' has no number from 0 to 1 for "
            f"skill '{step.skill}'."
        )
    guess = _guess_chance(step)

    # Part 1: Bayes' rule. Of all the ways this answer could have happened, which
    # share comes from a student who knows the skill?
    if answer.correct:
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

    if not answer.correct and answer.seconds < FAST_ANSWER_SECONDS:
        # Looks like a guess: keep only part of the change from `before`.
        after = before + (after - before) * FAST_WRONG_WEIGHT

    if not answer.correct:
        # The learning part (Part 2) can lift a low number above where it started,
        # because different step kinds settle at different lowest values. A wrong
        # answer must never raise mastery, so keep the lower of the two.
        after = min(after, before)

    # Keep the number between 0 and 1, in case rounding in the arithmetic nudged it out.
    after = min(1.0, max(0.0, after))

    # Copy the table, then change only this skill, so the state passed in stays as it was.
    mastery = dict(state.mastery)
    mastery[step.skill] = after
    return MasteryState(nickname=state.nickname, mastery=mastery)


def _find_step(course: Course, problem_id: str, step_position: int) -> Step:
    """The step at `step_position` (counting from 1) of the problem with `problem_id`."""
    for problem in course.problems:
        if problem.id == problem_id:
            if not 1 <= step_position <= len(problem.steps):
                raise ValueError(
                    f"Problem '{problem_id}' has steps 1 to {len(problem.steps)}, "
                    f"so there is no step {step_position}."
                )
            return problem.steps[step_position - 1]  # the list counts from 0
    raise ValueError(f"There is no problem '{problem_id}' in course '{course.id}'.")


def _guess_chance(step: Step) -> float:
    """How likely a student who does not know the skill gets this step right by luck."""
    if step.kind == "choice":
        # `or []` treats a missing options line as no options; max(..., 1) avoids
        # dividing by 0 (the course checker rejects such a step anyway).
        options = step.options or []
        return min(MAX_GUESS_CHANCE, 1 / max(len(options), 1))
    if step.kind == "order":
        # Items can be put in order in 1 x 2 x 3 x ... ways (math.factorial), and
        # only one is right.
        items = step.answer if isinstance(step.answer, list) else []
        return min(MAX_GUESS_CHANCE, 1 / math.factorial(len(items)))
    return NUMBER_GUESS_CHANCE  # a number step, the only kind left
