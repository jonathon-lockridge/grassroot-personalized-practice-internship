# Plan: Grassroot Personalized Practice

*What we're building, for whom, and how we'll know it works. The one document to read. Draft, being reviewed section by section.*

**Owner:** Jonathon, product design intern. **Mentor:** Grassroot Academy's cofounder, who reviews focus and progress at check-ins.
**Last updated:** 2026-11-13

## Goal

Build a working demonstration of practice that adapts to the student: problems are solved step by step, every step tells us something about what the student knows, and the next problem is chosen on purpose, with a reason. It must work for any course, including ones generated on request, not just one subject.

## What this is and isn't

This is an independent project. It stands on its own, with its own small set of test students, and it is what gets shown and discussed at check-ins. It is designed so it *could* plug into Grassroot's platform later, but nothing here depends on Grassroot's code, data or permission. How a student actually tries it (a web page, or something simpler first) is still open; see Decisions.

## Background

Grassroot Academy (grassroot.academy) is an AI tutoring platform. In Learn mode an AI tutor teaches a concept. In Practice mode the student picks the difficulty and problem types and mixes topics themselves. Any course a student asks for, Grassroot generates. Its blog reported in February 2026 that AI-assisted practice raised students' confidence and problem counts but not their test scores, which is why this plan measures learning, not volume.

## Problem

Students don't know what they don't know. Left to choose, they grind problems they can already do, or jump to ones they aren't ready for and get discouraged. And a plain right-or-wrong answer hides *where* it went wrong: a physics problem has a setup, a principle to apply, some algebra and a final value, and a student can fail at any one of them. A good tutor watches the steps, spots the one that breaks, and picks the next problem to fix exactly that.

## Users

| Who | What they need | How many |
|---|---|---|
| Student trying it (Jonathon, friends, classmates, under nicknames) | Solve problems step by step, get a hint on the step they miss, see what they've mastered and why the next problem was chosen | A handful, growing |
| Jonathon (builder) | Change a course's data without touching code; see the logs of what the engine decided and why | 1 |
| Mentor (the cofounder) | See one working thing at each check-in and discuss focus and progress | 1 |
| Grassroot's platform (later, maybe) | A clean way to send answers in and get next problems out | 0 for now |

## How it works, step by step

1. A student picks a course. At first that's a small hand-made sample course; later, a course generated from a topic or pasted notes.
2. The engine picks a problem. The student answers step one, then step two, and so on. Each step is checked immediately (pick the next step from a few options, type a number, or put steps in order). A wrong step gets a hint aimed at that step.
3. Every step answered is recorded with its skill, right or wrong, time taken and hints used. The engine updates its estimate of the student's mastery of that skill.
4. The next problem is chosen by rules (see Decisions) and comes with a one-line reason, such as "Last time you set up the equation right but lost the sign in step 3."
5. After a session the student sees their mastery per skill and the reasons behind the problems they got.
6. Jonathon reads the logs: did the engine flag the step the student actually struggled with?
7. At a check-in, one working piece is shown and the next focus is agreed.

## Edge cases

- New student with no history: a short diagnostic, one problem per main skill, instead of guessing.
- Answers in under 3 seconds: a fast wrong step looks like a guess and moves mastery less; a fast correct streak counts as mastery sooner.
- A step that tests two skills: update both (equally, for now).
- A one-step problem: just a problem with one step. Multiple choice still works.
- A course with no prerequisite information (likely for generated courses): the prerequisite rule switches off, the rest still works.
- A generated course whose data fails the checks (a step with no answer, a skill nobody uses): rejected before any student sees it.
- Nothing left to give at the right difficulty: use the next difficulty, then a generated variant. Never return nothing while any problem exists.

## How we'll know it works

- **It finds the struggle.** With test students, the step the engine flags as weak matches what the student says they struggled with in most sessions (target: 4 of 5).
- **Learning, not volume.** Simulated students reach mastery in fewer steps with the engine's order than with a random order. With real test students, scores on a short end check improve.
- **Explainable.** Every pick has a reason a student understands.
- **Generalizes.** Swapping in a second course is a data change, not a code change, and everything still works.
- **Demo-able.** A stranger can try it for fifteen minutes at a check-in with no explanation from us.
- **No personal data.** The data holds nicknames only, no names, emails or ages.

