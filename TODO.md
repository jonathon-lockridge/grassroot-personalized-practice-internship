# To do

*Small steps, each testable on its own. One at a time. Update this at the start and end of every session.*

## Now (one step only)

- [ ] **T1 Define the data and load a sample course.** Describe a Skill, a Problem, an Attempt and a learner's MasteryState in code (`src/practice_engine/models.py`). Add `data/sat_math/skills.json` (10 to 15 skills with prerequisites) and `data/sat_math/items.sample.json` (about 30 tagged problems). **Done when:** a test loads both files, every problem's skills exist, and no skill is its own prerequisite through a loop.

## Next

- [ ] **T2 Mastery update.** A function that takes a learner's mastery state and one attempt and returns the new state. No web or database code in it. **Done when:** tests show mastery rises on a correct answer, falls on a wrong one, stays between 0 and 1, moves less for a sub-3-second wrong answer, and matches a hand-computed example.
- [ ] **T3 Storage.** Save learners, attempts and mastery in SQLite; a Postgres address works with the same code. **Done when:** the same attempt sent twice is stored once and updates mastery once.
- [ ] **T4 Next-set rules.** Partway-through skills first, prerequisites before what depends on them, revisit fading skills, mix two or three skills, no repeats within 24 hours, a reason per pick, a diagnostic set for new learners. **Done when:** tests cover a new learner getting a diagnostic, a weak skill coming first, an unmet prerequisite redirecting, and a non-empty set whenever problems exist.
- [ ] **T5 The four calls.** Record an answer, next set, mastery picture, forget a learner, each requiring the secret key; requests containing a name or email are refused. **Done when:** all four work with the right key, a wrong key is refused, and a request with personal fields is refused.
- [ ] **T6 Does it actually help?** Simulated learners with hidden true mastery: compare these rules against random and fixed-order practice on how many attempts it takes to reach mastery; then replay real exported data. **Done when:** a command prints the comparison and the rules beat random.
- [ ] **T7 AI-generated variants, switched off by default.** Variants of existing problems (same skill and difficulty), checked automatically, saved as generated and unreviewed. **Done when:** a variant that fails the check is never shown, and a passing one carries the flags.
- [ ] **T8 Agree the interface and get real data.** Settle the four calls with the cofounder; write a script that exports anonymized attempts from the platform's database. **Done when:** the cofounder can run it and we have a real dataset for T6.
- [ ] **T9 Put it online.** A small Python host (Railway or Render) and a Postgres database, with secrets in the host's settings. **Done when:** the health check answers at the public address and the T5 checks pass against it.

## Later

- Estimate each problem's difficulty from data (needs the data-use decision in PRD.md)
- Use misconception tags from Learn mode as extra signals
- Design the real-learner comparison and decide the measure before running it
- Parent and teacher mastery report

## Done

- [x] 2026-11-12 Project setup: plan, to-do list, repository, automatic checks, health endpoint with a test.
