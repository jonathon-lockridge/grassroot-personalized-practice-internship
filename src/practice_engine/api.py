"""HTTP layer for the practice engine.

Keep this file thin. Every decision about what a learner should practice next lives in the
core modules (models, mastery, selection), which import nothing from FastAPI or SQL.
"""

from fastapi import FastAPI

from practice_engine import __version__

app = FastAPI(title="Grassroot Practice Engine", version=__version__)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check for the platform and the deploy host."""
    return {"status": "ok", "service": "practice-engine", "version": __version__}
