# Plan: Grassroot Personalized Practice

*What we're building, for whom, and how we'll know it works. The one document to read. Draft, being reviewed section by section.*

**Owner:** Jonathon, product design intern. **Mentor:** Grassroot Academy's cofounder, who reviews focus and progress at check-ins.
**Last updated:** 2026-11-20

## Goal

Build a working demonstration of practice that adapts to the student: problems are solved step by step, every step tells us something about what the student knows, and the next problem is chosen on purpose, with a reason. It must work for any course, including ones generated on request, not just one subject.

## What this is and isn't

This is an independent project. It stands on its own, with its own small set of test students, and it is what gets shown and discussed at check-ins. It is designed so it *could* plug into Grassroot's platform later, but nothing here depends on Grassroot's code, data or permission.

The demo is a **mock of Grassroot**: screens that look like Grassroot, where everything except practice is fake. The practice part, both what the student sees and the engine and stored data behind it, is built in full. (Mentor, 2026-11-19.)

## Background

Grassroot Academy (grassroot.academy) is an AI tutoring platform. In Learn mode an AI tutor teaches a concept. In Practice mode the student picks the difficulty and problem types and mixes topics themselves. Any course a student asks for, Grassroot generates. Its blog reported in February 2026 that AI-assisted practice raised students' confidence and problem counts but not their test scores, which is why this plan measures learning, not volume.

## Problem

Students don't know what they don't know. Left to choose, they grind problems they can already do, or jump to ones they aren't ready for and get discouraged. And a plain right-or-wrong answer hides *where* it went wrong: a physics problem has a setup, a principle to apply, some algebra and a final value, and a student can fail at any one of them. A good tutor watches the steps, spots the one that breaks, and picks the next problem to fix exactly that.

## Users

| Who | What they need | How many |
|---|---|---|
| Student trying it (Jonathon, friends, classmates, under nicknames) | Solve problems step by step, get a hint on the step they miss, see what they've mastered and why the next problem was chosen | A handful, growing |
| Jonathon (builder) | Change a course's data without touching code; see the record (the log) of what the engine decided and why | 1 |
| Mentor (the cofounder) | See one working thing at each check-in and discuss focus and progress | 1 |
| Grassroot's platform (later, maybe) | A clean way to send answers in and get next problems out | 0 for now |

## How it works, step by step

1. A student picks a course. First, AP Physics C: Mechanics, energy and momentum (`data/ap-physics-c-energy-momentum/`); later, a course generated from a topic or pasted notes.
2. The engine picks a problem. The student answers step one, then step two, and so on, each in one of three ways: pick the next step from a few options, type a number, or put steps in order. Each answer is checked immediately. A wrong step gets a hint aimed at that step.
3. Every step answered is recorded with its skill, right or wrong, time taken and hints used. The engine updates its estimate of the student's mastery of that skill.
4. The next problem is chosen by rules (see *Decisions so far*) and comes with a one-line reason, such as "Last time you set up the energy equation right but lost the sign of friction's work in step 3." The screen shows clearly, with a visible marker, when a problem was picked as a follow-up, and which skill and step it targets.
5. After a practice session the student sees their mastery per skill and the reasons behind the problems they got.
6. Jonathon reads the record: did the engine flag the step the student actually struggled with?
7. At a check-in, one working piece is shown and the next focus is agreed.

## Unusual cases

- New student with no history: a short diagnostic, one problem per main skill, instead of guessing.
- A wrong step answered in under 3 seconds looks like a guess and moves mastery less.
- A one-step problem: just a problem with one step. Multiple choice still works.
- A step with more than one correct move, in any subject: a wrong-looking answer that is really another correct method must not count against a skill. For now each step's question names its goal, so only one answer fits; this is checked by hand when problems are written, and generated problems will need the same check.
- A course with no prerequisite information (likely for generated courses): the prerequisite rule switches off, the rest still works.
- A generated course whose data fails the checks (a step with no answer, a skill nobody uses): rejected before any student sees it.
- Nothing left that fits the rules: relax them in order (a different difficulty, then a problem seen earlier today, then any skill), and if AI generation is switched on, a generated variant. Never come up empty while any problem exists.

## How we'll know it works

