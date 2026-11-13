# PRD: Grassroot Personalized Practice

*Product requirements doc for the personalized-practice feature. Written before any code. Draft v0.1: needs review by Jonathon and the Grassroot cofounder before the first feature ticket starts.*

**Owner:** Jonathon, product design intern (GitHub: jonathon-lockridge)
**Last updated:** 2026-11-12

## Goal

Turn each learner's own data (attempts, scores, hints, time, tutor signals) into the next set of practice problems that will teach them the most, so Grassroot's Practice mode adapts to the learner instead of the learner configuring it.

## Problem

Today in Practice mode the learner picks the difficulty and problem types and mixes topics themselves. Beginners don't know what they don't know. They pick comfortable topics and grind problems they already know (confidence up, scores flat, the pattern Grassroot's own blog documented in February 2026), or they hit problems whose prerequisites they lack and get discouraged. A human tutor solves this by tracking what a student has and hasn't mastered and choosing the next problem deliberately. The platform already collects the data a tutor would use (quiz scores, progress, usage, tutor conversations). Nothing turns it into decisions.

## Users

| User type | What they need to do | How many |
|---|---|---|
| Learner (college prep, SAT/ACT, AP, course help) | Get the next 5 problems that target what they haven't mastered, with a reason for each; see mastery per skill | Grassroot's active learners (count TBD) |
| Grassroot platform (the main app, calling this service) | Send attempt events; fetch next set and mastery; delete a learner's data | 1 integration |
| Grassroot team (Jonathon + cofounder) | See why a problem was picked; tune the policy; evaluate against today's Practice mode | 2 |
| Parent / teacher | View a mastery report | Out of scope for v1 |

## Main workflows

1. Learner finishes a problem in Practice mode. The platform sends the engine an attempt event (learner id, item id, correct or not, time, hints, timestamp). The engine updates the learner's mastery estimate for each skill the item tests.
2. Learner taps "Practice" or "Next". The platform asks the engine for the next set. The engine returns N items plus a one-line reason for each ("You missed two linear-equation problems yesterday", "Review: you haven't practiced ratios in 9 days"). The platform renders them.
3. Learner or platform asks for mastery. The engine returns one row per skill: mastery 0 to 1, attempts, last practiced, status.
4. The item bank is thin for the skill and difficulty needed. The engine generates a variant of an existing tagged problem with an LLM, validates it, marks it `generated` and `unreviewed`, and can serve it. Failed validation is discarded and logged.
5. Learner deletes their account or requests deletion. The platform calls delete on the engine. The engine erases every row linked to that learner.
6. The team evaluates: offline replay on historical attempts and simulated learners first, then an A/B test against today's self-selected Practice mode.

## Permissions

| Action | Learner (through the platform) | Platform service | Team / admin |
|---|---|---|---|
| Send own attempts | Yes | Yes | Yes |
| Get own next set and mastery | Yes | Yes | Yes |
| Get another learner's data | No | n/a (the platform asserts the learner id) | Yes, audited |
| Delete learner data | Own only | Yes | Yes |
| Edit skill map or item bank | No | No | Yes |
| Change selection policy parameters | No | No | Yes |

In v1 only the platform calls the engine, server to server, with a secret key. Learners never call it directly. Authorization is therefore the platform's authorization plus the engine trusting only the platform.

## Edge cases

- New learner with zero attempts: cold start. Serve a short diagnostic set (one item per top-level skill at medium difficulty) instead of guessing.
- Very fast answers (under 3 seconds): treat rapid wrong answers as guessing or disengagement and dampen the mastery drop; treat rapid correct streaks as evidence of mastery.
- Item tagged with several skills: update each skill (v1: equally).
- The same attempt arrives twice (network retry): idempotent on attempt id, stored once.
- Bank is empty for the target skill at the target difficulty: fall back to the adjacent difficulty, then to a generated variant. Never return an empty set while any item exists.
- Generated item fails validation: discard, log, never show.
- Engine is down: the platform falls back to today's self-selected Practice mode. The platform must not hard-depend on the engine.
- Prerequisite not mastered: recommend the prerequisite skill first and say so in the reason.
- Learner under 13: same behavior, no extra data, everything keyed to a pseudonymous id.

## Success criteria

- **Learning, not volume.** In an A/B test, learners on adaptive practice improve more on held-out quiz or assessment items than learners on self-selected practice. Problems completed and self-reported confidence are not success metrics.
- **Prediction quality.** The mastery model predicts next-attempt correctness better than a "learner's overall accuracy" baseline on replayed data (AUC and log loss).
- **Explainable.** Every recommendation carries a human-readable reason, and the team can trace why any item was picked.
- **Fast.** Next set from the bank in under 300 ms at p95. Generation may be slower and runs ahead of need.
- **No PII.** Zero personally identifying fields in the engine's database, verified by schema review.
- **Safe to integrate.** The platform can turn the engine on behind a feature flag and fall back if it errors.

## Out of scope (not in the first version)

- Generating whole courses or lessons (Learn mode)
- Teacher and parent dashboards
- Fitting model parameters on student data (needs a policy decision, see Constraints)
- Essay or free-text grading (v1 items are auto-gradable: multiple choice, numeric, short exact answer)
- More than one course; v1 is one pilot course
- A learner-facing UI (the platform renders; the engine may ship a tiny internal debug page)

## Constraints

- **Budget:** $0/month to start (local development plus free tiers). LLM generation is metered per call and off by default.
- **Deadline:** TBD with cofounder.
- **Must use / must avoid:** Postgres-compatible storage. Python 3.12. No tutor transcripts in the engine. No PII (names, emails, date of birth, school) ever sent to the engine. Pseudonymous learner ids only.
- **Data and privacy:** Grassroot's privacy policy already lists "personalizing learning" as a purpose and already collects quiz scores and progress, so v1 uses existing data for its stated purpose and collects nothing new. COPPA: no new collection from under-13s. FERPA: engine data are education records, so access control, an audit log of admin reads, and deletion inside the platform's 60-day window. Grassroot publicly states learner data is never used to train AI models, so v1 uses fixed model parameters and no fine-tuning. Any statistical fitting on aggregate data needs an explicit go or no-go from the team and possibly a policy update.

## Open questions

- [ ] Which course is the pilot? Recommendation: SAT Math (finite, public skill taxonomy, OER-rich, matches Grassroot's audience). (Jonathon + cofounder)
- [ ] What tagged problem bank exists today, and in what format? Items need skill tags, a difficulty, and an auto-gradable answer. (cofounder)
- [ ] What do attempts and quiz results look like in the platform today? Can we get a pseudonymized export? (cofounder)
- [ ] How will the platform call the engine: as an HTTP service, or imported as a Python package inside an existing backend? (cofounder; shapes the deploy plan)
- [ ] Does fitting mastery parameters on aggregate anonymized attempts count as "training AI models" under Grassroot's public commitments? (team, possibly legal)
- [ ] Which LLM provider does the platform already use for practice generation? Reuse it here? (cofounder)
- [ ] Who owns what: the engine vs. the platform-side integration? (Jonathon + cofounder)
