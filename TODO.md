# To do

*Small steps, each testable on its own. One at a time. Update this at the start and end of every work session.*

## Now (one step only)

- [ ] **T1b Grow the course.** Same file, by hand, taking skills and problem patterns from the OpenStax Elementary Algebra chapter on solving linear equations (free and openly licensed): 8 to 12 skills in a prerequisite chain (every skill except the first one or two lists one or two prerequisites), 10 to 15 problems of 3 to 4 steps each, about a third at each difficulty. Working method: write the skills first; write problems in a plain table (one line per step: question, kind, answer, hint, skill); turn the table into the file; solve every problem yourself to check each answer and hint; stop at 10 problems and add more only if time remains. Reusing one problem's steps with new numbers counts as a new problem. **Done when:** the T1a tests still pass and a new test asserts at least 8 skills and 10 problems. The file format is described at the top of `src/practice_engine/models.py` and in the T1a entry under Done.
  - Skill list (agreed 2026-11-15), in the order a student learns them. These go into `course.json` together with the problems that use them, because the checker complains about any skill no step uses.

    | id | name | depends on |
    |---|---|---|
    | `undo_addition` | Undo addition or subtraction on both sides | none |
    | `check_solution` | Check an answer by putting it back into the equation | `undo_addition` |
    | `undo_multiplication` | Undo multiplication or division on both sides | `undo_addition` |
    | `combine_like_terms` | Combine like terms on one side (3x + 2x becomes 5x) | `undo_addition` |
    | `two_step` | Solve a two-step equation, such as 2x + 3 = 11 | `undo_multiplication` |
    | `variables_both_sides` | Move the x terms to one side, such as 5x + 2 = 3x + 8 | `two_step`, `combine_like_terms` |
    | `distribute` | Remove brackets by multiplying in: 2(x + 3) becomes 2x + 6 | `combine_like_terms` |
    | `general_strategy` | Solve any linear equation: simplify, gather the x terms, then undo | `distribute`, `variables_both_sides` |
    | `clear_fractions` | Clear fractions by multiplying both sides by a common bottom number | `general_strategy` |
    | `clear_decimals` | Clear decimals by multiplying both sides by 10 or 100 | `clear_fractions` |

## Next

- [ ] **T1c Check an answer.** A piece of code that is given a step and what the student typed or picked, and says right or wrong by the rules of the step's kind. **Done when:** tests cover a right and a wrong answer for each of the three kinds.
- [ ] **T2 Mastery update.** In `models.py`, describe a student's MasteryState (nickname, and one number from 0 to 1 per skill) and a StepAnswer (student, problem id, step position, right or wrong, seconds taken, hints used, when). Then, in a new file `src/practice_engine/mastery.py`, a piece of code that is given a MasteryState and one StepAnswer and gives back the updated state. It must not touch the web server or stored data. **Done when:** tests show mastery rises on a correct step, falls on a wrong one, stays between 0 and 1, moves less for a wrong step answered in under 3 seconds, matches a hand-computed example, and a new student's state has one entry per skill at the starting value.
- [ ] **T3 Next-problem rules.** In a new file `src/practice_engine/selection.py`: partway-through skills first, prerequisites before what depends on them, revisit fading skills, prefer the student's difficulty level then the next one, each batch covers two or three skills, no repeats within a day, a reason per pick, a diagnostic set for new students, and the prerequisite rule switches off when a course has no prerequisite data. When nothing fits, relax the rules in order (difficulty, then repeats, then any skill). **Done when:** tests cover each rule and the list of next problems is never empty while any problem exists.
- [ ] **T4 A way to try it (format tentative).** The simplest thing that lets a person answer steps: probably a walkthrough in the terminal (the text command window) that asks each step, checks it with T1c, hints on a miss (decide here whether the student gets a second try), and prints mastery and reasons at the end. Decide here whether a web page is worth building. **Done when:** Jonathon can do three problems from first step to last and the printed reasons make sense.
- [ ] **T5 Remember students between sessions.** Save students (nicknames), step answers and mastery in one local file (SQLite); the same answer sent twice is stored once; a student can be forgotten. **Done when:** closing and reopening keeps a student's mastery, and forgetting removes every record about them.
- [ ] **T6 Does it actually help?** Fake students run by the computer, each with a real mastery level that we set but hide from the engine: compare the engine's order against random and fixed order on how many steps it takes to reach mastery; use numpy for the simulations. **Done when:** a command prints the comparison and the engine's order wins.
- [ ] **T7 Generate a course from a topic or notes.** An AI model writes skills, prerequisites and step-by-step problems in the course file format; the T1a checker rejects bad output; generated problems are marked as generated, for a person to look over. Needs the AI-service decision in PRD.md; also extend the secret check in `.github/workflows/ci.yml` to that service's key format. **Done when:** a generated course passes the same checks as the hand-made one and a person can practice it in T4's walkthrough.
- [ ] **T8 Try it on real people.** A handful of friends or classmates under nicknames. Each does the same short check of five questions before and after. For each practice session, compare the step the engine flagged as weak with what the student says they struggled with. **Done when:** at least five sessions are logged, and how often they matched (the hit rate) and the before-and-after scores are written down, with what to fix.
- [ ] **T9 Make it presentable.** Whatever the check-ins showed is needed: the web page if T4 said yes, otherwise a clean walkthrough and a short write-up of the results from T6 and T8. **Done when:** a stranger can try it for fifteen minutes without help.

