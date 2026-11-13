from fastapi.testclient import TestClient

from practice_engine import __version__
from practice_engine.api import app


def test_health_reports_ok() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "practice-engine",
        "version": __version__,
    }
