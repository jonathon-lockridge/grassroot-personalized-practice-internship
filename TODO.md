# To do

*Small tickets, each under an hour or two and testable on its own. Work on one at a time. Update this at the start and end of every session.*

## Now (one ticket only)

- [ ] **T1 Domain model + pilot skill map + sample item bank.** Define `Skill`, `Item`, `Attempt`, `MasteryState` as pydantic models in `src/practice_engine/models.py`. Add `data/sat_math/skills.json` (10 to 15 skills with prerequisites) and `data/sat_math/items.sample.json` (about 30 tagged, auto-gradable items). **Done when:** `pytest` passes a test that loads both files, every item's skills exist in the skill map, and the prerequisite graph has no cycle.

## Next

- [ ] **T2 Mastery update (BKT) as a pure function.** `update_mastery(state, attempt, params) -> state` in `mastery.py`, no imports from FastAPI or SQL. **Done when:** tests show mastery rises on a correct answer, falls on an incorrect one, stays within 0 to 1, dampens sub-3-second wrong answers, and matches a hand-computed value for one worked example.
- [ ] **T3 Learner state store.** SQLite through SQLAlchemy with `learners`, `attempts`, `mastery` tables; ingestion idempotent on `attempt_id`. **Done when:** sending the same attempt twice stores one row and updates mastery once; a Postgres URL works with the same code (checked once against a local Postgres).
- [ ] **T4 Selection policy v1.** Learning zone (mastery 0.3 to 0.85), prerequisites at 0.7 or above first, spaced review for decayed skills, interleave 2 to 3 skills, no repeats within 24 hours, reason string per pick, diagnostic set for new learners. **Done when:** tests cover a new learner getting a diagnostic, a weak skill being prioritized, an unmet prerequisite redirecting, and a non-empty set whenever the bank has items.
- [ ] **T5 HTTP API.** `POST /v1/attempts`, `GET /v1/learners/{id}/next-set`, `GET /v1/learners/{id}/mastery`, `DELETE /v1/learners/{id}`, `X-API-Key` auth, PII fields rejected by schema. **Done when:** TEST_PLAN critical paths 1 to 6 pass and a wrong key returns 401.
- [ ] **T6 Offline evaluation harness.** Simulated learners with hidden true mastery; compare adaptive vs. random vs. fixed-sequence on attempts-to-mastery; replay on exported real attempts for AUC and log loss. **Done when:** `python -m practice_engine.eval` prints a comparison table and adaptive beats random on simulated learners.
- [ ] **T7 LLM variant generation behind `GENERATION_ENABLED`.** Variants of existing tagged items (same skill and difficulty), schema plus answer-consistency validation, stored with `generated: true, reviewed: false`. **Done when:** an item that fails validation is never served, and a validated one carries the flags and provenance.
- [ ] **T8 Integration spec + export script.** Finalize `docs/api-contract.md` with the cofounder; write `scripts/export_attempts.py` for a pseudonymized export. **Done when:** the cofounder can run it and we have a real dataset for T6.
- [ ] **T9 Deploy.** Railway or Render for the API, Postgres, secrets in the host's settings, `/health` wired to the host's health check. **Done when:** `/health` is live and TEST_PLAN passes against the deployed URL; `DEPLOYMENT.md` lists the steps and the rollback.

## Later

- Elo or IRT item-difficulty fitting (needs the data-use decision in PRD.md)
- Misconception tags from Learn mode as extra signals
- A/B test design doc with a pre-registered metric (held-out assessment gains)
- Parent and teacher mastery report
- Branch protection on `main` (GitHub requires Pro or Team for private repos; or make the repo public)
- Replace the basic secret grep in CI with gitleaks or trufflehog

## Temporary workarounds to replace

- Fixed BKT parameters per skill: real fix is fitting on aggregate attempt data once the team confirms it fits Grassroot's "never used to train AI models" commitment (see DECISIONS.md, 2026-11-12).

## Done

- [x] 2026-11-12 Project setup: PRD, decisions, API contract draft, GitHub repo, CI, pre-commit hooks, health endpoint with a test.
