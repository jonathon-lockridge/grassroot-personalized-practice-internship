# Grassroot Personalized Practice

Product design internship project at [Grassroot Academy](https://grassroot.academy): personalizing practice problems from each learner's own data.

Today a learner in Grassroot's Practice mode picks the difficulty and topics by hand. This project builds the part that chooses the next problems for them, based on what they have and haven't mastered, with a plain-language reason for each pick.

## Status

Planning. The plan is [PRD.md](PRD.md) and the work is broken into steps in [TODO.md](TODO.md). No feature code yet. Built with Python 3.12 and FastAPI; SQLite locally, Postgres in production.

## Running it

Needs Git and Python 3.12 or newer.

```bash
git clone https://github.com/jonathon-lockridge/grassroot-personalized-practice-internship.git
cd grassroot-personalized-practice-internship
cp .env.example .env
python3 -m venv .venv            # a private folder of tools just for this project
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q                        # runs the tests; expect "passed"
uvicorn practice_engine.api:app --reload
```

Then open http://127.0.0.1:8000/health. It should say `{"status": "ok", ...}`.

`.env` holds secrets such as keys and is never uploaded. `.env.example` lists the names only.

## How changes are made

One step from [TODO.md](TODO.md) at a time. Each step is tested, then saved with a message that says what changed and why. On every upload, GitHub runs the tests and checks that no secret was saved by accident.