## Later

- Estimate each problem's difficulty from data instead of setting it by hand
- Plug into Grassroot's platform through the four requests in PRD.md, if the mentor wants it
- Teacher or parent mastery report
- Once there is enough real data, train a neural knowledge-tracing model (PyTorch) and compare it with the Bayesian one

## Done

- [x] 2026-11-12 Project setup: plan, to-do list, the project's home on GitHub, automatic checks on every upload, and a web address that answers "ok" (http://127.0.0.1:8000/health), with a test.
- [x] 2026-11-13 Plan rewritten around a standalone project with step-by-step problems and any-course support; T1 split into T1a, T1b and T1c with the course file format settled.
- [x] **T1a Shapes and checks** (done 2026-11-14). Subject: algebra, solving linear equations, in `data/linear-equations/`. In a new file `src/practice_engine/models.py`, describe what a Course, a Skill, a Problem and a Step look like, and write two helpers: one that loads a course file, and one that checks it and lists every fault in plain English. Start a tiny course file with 2 skills and 2 problems that together use all three answer kinds.
  - A course is one file in a folder named after the course inside `data/` (for example `data/linear-equations/course.json`). Fields, all lowercase: course `id`, `title`, `skills`, `problems`; skill `id`, `name`, `prerequisites` (a list of skill ids, may be empty); problem `id`, `prompt` (the scenario, such as the equation), `difficulty` (1 easy, 2 medium, 3 hard, set by hand), `steps` in order; step `prompt` (its question text), `kind`, `options` (choice only), `answer`, `hint` (exactly one, never empty), `skill` (one skill id; a step that needs two skills is split in two). Skill and problem ids are short lowercase words or digits joined by underscores, like `undo_addition`; the course id matches its folder name, like `linear-equations`.
  - Three kinds of step. `choice`: `options` holds 2 or more short texts and `answer` is exactly one of them. `number`: `answer` is a whole number or has at most two decimals, the question states any unit in words, and the student's typed number must match exactly. `order`: `answer` lists the items in the correct order (2 or more, no repeats); the student sees them shuffled.
  - The checks: skill ids and problem ids are unique; every step's skill and every prerequisite names a real skill; every skill is used by at least one step; no chain of prerequisites leads back to where it started; every step follows the rules of its kind; every prompt and hint is non-empty.
  - **Done when:** `tests/test_models.py` loads the tiny course without error and the checker finds no fault in it, and three deliberately broken copies (a step naming a missing skill, two skills that are each other's prerequisite, a choice answer not among its options) each get a complaint.
