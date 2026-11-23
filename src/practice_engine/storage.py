"""Remember students between sessions (step T5), in one local SQLite file.

SQLite is a small database that lives in a single file and comes with Python, so
nothing new needs installing. The file has three tables:

- students: one row per nickname and course.
- answers: every step answer, in the order it arrived. Rows are only ever added
  (and removed when a student is forgotten), never changed. Each row also keeps the
  course and the step's skill at the time it was saved, so a later edit to the
  course file can be noticed. A `given` column can hold what the student typed or
  picked, so T8 can see which wrong option was chosen; it may be left empty.
- picks: every next problem the engine chose, with its reason (PRD decision 4).

Mastery is not stored. It is worked out again each time by replaying the saved
answers through update_mastery, oldest first. That keeps the answers as the only
record of what happened, so a saved number can never disagree with the history.
The time on each answer decides the order, not the order the answers arrived in.
If the course is edited later, answers to a step that is gone, or that now
practices a different skill, are skipped, as mastery.py and selection.py do.
check_saved_answers lists them so the change can be looked at.

The helpers:

- open_storage(path): open the file, making it and its tables if needed.
- save_answer(db, course, answer, given=None): save one step answer. True if it
  was new, False if the same answer was already saved.
- load_history(db, course, nickname): the student's saved answers, oldest first.
- load_mastery(db, course, nickname): the student's MasteryState, rebuilt.
- check_saved_answers(db, course): plain complaints about saved answers that no
  longer match the course file. An empty list means they all match.
- save_picks(db, course, nickname, picks, created_at) and load_picks(db, course,
  nickname): record a batch of next problems, and read them all back.
- list_students(db, course_id=None): every nickname with saved answers or picks,
  in alphabetical order.
- forget_student(db, nickname): delete every row about a student; gives back how
  many rows went.

Times are saved as text in UTC (world time), always in the same form, such as
2026-11-20T10:00:00.000000+00:00, so sorting the text sorts the times. They come
back as times with a time zone. A time without a time zone is refused, because we
cannot tell which moment it means.

Loaded times have a time zone, so pass a time with one too, such as
datetime.now(UTC), as `now` when giving a loaded history to next_problems.

Open one connection for each request or session (open_storage), and close it when
done. A connection should not be shared between threads.

Every query passes its values separately from the SQL text (the `?` marks), so a
nickname containing quotes is stored as plain text and cannot change the query.

Nothing here knows about algebra or physics.
"""

import math
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from practice_engine.mastery import new_mastery_state, update_mastery
from practice_engine.models import Course, MasteryState, StepAnswer
from practice_engine.selection import MissedStep, Pick

