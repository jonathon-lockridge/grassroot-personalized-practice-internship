"""Web layer of the engine.

Keep this file thin. Every decision about what a student should practice next will live in the
core modules (models, mastery, selection), which import nothing from FastAPI or SQL.
"""

from fastapi import FastAPI

from practice_engine import __version__

app = FastAPI(title="Grassroot Personalized Practice", version=__version__)


@app.get("/health")
def health() -> dict[str, str]:
    """Quick check that the server is up."""
    return {"status": "ok", "service": "practice-engine", "version": __version__}
