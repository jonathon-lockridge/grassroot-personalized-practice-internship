"""Web layer of the engine (step T4): the practice page and the requests it makes.

Keep this file thin. Every decision about what is right, what the student knows and
what to practice next lives in the core modules (checking, mastery, selection,
storage); this file only passes values between them and the page.

The requests:

- GET /: the practice page (files in the `page` folder next to this file).
- GET /api/course: the course title, its skills in course order, its problem ids, and
  its units and lessons (each lesson with its skills and its short notes).
- GET /api/problems/{id}: one problem for the page, without answers or why-wrong
  messages, so the page cannot give them away. A choice step's options and an order
  step's items come shuffled, so the right one is not always in the same place. It
  also gives `started_at`, the time the student opened the problem, which the page
  sends back with each answer.
- POST /api/start {nickname}: the student's mastery and their next problems.
- POST /api/answer: check one try at one step, save it, and say what the page shows
  next. A wrong first try gets why it is wrong and a hint, and one more try; a wrong
  second try also gets the right answer, and the step ends (decided 2026-11-26).
  Text that cannot be read, such as "five", a choice that is not one of the options,
  or an order of other items, is not saved: the student answers again.
  The server works out which try this is from the tries saved since `started_at`,
  instead of trusting the page: a first try, then a second only after a wrong first.
  The same try sent twice (a reply lost on the way) gets the same reply and is saved
  once; anything else on a finished step is refused (409).
- POST /api/next {nickname}: a fresh batch of next problems, each with its reason,
  saved with save_picks so the record shows what the engine decided and why.
- POST /api/lesson/next {nickname, lesson_id}: the one next problem while practicing a
  lesson (selection.next_problem), saved the same way, or null when the lesson has
  nothing fresh left today. With no lesson_id, the whole course is the lesson.

Students go by nickname only. There is no sign-in: this is a local demo, so someone
writing their own requests could reopen a problem to get fresh first tries. Plugging
into Grassroot would add sign-in and server-side sessions (see PRD.md).
"""

import os
import random
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime, BaseModel, Field, StringConstraints

from practice_engine import __version__
from practice_engine.checking import can_read, check_answer
from practice_engine.mastery import is_mastered
from practice_engine.models import Step, StepAnswer, load_course, validate_course
from practice_engine.selection import READY_MASTERY, Pick, next_problem, next_problems
from practice_engine.storage import (
    load_history,
    load_mastery,
    load_tries,
    open_storage,
    save_answer,
    save_picks,
)

PAGE = Path(__file__).resolve().parent / "page"
REPO = Path(__file__).resolve().parents[2]
DEFAULT_COURSE = REPO / "data" / "ap-physics-c-energy-momentum" / "course.json"
DEFAULT_DB = REPO / "practice.db"  # *.db files are never committed (see .gitignore)

# How many next problems the page shows at once.
BATCH_SIZE = 3
# How long an opened problem stays open for answers. Older, and the page must reopen it.
OPEN_HOURS = 12

# A nickname: 1 to 24 letters, digits, spaces, "_" or "-", starting with a letter or
# digit and not ending with a space. Anything else, such as "<script>", is refused.
Nickname = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9 _-]{0,22}[A-Za-z0-9_-])?$")
]


class StartRequest(BaseModel):
    nickname: Nickname


class LessonRequest(BaseModel):
    nickname: Nickname
    lesson_id: str | None = None  # None: practice the whole course


class AnswerRequest(BaseModel):
    nickname: Nickname
    problem_id: str
    step_position: int = Field(ge=1)
    # What the student picked or typed: an option's text, typed text, or an order.
    given: str | list[str]
    seconds: float = Field(ge=0, le=24 * 60 * 60, allow_inf_nan=False)
    hints_used: int = Field(ge=0, le=10)
    # Which try the page thinks this is. The server checks it against the saved tries.
    attempt: int = Field(ge=1, le=2)
    started_at: AwareDatetime  # from GET /api/problems; must have a time zone