# The tables. `seq` numbers each row in the order it was saved, so answers with the
# same time come back in the order they arrived. UNIQUE says what makes an answer
# "the same answer": the same student, course, problem, step, try and time. A second
# copy of it is not stored.
SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    nickname TEXT NOT NULL,
    course_id TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,  -- time of the first answer or pick saved for them
    PRIMARY KEY (nickname, course_id)
);
CREATE TABLE IF NOT EXISTS answers (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    nickname TEXT NOT NULL,
    course_id TEXT NOT NULL,
    problem_id TEXT NOT NULL,
    step_position INTEGER NOT NULL,
    skill_id TEXT NOT NULL,
    correct INTEGER NOT NULL,
    seconds REAL NOT NULL,
    hints_used INTEGER NOT NULL,
    attempt INTEGER NOT NULL,
    answered_at TEXT NOT NULL,
    given TEXT,
    UNIQUE (nickname, course_id, problem_id, step_position, attempt, answered_at)
);
CREATE TABLE IF NOT EXISTS picks (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    nickname TEXT NOT NULL,
    course_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    position INTEGER NOT NULL,
    problem_id TEXT NOT NULL,
    target_skill TEXT NOT NULL,
    is_follow_up INTEGER NOT NULL,
    missed_problem_id TEXT,
    missed_step_position INTEGER,
    reason TEXT NOT NULL
);
"""

# One delete for every table that holds rows about a student, for forget_student.
FORGET_QUERIES = (
    "DELETE FROM students WHERE nickname = ?",
    "DELETE FROM answers WHERE nickname = ?",
    "DELETE FROM picks WHERE nickname = ?",
)

# Adds the student's row the first time an answer or pick is saved for them.
_ADD_STUDENT = (
    "INSERT OR IGNORE INTO students (nickname, course_id, first_seen_at) VALUES (?, ?, ?)"
)


def open_storage(path: str | Path) -> sqlite3.Connection:
    """Open the file at `path`, making it and its tables if they do not exist yet.

    Close it when done, for example with `contextlib.closing`.
    """
    db = sqlite3.connect(path)
    with db:
        db.executescript(SCHEMA)
    return db


def save_answer(
    db: sqlite3.Connection, course: Course, answer: StepAnswer, given: str | None = None
) -> bool:
    """Save one step answer. True if it was new, False if it was already saved.

    `given` is what the student typed or picked, if known. Stops with a ValueError
    if the answer's time has no time zone, if the course has no such problem or
    step, or if an answer with the same identity (student, course, problem, step,
    try and time) was already saved with different details.
    """
    answered_at = _to_text(answer.answered_at)
    if not math.isfinite(answer.seconds):
        raise ValueError(f"The answer's seconds ({answer.seconds}) is not a usable number.")
    skill_id = _skill_of(course, answer.problem_id, answer.step_position)
    row = (
        answer.nickname,
        course.id,
        answer.problem_id,
        answer.step_position,
        skill_id,
        int(answer.correct),
        answer.seconds,
        answer.hints_used,
        answer.attempt,
        answered_at,
        given,
    )
    with db:  # one transaction: both rows are saved, or neither
        db.execute(_ADD_STUDENT, (answer.nickname, course.id, answered_at))
        added = db.execute(
            "INSERT INTO answers (nickname, course_id, problem_id, step_position, skill_id,"
            " correct, seconds, hints_used, attempt, answered_at, given)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT DO NOTHING",
            row,
        ).rowcount
    if added:
        return True
    # Already there. If the details differ, one of the two is a mistake: say so.
    saved = db.execute(
        "SELECT nickname, course_id, problem_id, step_position, skill_id, correct, seconds,"
        " hints_used, attempt, answered_at, given FROM answers"
        " WHERE nickname = ? AND course_id = ? AND problem_id = ? AND step_position = ?"
        " AND attempt = ? AND answered_at = ?",
        (
            answer.nickname,
            course.id,
            answer.problem_id,
            answer.step_position,
            answer.attempt,
            answered_at,
        ),
    ).fetchone()
    if saved != row:
        raise ValueError(
            f"An answer by '{answer.nickname}' to step {answer.step_position} of "
            f"'{answer.problem_id}' (try {answer.attempt}, at {answered_at}) is already "
            "saved with different details."
        )
    return False


def load_history(db: sqlite3.Connection, course: Course, nickname: str) -> list[StepAnswer]:
    """The student's saved answers in this course, oldest first.

    Answers with the same time come back in the order they were saved.
    """
    return [step_answer for step_answer, _ in _load_answers(db, course, nickname)]


def load_mastery(db: sqlite3.Connection, course: Course, nickname: str) -> MasteryState:
    """The student's mastery, rebuilt by replaying their saved answers, oldest first.

    A student with no saved answers gets a new student's state. An answer whose
    step is gone from the course, or now practices a different skill than when it
    was saved, is skipped, so it is never counted toward the wrong skill (see
    check_saved_answers to list them).
    """
    skill_now = {
        (problem.id, position): step.skill
        for problem in course.problems
        for position, step in enumerate(problem.steps, start=1)
    }
    state = new_mastery_state(course, nickname)
    for step_answer, saved_skill in _load_answers(db, course, nickname):
        if skill_now.get((step_answer.problem_id, step_answer.step_position)) == saved_skill:
            state = update_mastery(state, step_answer, course)
    return state


def check_saved_answers(
    db: sqlite3.Connection, course: Course, nickname: str | None = None
) -> list[str]:
    """Plain complaints about saved answers that no longer match the course file.

    An answer no longer matches when its problem or step is gone, or when the step
    now practices a different skill than when it was saved. Give `nickname` to
    check one student only. An empty list means every saved answer still matches.
    """
    rows = db.execute(
        "SELECT DISTINCT problem_id, step_position, skill_id FROM answers"
        " WHERE course_id = ? AND (? IS NULL OR nickname = ?)"
        " ORDER BY problem_id, step_position",
        (course.id, nickname, nickname),
    ).fetchall()
    complaints = []
    for problem_id, step_position, saved_skill in rows:
        try:
            skill_now = _skill_of(course, problem_id, step_position)
        except ValueError:
            complaints.append(
                f"Step {step_position} of '{problem_id}' was answered but is no longer "
                "in the course."
            )
            continue
        if skill_now != saved_skill:
            complaints.append(
                f"Step {step_position} of '{problem_id}' practiced '{saved_skill}' when "
                f"answered, but now practices '{skill_now}'."
            )
    return complaints


def save_picks(
    db: sqlite3.Connection,
    course: Course,
    nickname: str,
    picks: list[Pick],
    created_at: datetime,
) -> None:
    """Record one batch of next problems the engine chose, in order, with reasons."""
    created = _to_text(created_at)
    rows = [
        (
            nickname,
            course.id,
            created,
            position,
            pick.problem_id,
            pick.target_skill,
            int(pick.is_follow_up),
            pick.missed_step.problem_id if pick.missed_step else None,
            pick.missed_step.step_position if pick.missed_step else None,
            pick.reason,
        )
        for position, pick in enumerate(picks, start=1)
    ]
    with db:
        db.execute(_ADD_STUDENT, (nickname, course.id, created))
        db.executemany(
            "INSERT INTO picks (nickname, course_id, created_at, position, problem_id,"
            " target_skill, is_follow_up, missed_problem_id, missed_step_position, reason)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )


def load_picks(
    db: sqlite3.Connection, course: Course, nickname: str
) -> list[tuple[datetime, Pick]]:
    """Every pick recorded for the student in this course, oldest batch first.

    Each item is (when the batch was made, the pick).
    """
    rows = db.execute(
        "SELECT created_at, problem_id, target_skill, is_follow_up, missed_problem_id,"
        " missed_step_position, reason FROM picks"
        " WHERE nickname = ? AND course_id = ? ORDER BY created_at, seq",
        (nickname, course.id),
    ).fetchall()
    saved = []
    for (
        created,
        problem_id,
        target_skill,
        is_follow_up,
        missed_problem,
        missed_step,
        reason,
    ) in rows:
        missed = None
        if missed_problem is not None:
            missed = MissedStep(problem_id=missed_problem, step_position=missed_step)
        pick = Pick(
            problem_id=problem_id,
            reason=reason,
            is_follow_up=bool(is_follow_up),
            target_skill=target_skill,
            missed_step=missed,
        )
        saved.append((_from_text(created), pick))
    return saved


def list_students(db: sqlite3.Connection, course_id: str | None = None) -> list[str]:
    """Every nickname with saved answers or picks, in alphabetical order.

    Give `course_id` to list one course only.
    """
    rows = db.execute(
        "SELECT DISTINCT nickname FROM students WHERE (? IS NULL OR course_id = ?)"
        " ORDER BY nickname",
        (course_id, course_id),
    ).fetchall()
    return [nickname for (nickname,) in rows]


def forget_student(db: sqlite3.Connection, nickname: str) -> int:
    """Delete every row about the student, in every course. Gives back how many went.

    It is one transaction, so either every row goes or, if something fails, none do.
    """
    removed = 0
    with db:
        for query in FORGET_QUERIES:
            removed += db.execute(query, (nickname,)).rowcount
    return removed


def _load_answers(
    db: sqlite3.Connection, course: Course, nickname: str
) -> list[tuple[StepAnswer, str]]:
    """The student's saved answers, oldest first, each with the skill saved beside it."""
    rows = db.execute(
        "SELECT nickname, problem_id, step_position, correct, seconds, hints_used,"
        " answered_at, attempt, skill_id FROM answers"
        " WHERE nickname = ? AND course_id = ? ORDER BY answered_at, seq",
        (nickname, course.id),
    ).fetchall()
    return [
        (
            StepAnswer(
                nickname=row[0],
                problem_id=row[1],
                step_position=row[2],
                correct=bool(row[3]),
                seconds=row[4],
                hints_used=row[5],
                answered_at=_from_text(row[6]),
                attempt=row[7],
            ),
            row[8],
        )
        for row in rows
    ]


def _to_text(moment: datetime) -> str:
    """A time as UTC text in one fixed form. Refuses a time without a time zone."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(
            f"The time {moment} has no time zone, so it cannot be saved; "
            "use a time with one, such as datetime.now(UTC)."
        )
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


def _from_text(text: str) -> datetime:
    """A time saved by _to_text, back as a time in UTC."""
    return datetime.fromisoformat(text)


def _skill_of(course: Course, problem_id: str, step_position: int) -> str:
    """The skill of a step. Stops with a ValueError if the course has no such step."""
    for problem in course.problems:
        if problem.id == problem_id:
            if 1 <= step_position <= len(problem.steps):
                return problem.steps[step_position - 1].skill
            raise ValueError(f"Problem '{problem_id}' has no step {step_position}.")
    raise ValueError(f"The course has no problem '{problem_id}'.")
