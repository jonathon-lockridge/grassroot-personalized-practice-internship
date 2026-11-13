# Plan: Grassroot Personalized Practice

*What we're building, for whom, and how we'll know it works. This is the one document to read. Draft, not yet agreed.*

**Owner:** Jonathon, product design intern at Grassroot Academy
**Last updated:** 2026-11-12

## Goal

Use each learner's own data (what they got right and wrong, how long they took, whether they needed hints) to choose the next practice problems that will teach them the most, so Grassroot's Practice mode adapts to the learner instead of making the learner configure it.

## Background

Grassroot Academy (grassroot.academy) is an AI tutoring platform launched in December 2025. It has two modes. In Learn mode an AI tutor teaches a concept and guides the learner to practice. In Practice mode the learner picks the difficulty and problem types and mixes topics themselves, then sees their results. Content comes from open textbooks (OpenStax and others) plus Grassroot's own problems. There are Free, Starter and Growth plans, and "practice generation" is metered by plan.

The platform already collects what a human tutor would use: quiz scores, assessment results, progress and usage, and tutor conversations. Its privacy policy lists "personalizing learning" as a purpose, promises COPPA and FERPA compliance (the US laws protecting children's and students' data), deletes progress data within 60 days of a request, and states publicly that learner data is never used to train AI models.

Grassroot's own blog reported in February 2026 that AI-assisted practice raised students' confidence and the number of problems they did, but not their test scores. That shapes how we measure success below.

## Problem

Beginners don't know what they don't know. Left to choose, they grind problems they can already do, or hit problems whose prerequisites they lack and get discouraged. A good tutor tracks what a student has and hasn't mastered and chooses the next problem deliberately. The platform has the data; nothing turns it into that decision.

## Users

| Who | What they need | How many |
|---|---|---|
| Learner (college prep, SAT/ACT, AP, course help) | The next five problems aimed at what they haven't mastered, with a reason for each; a view of their mastery per skill | Grassroot's active learners (count TBD) |
| The Grassroot platform (the main app, calling this service) | Send what the learner answered; fetch the next set and the mastery picture; delete a learner's data | 1 |
| Grassroot team (Jonathon + the cofounder) | See why a problem was picked; tune the rules; compare against today's Practice mode | 2 |
| Parent or teacher | A mastery report | Not in v1 |

## How it works, step by step

1. A learner finishes a problem. The platform tells the engine which problem, right or wrong, how long it took and how many hints were used. The engine updates its estimate of how well the learner knows each skill that problem tests.
2. The learner taps Practice or Next. The platform asks the engine for the next set. The engine returns five problems, each with a one-line reason such as "You missed two linear-equation problems yesterday" or "Review: you haven't practiced ratios in 9 days."
3. The learner or the platform asks for the mastery picture: one line per skill with a 0 to 1 score, attempts, last practiced, and a status.
4. If there aren't enough problems for a skill at the right difficulty, the engine makes a variant of an existing problem with an AI model (same skill and difficulty, new numbers), checks it, marks it as generated and unreviewed, and can use it. Anything that fails the check is thrown away.
5. A learner deletes their account. The platform tells the engine, and the engine erases everything tied to that learner.
6. The team checks that it works: first by replaying past data and simulated learners, then by comparing real learners on this against today's self-chosen practice.

## Who may do what

Only the platform's own server talks to the engine, using a secret key. Learners never call it directly, so the platform decides who the learner is and the engine trusts only the platform. The team can read anything, and those reads are logged. Only the team edits the skill map, the problem bank, or the rules.

## Edge cases

- Brand-new learner with no history: give a short diagnostic set, one problem per main skill at medium difficulty, instead of guessing.
- Answers in under 3 seconds: a fast wrong answer looks like a guess, so it moves the mastery score less; a fast correct streak counts as mastery sooner.
- A problem that tests several skills: update each one (equally, for now).
- The same answer sent twice (a network retry): stored once.
- Nothing left in the bank for a skill at that difficulty: use the next difficulty, then a generated variant. Never return an empty set while any problem exists.
- Engine down: the platform falls back to today's Practice mode. It must never depend on the engine to work.
- A prerequisite isn't mastered: recommend the prerequisite first and say so in the reason.
- Learner under 13: same behaviour, no extra data; everything is keyed to an anonymous id.

## How we'll know it works

- **Learning, not volume.** Learners on this improve more on held-out quiz questions than learners on self-chosen practice. Problems completed and confidence are not success measures.
- **Good predictions.** The mastery estimate predicts whether the next answer will be right better than the learner's plain overall accuracy does, measured on replayed data.
- **Explainable.** Every pick carries a reason, and the team can trace why any problem was chosen.
- **Fast.** The next set comes back in under 300 milliseconds almost always. Generating new problems may be slower and runs ahead of need.
- **No personal data.** The engine's database holds no names, emails, birthdays or schools, confirmed by reading its tables.
- **Safe to switch on.** The platform can turn it on behind a feature flag and fall back if it errors.

