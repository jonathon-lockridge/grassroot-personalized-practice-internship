# Grassroot Personalized Practice

Product design internship project at [Grassroot Academy](https://grassroot.academy): practice that adapts to the student.

Problems are solved step by step, and each step is tagged with a skill, so a wrong step shows exactly where a student is stuck. The engine (the part of the program that decides) uses that to estimate what the student has mastered and to choose the next problem on purpose, with a plain-language reason. It knows nothing about any subject, so any course can be loaded into it, including courses generated from a topic or notes.

This is an independent project, reviewed with Grassroot's cofounder as mentor. It is designed so it could plug into Grassroot's platform later, but it does not depend on it.

## Where things stand

The plan is [PRD.md](PRD.md). The work is small steps in [TODO.md](TODO.md), and step T1b is next. So far: the shapes of a course and a checker that finds faults in a course file (`src/practice_engine/models.py`), a tiny two-problem algebra course (`data/linear-equations/course.json`), 28 tests, and a placeholder web server. Written in Python 3.12. Data will live in one local file (SQLite; step T5). A small web server (made with a tool called FastAPI) is already set up for when a web page, or a connection to Grassroot, needs it.

## Running it

Needs two free tools installed: Git and Python 3.12 or newer (check with `python3 --version`). Type these lines one at a time into the Terminal app, the Mac's text command window. If you already have the project folder, skip the first two lines and open the terminal inside that folder.

```bash
git clone https://github.com/jonathon-lockridge/grassroot-personalized-practice-internship.git   # downloads the project
cd grassroot-personalized-practice-internship                # go into its folder
cp .env.example .env             # make your own copy of the settings file
python3 -m venv .venv            # a private folder of tools just for this project
source .venv/bin/activate        # use that folder from now on (Windows: .venv\Scripts\activate)
pip install -e ".[dev]"          # install the project and its tools into it
pytest -q                        # runs the tests; expect "passed"
uvicorn practice_engine.api:app --reload   # starts the web server and keeps the terminal busy
```

Then open http://127.0.0.1:8000/health in a browser. The page should say `{"status": "ok", ...}`. To stop the server, go back to the terminal and press Ctrl+C.

Three things that look wrong but aren't: files whose names start with a dot, such as `.env.example`, are hidden in Finder and in plain `ls` (use `ls -a`); `pip install` prints a long list of lines, and only the final "Successfully installed" matters; a yellow notice about a newer pip can be ignored.

`.env` will hold secrets, such as the access code (key) a paid AI service gives you, and is never uploaded. `.env.example` shows the setting names with safe defaults; nothing in it is needed before step T5.

## How changes are made

One step from [TODO.md](TODO.md) at a time. Each step is tested, then recorded in the project's history with a note that says what changed and why. Before recording, run the same checks GitHub will run:

```bash
ruff format . && ruff check . && pytest -q
```

On every upload, GitHub installs the project, runs those code checks and tests, and checks that no `.env` file or secret was saved by accident.
