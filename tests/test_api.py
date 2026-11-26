"""Checks for the web layer (step T4): the page's requests to the engine.

Every test uses its own new saved file in a temporary folder (pytest's `tmp_path`)
and a clock the test sets, so nothing here touches a real saved file or the real time.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from practice_engine import __version__
from practice_engine.api import create_app
from practice_engine.models import load_course

COURSE = (
    Path(__file__).resolve().parents[1] / "data" / "ap-physics-c-energy-momentum" / "course.json"
)

# Problem push_cart: step 1 is a choice (choose_principle), step 2 the number 30
# (work_constant_force), step 3 the number 5.48 within 0.05 (kinetic_energy).
PRINCIPLE = "Work-energy theorem (net work equals change in kinetic energy)"
WRONG_PRINCIPLE = "Conservation of momentum"


class Clock:
    """A clock the test moves by hand, so answer times are known and never collide."""

    def __init__(self) -> None:
        self.now = datetime(2026, 11, 26, 10, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=30)
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def client(tmp_path: Path, clock: Clock) -> TestClient:
    return TestClient(create_app(COURSE, tmp_path / "practice.db", clock=clock))


def opened(client: TestClient, problem_id: str = "push_cart") -> str:
    """When the student opened the problem, as the page gets it. Opened once per client."""
    times = client.__dict__.setdefault("opened_at", {})
    if problem_id not in times:
        times[problem_id] = client.get(f"/api/problems/{problem_id}").json()["started_at"]
    return times[problem_id]


def body(client: TestClient, given, step: int = 1, attempt: int = 1, hints: int = 0, **extra):
    """An answer request as the page sends it, for push_cart unless `extra` says otherwise."""
    sent = {
        "nickname": "kiwi",
        "problem_id": "push_cart",
        "step_position": step,
        "given": given,
        "seconds": 12.0,
        "hints_used": hints,
        "attempt": attempt,
    }
    sent.update(extra)
    sent.setdefault("started_at", opened(client, sent["problem_id"]))
    return sent


def answer(client: TestClient, given, step: int = 1, attempt: int = 1, hints: int = 0, **extra):
    response = client.post("/api/answer", json=body(client, given, step, attempt, hints, **extra))
    assert response.status_code == 200, response.text
    return response.json()


def test_health_reports_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "practice-engine",
        "version": __version__,
    }


def test_the_page_itself_is_served(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert client.get("/page/page.js").status_code == 200
    assert client.get("/page/page.css").status_code == 200


def test_course_lists_skills_with_names_in_course_order(client: TestClient) -> None:
    course = client.get("/api/course").json()

    assert course["title"].startswith("AP Physics C")
    assert len(course["skills"]) == 17
    assert course["skills"][0]["id"] == "choose_principle"
    assert course["skills"][0]["name"]


def test_a_problem_is_sent_without_answers_or_why_wrong_messages(client: TestClient) -> None:
    problem = client.get("/api/problems/push_cart").json()

    assert problem["title"] == "Pushing a cart"
    assert [step["position"] for step in problem["steps"]] == [1, 2, 3]
    assert problem["steps"][0]["options"]
    assert problem["steps"][0]["skill_name"]
    for step in problem["steps"]:
        assert "answer" not in step
        assert "feedback" not in step
        assert "tolerance" not in step
        assert step["hint"]


def test_order_items_are_shuffled_never_already_in_order(client: TestClient) -> None:
    course = load_course(COURSE)
    order_steps = [
        (problem.id, position, step.answer)
        for problem in course.problems
        for position, step in enumerate(problem.steps, start=1)
        if step.kind == "order"
    ]
    assert order_steps, "the course should have at least one order step"
    for problem_id, position, right_order in order_steps:
        for _ in range(5):  # shuffled afresh each time, so try a few
            sent = client.get(f"/api/problems/{problem_id}").json()["steps"][position - 1]
            assert sorted(sent["items"]) == sorted(right_order)  # the same items
            assert sent["items"] != right_order  # but never already in order


def test_an_unknown_problem_is_a_404(client: TestClient) -> None:
    assert client.get("/api/problems/no_such_problem").status_code == 404


def test_start_gives_a_new_student_a_starting_check_and_mastery(client: TestClient) -> None:
    response = client.post("/api/start", json={"nickname": "kiwi"})

    assert response.status_code == 200
    start = response.json()
    assert start["nickname"] == "kiwi"
    assert len(start["picks"]) == 3
    assert all(pick["rule"] == "starting_check" for pick in start["picks"])
    assert all(pick["title"] and pick["skill_name"] for pick in start["picks"])
    assert len(start["mastery"]) == 17
    assert all(0 <= skill["mastery"] <= 1 for skill in start["mastery"])
    assert not any(skill["mastered"] or skill["tried"] for skill in start["mastery"])


@pytest.mark.parametrize("nickname", ["", " ", "a" * 25, "<script>", "kiwi\n"])
def test_a_bad_nickname_is_refused(client: TestClient, nickname: str) -> None:
    assert client.post("/api/start", json={"nickname": nickname}).status_code == 422


def test_a_right_first_try_finishes_the_step_and_raises_mastery(client: TestClient) -> None:
    before = client.post("/api/start", json={"nickname": "kiwi"}).json()["mastery"]

    result = answer(client, PRINCIPLE)

    assert result["readable"] is True
    assert result["correct"] is True
    assert result["step_done"] is True
    after = {skill["id"]: skill["mastery"] for skill in result["mastery"]}
    first = {skill["id"]: skill["mastery"] for skill in before}
    assert after["choose_principle"] > first["choose_principle"]
    tried = {skill["id"] for skill in result["mastery"] if skill["tried"]}
    assert tried == {"choose_principle"}


def test_a_wrong_first_try_says_why_and_gives_a_hint_and_one_more_try(client: TestClient) -> None:
    result = answer(client, WRONG_PRINCIPLE)

    assert result["correct"] is False
    assert result["step_done"] is False
    assert "outside force" in result["why"]
    assert result["hint"]
    assert result["right_answer"] is None  # not shown yet: one more try first


def test_a_wrong_second_try_shows_the_right_answer_and_ends_the_step(client: TestClient) -> None:
    answer(client, WRONG_PRINCIPLE)

    result = answer(client, "Conservation of mechanical energy", attempt=2, hints=1)

    assert result["correct"] is False
    assert result["step_done"] is True
    assert result["right_answer"] == PRINCIPLE


def test_only_the_first_try_changes_mastery(client: TestClient) -> None:
    first = answer(client, WRONG_PRINCIPLE)
    second = answer(client, PRINCIPLE, attempt=2, hints=1)

    assert second["correct"] is True
    assert second["mastery"] == first["mastery"]


def test_a_number_within_the_tolerance_is_right_and_commas_are_read(client: TestClient) -> None:
    assert answer(client, "5.5", step=3)["correct"] is True
    assert answer(client, "30", step=2)["correct"] is True


def test_unreadable_text_asks_to_retype_and_saves_nothing(client: TestClient) -> None:
    result = answer(client, "five m/s", step=3)

    assert result["readable"] is False
    assert result["correct"] is None
    assert result["step_done"] is False
    # Nothing was saved, so the student is still brand new: a starting check again.
    picks = client.post("/api/next", json={"nickname": "kiwi"}).json()["picks"]
    assert all(pick["rule"] == "starting_check" for pick in picks)


def test_a_miss_makes_a_follow_up_that_names_the_missed_step(client: TestClient) -> None:
    answer(client, PRINCIPLE)
    answer(client, "30", step=2)
    answer(client, "9", step=3)  # wrong: the speed is 5.48 m/s

    picks = client.post("/api/next", json={"nickname": "kiwi"}).json()["picks"]

    follow_ups = [pick for pick in picks if pick["is_follow_up"]]
    assert follow_ups, picks
    missed = follow_ups[0]["missed"]
    assert missed["problem_title"] == "Pushing a cart"
    assert missed["step_position"] == 3
    assert missed["step_prompt"].startswith("What is the cart's final speed")
    assert follow_ups[0]["skill_name"].startswith("Kinetic energy")
    assert follow_ups[0]["problem_id"] != "push_cart"  # a new problem, not the same one


def test_a_returning_student_keeps_their_mastery(tmp_path: Path, clock: Clock) -> None:
    saved = tmp_path / "practice.db"
    first = TestClient(create_app(COURSE, saved, clock=clock))
    first.post("/api/start", json={"nickname": "kiwi"})
    answer(first, PRINCIPLE)
    known = first.post("/api/start", json={"nickname": "kiwi"}).json()["mastery"]

    reopened = TestClient(create_app(COURSE, saved, clock=clock))
    again = reopened.post("/api/start", json={"nickname": "kiwi"}).json()

    assert again["mastery"] == known
    assert not all(pick["rule"] == "starting_check" for pick in again["picks"])


def test_an_answer_to_a_step_that_does_not_exist_is_a_404(client: TestClient) -> None:
    assert client.post("/api/answer", json=body(client, "1", step=9)).status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        {"seconds": -1},
        {"hints_used": -1},
        {"hints_used": 2**63},
        {"attempt": 3},
        {"attempt": 0},
        {"started_at": "2026-11-26T10:00:00"},  # no time zone
    ],
)
def test_out_of_range_values_are_refused(client: TestClient, change: dict) -> None:
    assert client.post("/api/answer", json=body(client, PRINCIPLE, **change)).status_code == 422


def test_a_time_that_is_not_a_number_is_refused(client: TestClient) -> None:
    text = json.dumps(body(client, PRINCIPLE)).replace('"seconds": 12.0', '"seconds": NaN')
    response = client.post(
        "/api/answer", content=text, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422


def test_choice_options_are_shuffled(client: TestClient) -> None:
    places = {
        client.get("/api/problems/push_cart").json()["steps"][0]["options"].index(PRINCIPLE)
        for _ in range(40)
    }
    assert len(places) > 1  # the right option does not always sit in the same place


def test_a_second_try_with_no_first_try_is_refused(client: TestClient) -> None:
    response = client.post("/api/answer", json=body(client, WRONG_PRINCIPLE, attempt=2))

    assert response.status_code == 409
    assert "right_answer" not in response.text


def test_a_finished_step_cannot_get_another_first_try(client: TestClient) -> None:
    answer(client, WRONG_PRINCIPLE)
    answer(client, PRINCIPLE, attempt=2)

    again = client.post("/api/answer", json=body(client, PRINCIPLE))

    assert again.status_code == 409


def test_a_first_try_cannot_be_sent_again_with_a_new_answer(client: TestClient) -> None:
    answer(client, WRONG_PRINCIPLE)

    again = client.post("/api/answer", json=body(client, PRINCIPLE))  # still says try 1

    assert again.status_code == 409


def test_the_same_try_sent_twice_gets_the_same_reply_and_is_saved_once(
    client: TestClient,
) -> None:
    first = answer(client, WRONG_PRINCIPLE)
    resent = answer(client, WRONG_PRINCIPLE)  # its reply was lost, so the page sends it again

    assert resent == first
    second = answer(client, PRINCIPLE, attempt=2)
    assert second["correct"] is True and second["step_done"] is True


def test_the_same_wrong_number_twice_counts_as_the_second_try(client: TestClient) -> None:
    answer(client, "9", step=3)

    result = answer(client, "9", step=3, attempt=2)

    assert result["step_done"] is True
    assert result["right_answer"] == "5.48"


def test_a_problem_opened_in_the_future_or_long_ago_is_refused(
    client: TestClient, clock: Clock
) -> None:
    future = (clock.now + timedelta(hours=1)).isoformat()
    old = (clock.now - timedelta(hours=13)).isoformat()

    assert (
        client.post("/api/answer", json=body(client, PRINCIPLE, started_at=future)).status_code
        == 409
    )
    assert (
        client.post("/api/answer", json=body(client, PRINCIPLE, started_at=old)).status_code == 409
    )


@pytest.mark.parametrize("given", ["", "zzz"])
def test_a_choice_that_is_not_an_option_is_asked_again(client: TestClient, given: str) -> None:
    result = answer(client, given)

    assert result["readable"] is False
    assert answer(client, PRINCIPLE)["correct"] is True  # nothing was saved before it


def order_step(course) -> tuple[str, int, list[str]]:
    problem = next(p for p in course.problems if any(s.kind == "order" for s in p.steps))
    position = next(i for i, s in enumerate(problem.steps, start=1) if s.kind == "order")
    return problem.id, position, problem.steps[position - 1].answer


def test_order_steps_are_checked_and_nonsense_orders_asked_again(client: TestClient) -> None:
    problem_id, position, right_order = order_step(load_course(COURSE))

    def send(given, attempt=1):
        return answer(client, given, step=position, attempt=attempt, problem_id=problem_id)

    assert send([])["readable"] is False
    assert send(["something else", *right_order[1:]])["readable"] is False
    assert send(list(reversed(right_order)))["correct"] is False
    assert send(right_order, attempt=2)["correct"] is True
