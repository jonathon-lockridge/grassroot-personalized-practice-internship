# To do

*Small steps, each testable on its own. One at a time. Update this at the start and end of every work session.*

## Now (one step only)

- [ ] **T1b Review the physics course.** Subject changed on 2026-11-19 (mentor meeting): AP Physics C: Mechanics, energy and momentum, in `data/ap-physics-c-energy-momentum/course.json`. It has 17 skills and 24 problems (7 easy, 9 medium, 8 hard), each starting with a "which principle applies?" step, and every wrong option says why it is wrong. Every number answer was recomputed by computer and checked by a second reviewer (its five small fixes are in). Number steps can now have a `tolerance` (how far off a typed answer may be and still count). Jonathon's part: work every problem on paper as test practice, using the step checklist below, and note any step that is wrong, unclear, too easy or missing a case from class. **Done when:** every note is fixed and the tests pass.
  - Step checklist (agreed 2026-11-16):
    1. Solve the problem yourself on paper.
    2. For each step, ask whether a student could do something else and still be right. If so, reword the question or change the problem.
    3. For a choice step, make sure every wrong option really is wrong, ideally a common mistake.
    4. Check the final answer makes physical sense (units, sign, size).
    5. Use the method your class teaches.

## Next

- [ ] **T4 Practice page in a Grassroot mock.** A web page that looks like Grassroot, with everything fake except practice. The student answers each step, gets the T1c check and a hint on a miss (decide here whether they get a second try), and sees mastery per skill. When a problem is a follow-up, the page shows it clearly (for example a "Picked for you" tag naming the skill and the step that went wrong). Jonathon uses it himself and redesigns until it feels right. **Done when:** Jonathon can do three problems from first step to last, and each follow-up's reason is visible and makes sense to him.
- [ ] **T7 Generate a course from a topic or notes.** An AI model writes skills, prerequisites and step-by-step problems in the course file format; the T1a checker rejects bad output; generated problems are marked as generated, for a person to look over. Needs the AI-service decision in PRD.md; also extend the secret check in `.github/workflows/ci.yml` to that service's key format. **Done when:** a generated course passes the same checks as the hand-made one and a person can practice it in T4's walkthrough.
- [ ] **T8 Try it on real people.** A handful of friends or classmates under nicknames. Each does the same short check of five questions before and after. For each practice session, compare the step the engine flagged as weak with what the student says they struggled with. **Done when:** at least five sessions are logged, and how often they matched (the hit rate) and the before-and-after scores are written down, with what to fix.
- [ ] **T9 Make it presentable.** Polish the Grassroot mock using what T8 and the check-ins showed, plus a short write-up of the results from T6 and T8. **Done when:** a stranger can try it for fifteen minutes without help.

## Later

- Estimate each problem's difficulty from data instead of setting it by hand
- Plug into Grassroot's platform through the four requests in PRD.md, if the mentor wants it
- Teacher or parent mastery report
- Once there is enough real data, train a neural knowledge-tracing model (PyTorch) and compare it with the Bayesian one

## Done

- [x] **T6 Does it actually help? (done 2026-11-26).** Simulated students compare the engine's order with random and an expert order (`python -m practice_engine.simulate`). **Done when** (Jonathon, 2026-11-26): with realistic students, who need the basics first, the engine beats both other orders on how many learn every skill and on how much they know after 100, 200 and 300 steps, on two seeds; with the simpler students, on how many learn every skill. Result: realistic students, 42 and 44 of 50 learned every skill against 22 and 23 for the expert order, and knew more at every checkpoint (seeds 1 and 7; seed 3, never used for tuning, agrees). Simpler students: 48 of 50 against 41.
- [x] **T5 Remember students between sessions (done 2026-11-22).** Save students (nicknames), step answers and mastery in one local file (SQLite); the same answer sent twice is stored once; a student can be forgotten. **Done when:** closing and reopening keeps a student's mastery, and forgetting removes every record about them.
- [x] **T1c Check an answer (done 2026-11-20).** A piece of code that is given a step and what the student typed or picked, and says right or wrong by the rules of the step's kind. **Done when:** tests cover a right and a wrong answer for each of the three kinds.
- [x] **T2 Mastery update (done 2026-11-20).** In `models.py`, describe a student's MasteryState (nickname, and one number from 0 to 1 per skill) and a StepAnswer (student, problem id, step position, right or wrong, seconds taken, hints used, when). Then, in a new file `src/practice_engine/mastery.py`, a piece of code that is given a MasteryState and one StepAnswer and gives back the updated state. It must not touch the web server or stored data. **Done when:** tests show mastery rises on a correct step, falls on a wrong one, stays between 0 and 1, moves less for a wrong step answered in under 3 seconds, matches a hand-computed example, and a new student's state has one entry per skill at the starting value.
- [x] **T3 Next-problem rules (done 2026-11-20).** In a new file `src/practice_engine/selection.py`: partway-through skills first, prerequisites before what depends on them, revisit fading skills, prefer the student's difficulty level then the next one, each batch covers two or three skills, no repeats within a day, a reason per pick, a diagnostic set for new students, and the prerequisite rule switches off when a course has no prerequisite data. When nothing fits, relax the rules in order (difficulty, then repeats, then any skill). **Done when:** tests cover each rule and the list of next problems is never empty while any problem exists.
- [x] 2026-11-19 Algebra course removed (mentor: too simple); physics course written (see T1b).

- [x] 2026-11-12 Project setup: plan, to-do list, the project's home on GitHub, automatic checks on every upload, and a web address that answers "ok" (http://127.0.0.1:8000/health), with a test.
- [x] 2026-11-13 Plan rewritten around a standalone project with step-by-step problems and any-course support; T1 split into T1a, T1b and T1c with the course file format settled.
- [x] **T1a Shapes and checks** (done 2026-11-14). Subject then: algebra, solving linear equations (removed 2026-11-19). In a new file `src/practice_engine/models.py`, describe what a Course, a Skill, a Problem and a Step look like, and write two helpers: one that loads a course file, and one that checks it and lists every fault in plain English. Start a tiny course file with 2 skills and 2 problems that together use all three answer kinds.
  - A course is one file in a folder named after the course inside `data/` (for example `data/ap-physics-c-energy-momentum/course.json`). Fields, all lowercase: course `id`, `title`, `skills`, `problems`; skill `id`, `name`, `prerequisites` (a list of skill ids, may be empty); problem `id`, `prompt` (the scenario, such as the equation), `difficulty` (1 easy, 2 medium, 3 hard, set by hand), `steps` in order; step `prompt` (its question text), `kind`, `options` (choice only), `answer`, `hint` (exactly one, never empty), `skill` (one skill id; a step that needs two skills is split in two). Skill and problem ids are short lowercase words or digits joined by underscores, like `kinetic_energy`; the course id matches its folder name, like `ap-physics-c-energy-momentum`.
  - Three kinds of step. `choice`: `options` holds 2 or more short texts and `answer` is exactly one of them. `number`: `answer` is a whole number or has at most two decimals, the question states any unit in words, and the student's typed number must match exactly. `order`: `answer` lists the items in the correct order (2 or more, no repeats); the student sees them shuffled.
  - The checks: skill ids and problem ids are unique; every step's skill and every prerequisite names a real skill; every skill is used by at least one step; no chain of prerequisites leads back to where it started; every step follows the rules of its kind; every prompt and hint is non-empty.
  - **Done when:** `tests/test_models.py` loads the tiny course without error and the checker finds no fault in it, and three deliberately broken copies (a step naming a missing skill, two skills that are each other's prerequisite, a choice answer not among its options) each get a complaint.