- **It finds the struggle.** With test students, the step the engine flags as weak matches what the student says they struggled with in most practice sessions (target: 4 of 5).
- **Learning, not volume.** Simulated students reach mastery in fewer steps with the engine's order than with a random or a fixed order. With real test students, scores on a short check at the end are higher than on the same check at the start.
- **Explainable.** Every pick has a reason a student understands.
- **Works for any course.** Swapping in a second course is a data change, not a code change, and everything still works.
- **Good for its builder first.** Jonathon practices with it for his own Physics C test and finds the problems and the follow-ups useful before anyone else tries it.
- **Demo-able.** A stranger can try it for fifteen minutes at a check-in with no explanation from us.
- **No personal data.** The data holds nicknames only, no names, emails or ages.

## Not in the first version

- Plugging into Grassroot's platform (see *If it ever plugs into Grassroot*)
- Teaching lessons; this is practice only
- Grading essays or free-text answers; steps are choices, numbers, or ordering
- Teacher or parent reports
- Adjusting the mastery method's settings using real student data

## Constraints

- **Money:** $0 to start. Asking an AI service to generate courses or problem variants costs money each time, so it stays switched off unless we turn it on.
- **Time:** 12+ weeks at 4 to 6 hours a week, roughly 50 to 70 hours.
- **Tools:** Python 3.12. Data in one local file on this computer (SQLite).
- **Data:** nicknames only, no emails or ages, so test students can be anyone. The record exists to improve the engine and is deleted on request.

## Decisions so far

Each with the strongest argument against it, so future-us knows why.

1. **A standalone project with a subject-blind engine.** The engine knows nothing about physics or math. A course is data: skills, which skill depends on which, and problems made of steps, each step tagged with one skill. *Against:* without Grassroot's real students, we can't prove it works at their scale. *Safeguard:* test students plus simulated students, and a small fixed set of requests (see *If it ever plugs into Grassroot*) so plugging in later means connecting, not rebuilding.
2. **Problems are step by step, each step checkable, one skill per step.** A wrong step shows exactly where the student is stuck, which a single right-or-wrong answer never can. A step that would need two skills is split into two steps. *Against:* writing step-by-step problems is slower than writing multiple choice, and some subjects resist being cut into checkable steps. *Safeguard:* a one-step problem is allowed, and generation (decision 5) does the bulk writing later.
3. **Mastery per skill as a number from 0 to 1, kept by a standard, explainable method (Bayesian Knowledge Tracing: a few fixed numbers nudge the estimate up after a right step and down after a wrong one), updated after every step.** Works from the first answer and learns nothing from student data; its numbers are set by hand. *Against:* the hand-set numbers may be wrong for our problems. *Safeguard:* test on simulated students before real ones; adjust later if needed. *Tightened 2026-11-20 after a research review (report: "Evidence for adaptive practice design"):* only a student's first try counts as evidence, and a right first try after a hint counts as half a right answer (Jonathon, 2026-11-20); the numbers are set so mastery takes about 4 to 6 right steps, not 3 inside one problem; "mastered" means 0.95 plus the last 3 first tries right. *Against:* a student who learns from the hint gets no credit until the next problem. *Safeguard:* the next problem gives that credit, and T6 tunes the numbers.
4. **Next-problem rules:** skills the student is partway through come first (mastery roughly 0.3 to 0.85), prerequisites before what depends on them, revisit skills that are fading, prefer problems at the student's difficulty level, each batch of next problems covers two or three skills, never repeat within a day, always attach a reason. *Against:* rules can feel rigid. *Safeguard:* the rules are a short list we can change in one place, and every pick is recorded with its reason. *Updated 2026-11-20 from the same research:* mastered skills come back for review after 1, 3, 7, 14 and 30 days; a student stuck on a skill for about 8 steps is sent to its weakest prerequisite; problems are chosen so the student should get about 70 to 85% of the steps right; a batch mixes skills and principles. *Against:* the 70 to 85% target and the review gaps are educated guesses, not tested on students. *Safeguard:* named numbers in one place, tuned in T6 and T8.
5. **Courses and problem variants can be generated by an AI model, but only into the engine's data format and only after automatic checks.** *Against:* a generated problem with a wrong answer teaches the wrong thing. *Safeguard:* checks before use; generated problems are marked as generated, and a person looks them over. Which AI service, and its cost, is an open question.
6. **A web page that mocks Grassroot.** The student practices in a page that looks like Grassroot; only practice works. The page must be easy to use and must show *why* each follow-up problem was picked. Jonathon uses it himself first and keeps redesigning it until it feels right; test users come after (the first design will not be the last). *Against:* building a page costs time the engine could use. *Safeguard:* the rest of the mock stays fake, and the engine works without the page, so tests do not depend on it.
7. **Python 3.12 with SQLite.** The hard part is the mastery method and checking that it works, which Python is best at. A small web server (FastAPI) is already set up for when a page or a plug-in needs it. *Against:* a second programming language would be needed if Grassroot's app is written in TypeScript and this ever plugs in. *Safeguard:* the four requests in *If it ever plugs into Grassroot* are few enough to rebuild in another language.
8. **No personal data.** Nicknames only, delete on request. *Against:* none worth the risk.
9. **Every problem starts with "Which principle applies?", and every wrong option says why it is wrong.** Experts sort physics problems by principle, beginners by surface features; and feedback that explains why helps far more than right/wrong alone. Typed numbers accept "1,400" and a copied minus sign, and unreadable text asks the student to retype instead of counting as wrong. (Decided 2026-11-20.) *Against:* longer problems and more writing per problem. *Safeguard:* the course checker refuses a wrong option without its message, so none are forgotten.
10. **A skill that every problem practices is tracked but is never the reason a problem is picked; and when no problem fits the 70 to 85% target, the easiest difficulty comes first.** (Jonathon, 2026-11-20.) *Against:* easy problems dominate until a student is fairly strong (about 0.75 mastery). *Safeguard:* T6 tests whether that slows learning.