## Not in the first version

- Plugging into Grassroot's platform (see the last section)
- Teaching lessons; this is practice only
- Grading essays or free-text answers; steps are choices, numbers, or ordering
- Teacher or parent reports
- Tuning the mastery model's numbers on student data

## Constraints

- **Money:** $0 to start. AI calls (course generation, problem variants) cost per call and are off by default.
- **Time:** 12+ weeks at 4 to 6 hours a week, roughly 50 to 70 hours.
- **Tools:** Python 3.12. Data in a local SQLite file.
- **Data:** nicknames only, no emails or ages, so test students can be anyone. Logs exist to improve the engine and are deleted on request.

## Decisions so far

Each with the strongest argument against it, so future-us knows why.

1. **A standalone project with a subject-blind engine.** The engine knows nothing about physics or math. A course is data: skills, which skill depends on which, and problems made of steps, each step tagged with a skill. *Against:* without Grassroot's real students, we can't prove it works at their scale. *Guard:* test students plus simulated students; a clean interface so plugging in later is wiring, not a rewrite.
2. **Problems are step by step, each step checkable.** A wrong step shows exactly where the student is stuck, which a single right-or-wrong answer never can. *Against:* writing step-by-step problems is slower than writing multiple choice, and some subjects resist being cut into checkable steps. *Guard:* a one-step problem is allowed, and generation (decision 5) does the bulk writing later.
3. **Mastery per skill with a standard, explainable method (Bayesian Knowledge Tracing), fixed settings, updated after every step.** Works from the first answer and trains nothing on student data. *Against:* the settings may be wrong for our problems. *Guard:* test on simulated students before real ones; tune later if needed.
4. **Next-problem rules:** skills the student is partway through come first (mastery roughly 0.3 to 0.85), prerequisites before what depends on them, revisit skills that are fading, mix two or three skills, never repeat within a day, always attach a reason. *Against:* rules can feel rigid. *Guard:* the rules are a short list we can change in one place, and every pick is logged with its reason.
5. **Courses and problem variants can be generated by an AI model, but only into the engine's data format and only after automatic checks.** *Against:* a generated problem with a wrong answer teaches the wrong thing. *Guard:* checks before use, a flag on generated problems, and a review pass. Which AI service, and its cost, is an open question.
6. **How a student tries it is tentative.** The simplest thing that lets a person answer steps comes first, probably in the terminal; a web page follows only if it earns its place at a check-in. *Against:* a demo without a screen is less convincing. *Guard:* the engine is built so a web page can be added without changing it.
7. **Python 3.12 with SQLite.** The hard part is the model and its evaluation, which is Python's home turf. A small web server (FastAPI) is already set up for when a page or a plug-in needs it. *Against:* a second language would be needed if Grassroot's app is TypeScript and this ever plugs in. *Guard:* the interface in the last section is small enough to port.
8. **No personal data.** Nicknames only, delete on request. *Against:* none worth the risk.

## If it ever plugs into Grassroot

Grassroot's platform would call the engine through four small requests, all keyed to an anonymous student id and a secret key: record a step answer, get the next problems (with reasons), get the mastery picture, and forget a student. At that point Grassroot's rules apply in full: no personal data in the engine, children's and students' data laws (COPPA, FERPA), deletion within 60 days, Postgres storage, and Grassroot's public promise that learner data is never used to train AI models. Nothing in the current plan conflicts with those.

## Open questions

- [ ] Which subject for the first hand-made sample course? Physics (the step-by-step example) or algebra. (Jonathon)
- [ ] How often are check-ins, and what does the mentor want to see first? (Jonathon + mentor)
- [ ] Which AI service for generating courses and variants, and is there a key or budget for it? Needed by step T7. (Jonathon)
- [ ] Web page or not? Decided at step T4 after trying the simplest version. (Jonathon)
- [ ] How many test students can we get, and when? Needed by step T8. (Jonathon)
- [ ] Should this eventually plug into Grassroot? Ask once there is something to show. (mentor)
