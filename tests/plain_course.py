"""The physics course for the engine's own tests, with problem push_cart frozen.

The real course's problems change as they are improved (and push_cart became a
template with changing numbers on 2026-11-27). Many tests need one small problem
whose numbers never change, so this copies the real course and puts back the
original push_cart (tests/fixtures/push_cart_fixed.json): step 1 is a choice
(choose_principle), step 2 the number 30 (work_constant_force), step 3 the number
5.48 within 0.05 (kinetic_energy). Tests about the real course itself load the real
file instead.
"""

import json
import tempfile
from pathlib import Path

REAL_COURSE = (
    Path(__file__).resolve().parents[1] / "data" / "ap-physics-c-energy-momentum" / "course.json"
)
_FIXED = Path(__file__).resolve().parent / "fixtures" / "push_cart_fixed.json"


def _build() -> Path:
    course = json.loads(REAL_COURSE.read_text(encoding="utf-8"))
    fixed = json.loads(_FIXED.read_text(encoding="utf-8"))
    course["problems"] = [fixed if p["id"] == "push_cart" else p for p in course["problems"]]
    folder = Path(tempfile.mkdtemp(prefix="practice-tests-"))
    path = folder / "course.json"
    path.write_text(json.dumps(course, ensure_ascii=False), encoding="utf-8")
    return path


COURSE = _build()
