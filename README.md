# Grassroot Personalized Practice

Product design internship project at [Grassroot Academy](https://grassroot.academy): personalizing practice problems from each learner's own data. The engine turns a learner's attempt history into the next set of practice problems, with a plain-language reason for each pick.

## Status

In development. Project setup is done; the first feature ticket (T1 in [TODO.md](TODO.md)) is next. Not deployed. The plan (PRD.md) is a draft awaiting review by Jonathon and the Grassroot cofounder.

## What v1 will do

- Ingest attempt events from the Grassroot platform (correct or not, time, hints) keyed to pseudonymous learner ids
- Estimate mastery per skill with Bayesian Knowledge Tracing (fixed parameters, no training on student data)
- Pick the next set: skills in the learning zone, prerequisites first, spaced review of fading skills, interleaved, each with a reason
- Serve a diagnostic set to brand-new learners
- Delete every row for a learner on request
- Generate validated variants of existing problems with an LLM only when the bank is thin (off by default)

## Tech stack

- **Language:** Python 3.12
- **API:** FastAPI + pydantic (thin layer; the core has no web or database imports)
- **Storage:** SQLite locally, Postgres in production
- **AI model:** planned, generation only
- **Quality gates:** pytest, ruff, pre-commit hooks, GitHub Actions CI, secret scan

## Getting started

Full steps in [SETUP.md](SETUP.md). Short version:

```bash
git clone https://github.com/jonathon-lockridge/grassroot-personalized-practice-internship.git
cd grassroot-personalized-practice-internship
cp .env.example .env
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
pytest -q
uvicorn practice_engine.api:app --reload
```

Then open http://127.0.0.1:8000/health and http://127.0.0.1:8000/docs.

## Project docs

| File | What's in it |
|---|---|
| [PRD.md](PRD.md) | What we're building, for whom, and how we'll know it works |
| [docs/api-contract.md](docs/api-contract.md) | The endpoints the platform will call (draft) |
| [docs/research/grassroot-academy.md](docs/research/grassroot-academy.md) | What the public Grassroot site says about the product, data, and pricing |
| [DECISIONS.md](DECISIONS.md) | Why things are built the way they are, with the case against each choice |
| [TODO.md](TODO.md) | Tickets, one at a time |
| [TEST_PLAN.md](TEST_PLAN.md) | What to check before merging and deploying |
| [CHANGELOG.md](CHANGELOG.md) | What changed and when |
| [SETUP.md](SETUP.md) | Exact steps to run it on a new computer |
| [DEPLOYMENT.md](DEPLOYMENT.md) | How it goes live and how to roll back |
| [PROMPTS.md](PROMPTS.md) | Reusable prompts and the project context block for AI sessions |
| [BUG_LOG.md](BUG_LOG.md) / [ERROR_LOG.md](ERROR_LOG.md) | Solved bugs and raw errors |

## How we work

- `main` always works. Every change goes on a branch named after its ticket (`feat/t2-bkt-update`) and merges through a pull request.
- One ticket at a time, from the top of [TODO.md](TODO.md). Each ticket says what "done" means and ships with a test.
- Commit messages: `feat: ...`, `fix: ...`, `docs: ...`, `test: ...`, `chore: ...`, one change per commit.
- Secrets live only in `.env` (ignored by git and blocked by a pre-commit hook). `.env.example` lists the names.
- After each ticket: update `CHANGELOG.md` and `TODO.md`; record any real decision in `DECISIONS.md`.

## For the cofounder

Ask Jonathon to add you as a collaborator on the GitHub repo. Start with [PRD.md](PRD.md), then [docs/api-contract.md](docs/api-contract.md). The open questions at the bottom of the PRD need your answers before ticket T3.