## If it ever plugs into Grassroot

Grassroot's platform would talk to the engine with four kinds of request, each carrying an anonymous student id and a secret code that proves it is Grassroot: record a step answer, get the next problems (with reasons), get the student's mastery per skill, and forget a student. At that point Grassroot's rules apply in full: no personal data in the engine, children's and students' data laws (COPPA, FERPA), deletion within 60 days, data stored in Postgres (the database system Grassroot uses) instead of the local file, and Grassroot's public promise that learner data is never used to train AI models. Nothing in the current plan conflicts with those.

## Similar work, and what we take from it

Looked up 2026-11-18. None of these changes the plan; each is something to borrow at a named step.

- **OATutor** (UC Berkeley, open source, github.com/CAHLR/OATutor). The closest thing to this project: a free tutor that keeps mastery per skill with the same method as decision 3, and by default picks the problem whose skills the student is weakest at. **How we differ:** its steps usually ask only for the final answer, while ours cut each problem into small steps with one skill each; we also add prerequisites, a reason for every pick, and timing. **Use at:** T3 (its "weakest skill first" rule as a starting point).
- **pyBKT** (same Berkeley group, a free Python tool). Works out the four fixed numbers behind decision 3 from real answers instead of setting them by hand, and can make up simulated students. **Use at:** T6 (simulated students), and later to check the hand-set numbers.
- **Math Academy's "credit flows down" idea.** Getting a hard step right is also quiet practice of the easier skills underneath it, so it can count a little toward them; a miss casts doubt on what is built on top. **Use at:** T2 or T3; see the open question below.
- **Eedi's misconception data.** Each wrong option in a multiple-choice question is a specific common mistake, such as forgetting that friction's work is negative. Then a wrong pick says *why* the student is stuck, not only *that* they are. **Use at:** T1b (write wrong options this way), T8 (compare with what students say they struggled with).
- **SymPy** (a free Python tool that does algebra). It can solve an equation by itself, so a generated problem's answer can be checked automatically before any student sees it. **Use at:** T7, as part of the checks in decision 5.

## Open questions

- [x] Which subject for the first hand-made sample course? **AP Physics C: Mechanics, energy and momentum** (Units 3 and 4, plus center of mass), the unit Jonathon is studying now, so he can judge the problems and test them on his own exam. The mentor found linear equations too simple. Problems are ours (or AI-written and checked); course material is Grassroot's job, not ours. (Decided 2026-11-14, changed 2026-11-19 after the mentor meeting)
- [ ] How often are check-ins, and what does the mentor want to see first? (Jonathon + mentor)
- [ ] Which AI service for generating courses and variants, and do we have an account with it (which gives a secret access code, the key) and a budget? Needed by step T7. (Jonathon)
- [x] Web page or not? Yes: a page that mocks Grassroot, with only practice working. (Mentor, 2026-11-19)
- [ ] How many test students can we get, and when? Needed by step T8. (Jonathon)
- [ ] Should this eventually plug into Grassroot? Ask once there is something to show. (mentor)
- [x] When a student gets a step right, should the skills underneath it also rise a little? Not for now: the only support is company claims, not studies. Revisit after T6. (2026-11-20)
