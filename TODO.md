# To do

*Small steps, each testable on its own. One at a time. Update this at the start and end of every session.*

## Now (one step only)

- [ ] **T1 Define the data and write a sample course.** Describe in code what a Course, a Skill, a Problem with ordered Steps (each step: the prompt, the kind of answer, the correct answer, a hint, a skill) and a student's MasteryState look like (`src/practice_engine/models.py`). Write one small sample course by hand in `data/<course>/` (8 to 12 skills, 10 to 15 step-by-step problems; the subject is an open question in PRD.md). **Done when:** a test loads the course, every step points at a real skill, every step has a checkable answer, and no skill is its own prerequisite through a loop.

## Next

- [ ] **T2 Mastery update.** A function that takes a student's mastery state and one answered step and returns the new state. No web or database code in it. **Done when:** tests show mastery rises on a correct step, falls on a wrong one, stays between 0 and 1, moves less for a sub-3-second wrong step, and matches a hand-computed example.
- [ ] **T3 Next-problem rules.** Partway-through skills first, prerequisites before what depends on them, revisit fading skills, mix two or three skills, no repeats within a day, a reason per pick, a diagnostic set for new students, and the prerequisite rule switches off when a course has no prerequisite data. **Done when:** tests cover each rule and the set is never empty while problems exist.
- [ ] **T4 A way to try it (format tentative).** The simplest thing that lets a person answer steps: probably a terminal walkthrough that asks each step, checks it, hints on a miss, and prints mastery and reasons at the end. Decide here whether a web page is worth building. **Done when:** Jonathon can do three problems end to end and the printed reasons make sense.
- [ ] **T5 Remember students between sessions.** Save students (nicknames), step answers and mastery in a local SQLite file; the same answer sent twice is stored once; a student can be forgotten. **Done when:** closing and reopening keeps a student's mastery, and forgetting removes every row for them.
- [ ] **T6 Does it actually help?** Simulated students with hidden true mastery: compare the engine's order against random and fixed order on how many steps it takes to reach mastery. **Done when:** a command prints the comparison and the engine's order wins.
- [ ] **T7 Generate a course from a topic or notes.** An AI model writes skills, prerequisites and step-by-step problems in the engine's data format; automatic checks reject bad output; generated problems carry a flag. Needs the AI-service decision in PRD.md. **Done when:** a generated course passes the same test as the hand-made one and a person can practice it in T4's walkthrough.
- [ ] **T8 Try it on real people.** A handful of friends or classmates under nicknames. For each session, compare the step the engine flagged as weak with what the student says they struggled with. **Done when:** at least five sessions are logged and the hit rate is written down, with what to fix.
- [ ] **T9 Make it presentable.** Whatever the check-ins showed is needed: the web page if T4 said yes, otherwise a clean walkthrough and a short write-up of the results from T6 and T8. **Done when:** a stranger can try it for fifteen minutes without help.

## Later

- Estimate each problem's difficulty from data
- Plug into Grassroot's platform through the four requests in PRD.md, if the mentor wants it
- Teacher or parent mastery report

## Done

- [x] 2026-11-12 Project setup: plan, to-do list, repository, automatic checks, health endpoint with a test.
- [x] 2026-11-13 Plan rewritten around a standalone project with step-by-step problems and any-course support.