def create_app(
    course_path: str | Path = DEFAULT_COURSE,
    db_path: str | Path = DEFAULT_DB,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    """Build the web app for one course file and one saved file.

    `clock` gives the current time with a time zone; tests pass their own.
    Stops with a ValueError if the course file has faults.
    """
    course = load_course(course_path)
    faults = validate_course(course)
    if faults:
        raise ValueError("The course file has faults:\n" + "\n".join(faults))
    now = clock or (lambda: datetime.now(UTC))
    skill_names = {skill.id: skill.name for skill in course.skills}
    problems = {problem.id: problem for problem in course.problems}
    lessons = {lesson.id: lesson for unit in course.units for lesson in unit.lessons}

    app = FastAPI(title="Grassroot Personalized Practice", version=__version__)
    app.mount("/page", StaticFiles(directory=PAGE), name="page")

    @app.exception_handler(RequestValidationError)
    async def refused(request: Request, error: RequestValidationError) -> JSONResponse:
        """A refused request: say where and why, but do not echo the input back, which
        could be a value (such as NaN) that cannot be written as JSON."""
        details = [{"loc": list(item["loc"]), "msg": item["msg"]} for item in error.errors()]
        return JSONResponse(status_code=422, content={"detail": details})

    def find_step(problem_id: str, position: int) -> Step:
        problem = problems.get(problem_id)
        if problem is None or not 1 <= position <= len(problem.steps):
            raise HTTPException(404, f"No step {position} in problem '{problem_id}'.")
        return problem.steps[position - 1]

    def mastery_view(db, nickname: str) -> list[dict]:
        state = load_mastery(db, course, nickname)
        history = load_history(db, course, nickname)
        # Skills with at least one first try, so the page can tell "not started" apart.
        tried = {
            problems[answer.problem_id].steps[answer.step_position - 1].skill
            for answer in history
            if answer.attempt == 1
            and answer.problem_id in problems
            and answer.step_position <= len(problems[answer.problem_id].steps)
        }
        return [
            {
                "id": skill.id,
                "name": skill.name,
                "mastery": round(state.mastery[skill.id], 4),
                "mastered": is_mastered(state, history, skill.id, course),
                "tried": skill.id in tried,
                # Every skill it builds on is known well enough to start it now.
                "ready": all(state.mastery[p] >= READY_MASTERY for p in skill.prerequisites),
            }
            for skill in course.skills
        ]

    def pick_view(pick: Pick) -> dict:
        problem = problems[pick.problem_id]
        missed = None
        if pick.missed_step is not None:
            missed_problem = problems[pick.missed_step.problem_id]
            position = pick.missed_step.step_position
            missed = {
                "problem_title": missed_problem.title,
                "step_position": position,
                "step_prompt": missed_problem.steps[position - 1].prompt,
            }
        return {
            "problem_id": problem.id,
            "title": problem.title,
            "difficulty": problem.difficulty,
            "reason": pick.reason,
            "rule": pick.rule,
            "challenge": pick.challenge,
            "is_follow_up": pick.is_follow_up,
            "skill_id": pick.target_skill,
            "skill_name": skill_names[pick.target_skill],
            "missed": missed,
        }

    def next_batch(db, nickname: str) -> list[dict]:
        moment = now()
        state = load_mastery(db, course, nickname)
        history = load_history(db, course, nickname)
        picks = next_problems(course, state, history, moment, count=BATCH_SIZE)
        save_picks(db, course, nickname, picks, moment)
        return [pick_view(pick) for pick in picks]

    @app.get("/health")
    def health() -> dict[str, str]:
        """Quick check that the server is up."""
        return {"status": "ok", "service": "practice-engine", "version": __version__}

    @app.get("/", include_in_schema=False)
    def page() -> FileResponse:
        return FileResponse(PAGE / "index.html")

    @app.get("/api/course")
    def course_view() -> dict:
        return {
            "id": course.id,
            "title": course.title,
            "skills": [{"id": skill.id, "name": skill.name} for skill in course.skills],
            "problem_ids": list(problems),
            "units": [
                {
                    "title": unit.title,
                    "lessons": [
                        {
                            "id": lesson.id,
                            "title": lesson.title,
                            "skills": lesson.skills,
                            "notes": lesson.notes,
                        }
                        for lesson in unit.lessons
                    ],
                }
                for unit in course.units
            ],
        }

    @app.get("/api/problems/{problem_id}")
    def problem_view(problem_id: str) -> dict:
        problem = problems.get(problem_id)
        if problem is None:
            raise HTTPException(404, f"No problem '{problem_id}'.")
        steps = []
        for position, step in enumerate(problem.steps, start=1):
            sent = {
                "position": position,
                "prompt": step.prompt,
                "kind": step.kind,
                "hint": step.hint,
                "skill_name": skill_names[step.skill],
            }
            if step.kind == "choice":
                sent["options"] = random.sample(step.options, len(step.options))
            if step.kind == "order":
                sent["items"] = _shuffled(step.answer)
            steps.append(sent)
        return {
            "id": problem.id,
            "title": problem.title,
            "prompt": problem.prompt,
            "difficulty": problem.difficulty,
            "steps": steps,
            "started_at": now().isoformat(),
        }

    @app.post("/api/start")
    def start(request: StartRequest) -> dict:
        with closing(open_storage(db_path)) as db:
            return {
                "nickname": request.nickname,
                "mastery": mastery_view(db, request.nickname),
                "picks": next_batch(db, request.nickname),
            }

    @app.post("/api/next")
    def next_view(request: StartRequest) -> dict:
        with closing(open_storage(db_path)) as db:
            return {"picks": next_batch(db, request.nickname)}

    @app.post("/api/lesson/next")
    def lesson_next(request: LessonRequest) -> dict:
        if request.lesson_id is None:
            focus = None  # the whole course, with the usual readiness rule
        elif request.lesson_id in lessons:
            focus = set(lessons[request.lesson_id].skills)
        else:
            raise HTTPException(404, f"No lesson '{request.lesson_id}'.")
        moment = now()
        with closing(open_storage(db_path)) as db:
            state = load_mastery(db, course, request.nickname)
            history = load_history(db, course, request.nickname)
            pick = next_problem(course, state, history, moment, focus)
            if pick is None:
                return {"pick": None}
            save_picks(db, course, request.nickname, [pick], moment)
            return {"pick": pick_view(pick)}

    @app.post("/api/answer")
    def answer(request: AnswerRequest) -> dict:
        step = find_step(request.problem_id, request.step_position)
        given = request.given
        if not (can_read(step, given) and _fits(step, given)):
            return {"readable": False, "correct": None, "step_done": False}
        moment = now()
        if request.started_at > moment or moment - request.started_at > timedelta(hours=OPEN_HOURS):
            raise HTTPException(409, "This problem was opened too long ago. Open it again.")
        with closing(open_storage(db_path)) as db:
            tries = load_tries(
                db,
                course,
                request.nickname,
                request.problem_id,
                request.step_position,
                since=request.started_at,
            )
            if tries and tries[-1][0].attempt == request.attempt and tries[-1][1] == given:
                # The same try again (its reply was lost): answer it again, save nothing.
                correct = tries[-1][0].correct
            else:
                if not tries:
                    expected = 1
                elif len(tries) == 1 and not tries[0][0].correct:
                    expected = 2
                else:
                    raise HTTPException(409, "This step is already finished.")
                if request.attempt != expected:
                    raise HTTPException(409, f"This should be try {expected} at this step.")
                correct = check_answer(step, given)
                step_answer = StepAnswer(
                    nickname=request.nickname,
                    problem_id=request.problem_id,
                    step_position=request.step_position,
                    correct=correct,
                    seconds=request.seconds,
                    hints_used=request.hints_used,
                    answered_at=moment,
                    attempt=request.attempt,
                )
                save_answer(db, course, step_answer, given)
            mastery = mastery_view(db, request.nickname)
        last_try = request.attempt == 2
        return {
            "readable": True,
            "correct": correct,
            "attempt": request.attempt,
            "step_done": correct or last_try,
            "why": None if correct else _why_wrong(step, given),
            "hint": None if correct else step.hint,
            "right_answer": _right_answer(step) if not correct and last_try else None,
            "mastery": mastery,
        }

    return app


def _shuffled(items: list[str]) -> list[str]:
    """The items in a random order that is never already the right one.

    With only two items that would give the answer away (just swap them), so then
    either order may come.
    """
    shuffled = list(items)
    random.shuffle(shuffled)
    while len(items) > 2 and shuffled == items:
        random.shuffle(shuffled)
    return shuffled


def _same(first: str, second: str) -> bool:
    """Two texts match, ignoring capitals and spaces at the ends."""
    return first.strip().casefold() == second.strip().casefold()


def _fits(step: Step, given: str | list[str]) -> bool:
    """False for an answer that makes no sense for the step, so it is asked again.

    A choice must be one of the options; an order must hold exactly the step's items.
    Such an answer is not a sign of what the student knows, so it is not saved.
    """
    if step.kind == "choice":
        return any(_same(option, given) for option in step.options)
    if step.kind == "order":

        def norm(items: list[str]) -> list[str]:
            return sorted(item.strip().casefold() for item in items)

        return norm(given) == norm(step.answer)
    return True


def _why_wrong(step: Step, given: str | list[str]) -> str | None:
    """The course's message for a wrong option, if the step has one for `given`."""
    if step.kind != "choice" or not step.feedback or not isinstance(given, str):
        return None
    for option, message in step.feedback.items():
        if _same(option, given):
            return message
    return None


def _right_answer(step: Step) -> str | list[str]:
    """The step's answer as the page shows it: text, a number as text, or an order."""
    if step.kind == "number":
        return f"{step.answer:,}"  # such as 30, 5.48 or 1,400
    return step.answer


app = create_app(
    os.environ.get("PRACTICE_COURSE", DEFAULT_COURSE),
    os.environ.get("PRACTICE_DB", DEFAULT_DB),
)