## Not in the first version

- Teaching lessons (Learn mode)
- Teacher and parent dashboards
- Tuning the model's numbers on student data (needs a policy decision, see below)
- Grading essays or free-text answers (v1 problems are multiple choice, numeric, or short exact answers)
- More than one course
- A learner-facing screen (the platform shows the problems; the engine may get a tiny internal debug page)

## Constraints

- **Money:** $0/month to start. AI generation costs per call and stays switched off by default.
- **Time:** the internship runs 12+ weeks at 4 to 6 hours a week.
- **Must:** Postgres-compatible storage; Python 3.12; anonymous learner ids only.
- **Must not:** store tutor conversations or any personal details (names, emails, birthdays, schools) in the engine.
- **Data and privacy:** v1 uses data the platform already collects, for the purpose its policy already states, and collects nothing new. Children's data (COPPA): no new collection. Education records (FERPA): access control, a log of team reads, and deletion within the platform's 60-day window. Because Grassroot says learner data is never used to train AI models, v1 uses fixed model settings and no fine-tuning. Any statistical tuning on aggregate data needs an explicit yes from the team.

## Decisions so far

Each with the strongest argument against it, so future-us knows why.

1. **Own repository and service, with a core that has no web or database code.** Lets us build and test on our own schedule and keeps both ways of plugging in (a web service, or a package the platform imports) open. *Against:* two systems means the platform has to send events to us, and learner data lives in two places. *Guard:* the delete call exists from day one; how the platform will call us is an open question below.
2. **Python 3.12 with FastAPI; SQLite locally, Postgres in production.** The hard part is the model and its evaluation, which is Python's home turf; Postgres because the platform already runs it. *Against:* if the platform is written in TypeScript, the cofounder reviews code in another language and we need our own hosting. *Guard:* a tiny, documented interface so nobody has to read the Python.
3. **Mastery estimate: Bayesian Knowledge Tracing with fixed settings.** A standard, explainable method that works from the first attempt and trains nothing on student data. The next-problem rules: pick skills the learner is partway through (score 0.3 to 0.85), prerequisites first, revisit skills that are fading, mix two or three skills, never repeat within 24 hours, always attach a reason. *Against:* fixed settings may be wrong for Grassroot's problems, and the method treats an easy and a hard problem as the same evidence. *Guard:* test on replayed data before any learner sees it; measure test gains, not volume; tune the settings later if the data-use question is answered yes.
4. **AI-generated problems only as a fallback, checked, flagged and switched off by default.** Keeps most picks cheap, fast and auditable. *Against:* a generated problem with a wrong answer teaches the wrong thing. *Guard:* automatic checks, a review queue, a per-learner daily cap, metered by plan like the platform's existing generation. Which AI service to use is an open question below.
5. **One pilot course first, SAT Math (to confirm).** A week of content work, not a quarter, with a public skill list and open textbook coverage. *Against:* if most learners use AP courses, this delays value. *Guard:* the skill map and problem bank are data files, so switching course is content work, not code.
6. **Anonymous ids only, no transcripts, deletion first.** The less we hold, the less can leak, and deletion stays simple. *Against:* what a learner said to the tutor is a strong signal. *Guard:* the platform can send short tags like "misconception: sign error" instead of text.

## What the platform will call

Every request carries a secret key in a header. Learner ids are the platform's anonymous ids, never names or emails. Sketch of the four calls, to be settled with the cofounder before step T5:

- **Record an answer:** `POST /v1/attempts` with the learner id, course, problem id, right or wrong, time taken, hints used, when it happened, and a unique attempt id so a retry is stored once.
- **Next set:** `GET /v1/learners/{id}/next-set?course_id=...&n=5` returns up to five problems, each with its skills, difficulty and reason, plus whether this is a diagnostic or an adaptive set.
- **Mastery picture:** `GET /v1/learners/{id}/mastery?course_id=...` returns one line per skill.
- **Forget a learner:** `DELETE /v1/learners/{id}` erases everything tied to that id.

The platform must send every answered problem, send no personal data, treat the engine as optional, and call the forget call from its own account-deletion flow.

## Open questions

- [ ] Which course is the pilot? Recommendation: SAT Math. (Jonathon + cofounder)
- [ ] What tagged problem bank exists today, and in what format? Problems need skill tags, a difficulty and an auto-gradable answer. (cofounder)
- [ ] What do answers and quiz results look like in the platform's database today? Can we get an anonymized export? (cofounder)
- [ ] Will the platform call this as a web service, or import it as a package? (cofounder; decides how we host it)
- [ ] Does tuning the model's numbers on aggregate anonymized data count as "training AI models" under Grassroot's public promise? (team, maybe legal)
- [ ] Which AI service does the platform already use for practice generation? Reuse it here? (cofounder)
- [ ] Who owns what: this engine vs. the platform-side wiring? (Jonathon + cofounder)
