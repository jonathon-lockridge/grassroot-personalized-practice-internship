// The practice page. It only shows things and sends the student's answers; the
// engine (the Python server) checks every answer, keeps mastery and picks problems.
// All text goes in with textContent, never as HTML, so no text can run as code.
"use strict";

const RULE_LABELS = {
  starting_check: "Starting check",
  follow_up: "Picked for you",
  stuck: "Picked for you",
  partway: "Keep going",
  review: "Review",
  new_skill: "New skill",
  relaxed: "More practice",
};
// Solid and stretch (PRD decision 12), said in plain words on the card itself.
const CHALLENGE_WORDS = {
  solid: "Should feel doable",
  stretch: "A stretch, worth it",
};
const LEVELS = { 1: "Easy", 2: "Medium", 3: "Hard" };
// How a symbol in an expression step looks, and what to type for it.
const SYMBOL_LOOKS = { theta: "θ", mu: "μ", alpha: "α", beta: "β", omega: "ω", phi: "φ", lambda: "λ", v0: "v₀", x0: "x₀" };
const SVG = "http://www.w3.org/2000/svg";
// The skills panel shows a level, not a raw number, so a new student does not read a
// column of low percentages as failing grades. ALMOST is the mastery number from which
// a skill shows as "Almost there"; "Mastered" comes from the engine's own rule.
const ALMOST = 0.6;

const state = {
  nickname: null,
  units: [], // [{title, lessons: [{id, title, skills, notes}]}] from the course file
  lesson: null, // the lesson open now: {id, title, skills, notes, unit}
  done: 0, // problems finished in this practice run, for "Problem 3" above a problem
  courseId: null,
  loading: false, // true while the next problem is on its way, so a double click sends one request
  mastery: [], // [{id, name, mastery, mastered, tried}] in course order
  problem: null, // the problem being worked, as the server sent it
  pick: null, // the pick that led to it
  stepIndex: 0, // which step is being answered, counting from 0
  attempt: 1, // 1 or 2: only one more try after a miss
  hintShown: false,
  order: null, // the current order step's items as the student has arranged them
  busy: false, // true while an answer is on its way to the engine
  stepStarted: 0, // when the current try started, in milliseconds
  results: [], // per step: {firstTryRight, firstHint, firstGiven, outcome, shown}
  levelsBefore: {}, // skill name -> {level, mastery} when the problem started
};

// ---------- small helpers ----------

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, "");
    else if (value !== false && value != null) node.setAttribute(key, value);
  }
  for (const child of children) {
    if (child == null) continue;
    node.append(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

const $ = (id) => document.getElementById(id);

async function api(path, body) {
  const options = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
  const response = await fetch(path, options);
  if (!response.ok) {
    const error = new Error(`The server said ${response.status} for ${path}.`);
    error.status = response.status;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") error.detail = body.detail; // a plain message
    } catch (ignored) {
      // no readable message; the caller says something general
    }
    throw error;
  }
  return response.json();
}

// Show one view and move the keyboard to its heading, since the button just pressed is
// usually hidden by the change. A problem's own first input takes focus instead.
const VIEW_HEADINGS = { "lesson-view": "lesson-title", "summary-view": "summary-title", "done-view": "done-title" };

function show(view) {
  $("page-error").hidden = true;
  for (const id of ["lesson-view", "problem-view", "summary-view", "done-view"]) $(id).hidden = id !== view;
  window.scrollTo({ top: 0 });
  if (VIEW_HEADINGS[view]) $(VIEW_HEADINGS[view]).focus({ preventScroll: true });
}

function percent(value) {
  return `${Math.round(value * 100)}%`;
}

function answerText(value) {
  return Array.isArray(value) ? value.join(" → ") : String(value);
}

function levelOf(skill) {
  if (skill.mastered) return "Mastered";
  if (!skill.tried) return "Not started";
  return skill.mastery >= ALMOST ? "Almost there" : "Learning";
}

// ---------- start ----------

// The browser may refuse site storage; remembering is only a convenience.
function remember(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(`practice-${key}`);
    localStorage.setItem(`practice-${key}`, value);
  } catch (error) {
    return null;
  }
  return null;
}

function showError(message) {
  const box = $("page-error");
  box.textContent = message;
  box.hidden = false;
}

async function init() {
  // Listeners first, so pressing Start early never falls back to a plain form send.
  $("start-form").addEventListener("submit", onStart);
  $("start-practice").addEventListener("click", startPractice);
  $("next-problem").addEventListener("click", loadNextProblem);
  $("next-lesson").addEventListener("click", () => openLesson(nextLesson().id));
  // Widening the window shows the full lesson list again.
  const wide = window.matchMedia("(min-width: 1001px)");
  wide.addEventListener("change", (event) => {
    if (event.matches) $("lesson-picker").open = true;
  });
  // On a wide screen the lesson list always shows, even if a key press tries to fold it.
  $("lesson-picker").addEventListener("toggle", () => {
    if (wide.matches && !$("lesson-picker").open) $("lesson-picker").open = true;
  });
  for (const button of document.querySelectorAll(".back-to-lesson")) {
    button.addEventListener("click", () => openLesson(state.lesson.id));
  }
  const saved = remember("nickname");
  if (saved) $("nickname").value = saved;
  try {
    const course = await api("/api/course");
    $("course-title").textContent = course.title;
    state.courseId = course.id;
    // A course with no units is practiced as one whole lesson.
    state.units = course.units.length ? course.units : [{
      title: course.title,
      lessons: [{ id: null, title: "Practice", skills: course.skills.map((s) => s.id), notes: [] }],
    }];
    $("start-button").disabled = false; // only now is there a lesson to open
  } catch (error) {
    $("course-title").textContent = "Could not reach the practice engine.";
    $("start-error").textContent = "Start the practice engine, then reload this page.";
  }
}

async function onStart(event) {
  event.preventDefault();
  const nickname = $("nickname").value.trim();
  $("start-error").textContent = "";
  let start;
  try {
    start = await api("/api/start", { nickname });
  } catch (error) {
    $("start-error").textContent = error.status === 422
      ? "That nickname did not work. Use 1 to 24 letters, digits, spaces, _ or -."
      : "Could not reach the practice engine. Is it running?";
    return;
  }
  state.nickname = start.nickname;
  remember("nickname", nickname);
  $("welcome").hidden = true;
  $("app").hidden = false;
  const who = $("who");
  who.hidden = false;
  who.replaceChildren(
    `${nickname} · `,
    el("button", { class: "btn quiet", type: "button", text: "change", onclick: () => location.reload() }),
  );
  state.mastery = start.mastery;
  openLesson(firstLesson());
}

// ---------- lessons ----------

function allLessons() {
  return state.units.flatMap((unit) => unit.lessons.map((lesson) => ({ ...lesson, unit: unit.title })));
}

// The saved lesson belongs to one student and one course.
function lessonKey() {
  return `lesson:${state.courseId}:${state.nickname}`;
}

// The lesson to open: the one this student last opened, unless they have mastered it, or
// else the first, in course order, with a skill they can start now (not mastered, and
// everything it builds on known).
function firstLesson() {
  const lessons = allLessons();
  const saved = lessons.find((lesson) => lesson.id === remember(lessonKey()));
  if (saved && !lessonDone(saved)) return saved.id;
  const startable = new Set(state.mastery.filter((s) => !s.mastered && s.ready).map((s) => s.id));
  const open = lessons.find((lesson) => lesson.skills.some((id) => startable.has(id)));
  return (open || lessons[0]).id;
}

function nextLesson() {
  const lessons = allLessons();
  const index = lessons.findIndex((lesson) => lesson.id === state.lesson.id);
  return lessons[index + 1] || null;
}

function lessonDone(lesson) {
  const mastered = new Set(state.mastery.filter((s) => s.mastered).map((s) => s.id));
  return lesson.skills.length > 0 && lesson.skills.every((id) => mastered.has(id));
}

function renderLessonNav() {
  $("lesson-nav").replaceChildren(
    ...state.units.map((unit) =>
      el(
        "div",
        { class: "lesson-unit-block" },
        el("p", { class: "lesson-unit", text: unit.title }),
        el(
          "ul",
          { class: "lesson-list" },
          ...unit.lessons.map((lesson) =>
            el(
              "li",
              {},
              el(
                "button",
                {
                  type: "button",
                  class: lesson.id === state.lesson?.id ? "lesson-link current" : "lesson-link",
                  "aria-current": lesson.id === state.lesson?.id ? "page" : null,
                  onclick: () => openLesson(lesson.id),
                },
                lesson.title,
                lessonDone(lesson) ? el("span", { class: "lesson-check", "aria-hidden": "true", text: " ✓" }) : null,
                lessonDone(lesson) ? el("span", { class: "visually-hidden", text: " (all skills mastered)" }) : null,
              ),
            ),
          ),
        ),
      ),
    ),
  );
}

function openLesson(lessonId) {
  state.lesson = allLessons().find((lesson) => lesson.id === lessonId);
  if (lessonId !== null) remember(lessonKey(), lessonId);
  $("lesson-unit").textContent = state.lesson.unit;
  $("lesson-title").textContent = state.lesson.title;
  $("lesson-notes").replaceChildren(...state.lesson.notes.map((note) => el("li", { text: note })));
  $("lesson-notes").hidden = !state.lesson.notes.length;
  renderLessonNav();
  $("lesson-picker-current").textContent = ` · ${state.lesson.title}`;
  // On a narrow screen the lesson list folds away once a lesson is chosen.
  $("lesson-picker").open = window.matchMedia("(min-width: 1001px)").matches;
  renderMastery(state.mastery);
  show("lesson-view");
}

function startPractice() {
  state.done = 0;
  loadNextProblem();
}

// ---------- skills panel ----------

function renderMastery(mastery, activeName = null) {
  state.mastery = mastery;
  const inLesson = new Set(state.lesson ? state.lesson.skills : []);
  const row = (skill) => {
      const level = levelOf(skill);
      const classes = ["skill-row"];
      if (skill.mastered) classes.push("mastered");
      if (skill.name === activeName) classes.push("active");
      const bar = el("span");
      bar.style.width = percent(skill.mastery);
      return el(
        "li",
        { class: classes.join(" ") },
        el(
          "div",
          { class: "skill-top" },
          el("span", { class: "skill-name", text: skill.name }),
          el("span", { class: "skill-level", text: skill.mastered ? "Mastered ✓" : level }),
        ),
        el("div", { class: "bar", "aria-hidden": "true" }, bar),
      );
  };
  $("mastery-lesson").replaceChildren(...mastery.filter((s) => inLesson.has(s.id)).map(row));
  $("mastery").replaceChildren(...mastery.filter((s) => !inLesson.has(s.id)).map(row));
  if (state.lesson) renderLessonNav(); // a lesson's ✓ can change after any answer
}

// ---------- the next problem ----------

async function loadNextProblem() {
  if (state.loading) return; // a double click must not ask twice
  state.loading = true;
  try {
    await fetchNextProblem();
  } finally {
    state.loading = false; // only once the problem is open (or failed)
  }
}

async function fetchNextProblem() {
  const lessonId = state.lesson.id;
  let next;
  try {
    next = await api("/api/lesson/next", { nickname: state.nickname, lesson_id: lessonId });
  } catch (error) {
    showError("Could not get your next problem. Try again in a moment.");
    return;
  }
  if (state.lesson.id !== lessonId) return; // the student opened another lesson meanwhile
  if (!next.pick) {
    const did = state.done ? `You did ${state.done} problem${state.done === 1 ? "" : "s"}. ` : "";
    $("done-line").textContent = `${did}That's all the fresh practice for this lesson today. Come back tomorrow, or try another lesson.`;
    $("next-lesson").hidden = !nextLesson();
    show("done-view");
    return;
  }
  await startProblem(next.pick);
}

function pickTags(pick) {
  return el(
    "div",
    { class: "pick-tags" },
    el("span", { class: pick.is_follow_up ? "chip follow" : "chip", text: RULE_LABELS[pick.rule] || pick.rule }),
    el("span", { class: `chip ${pick.challenge}`, text: CHALLENGE_WORDS[pick.challenge] }),
    state.lesson.skills.includes(pick.skill_id)
      ? null
      : el("span", { class: "chip", text: "From another lesson" }),
  );
}

function missedBox(pick) {
  if (!pick.missed) return null;
  return el(
    "p",
    { class: "missed-box" },
    el("strong", { text: `The step you missed, in “${pick.missed.problem_title}”: ` }),
    `step ${pick.missed.step_position} asked `,
    el("q", { text: pick.missed.step_prompt }),
  );
}

// ---------- working a problem ----------

async function startProblem(pick) {
  const lessonId = state.lesson.id;
  let problem;
  try {
    problem = await api(`/api/problems/${encodeURIComponent(pick.problem_id)}`);
  } catch (error) {
    showError("Could not open that problem. Try again in a moment.");
    return;
  }
  if (state.lesson.id !== lessonId) return; // the student opened another lesson meanwhile
  state.problem = problem;
  $("page-error").hidden = true;
  state.pick = pick;
  state.stepIndex = 0;
  state.results = [];
  state.levelsBefore = Object.fromEntries(
    state.mastery.map((s) => [s.name, { level: levelOf(s), mastery: s.mastery }]),
  );
  $("practice-count").textContent = `${state.lesson.title} · problem ${state.done + 1}`;
  $("problem-title").textContent = state.problem.title;
  $("problem-level").textContent = LEVELS[state.problem.difficulty];
  $("problem-prompt").textContent = state.problem.prompt;
  renderGraph(state.problem.graph);
  const banner = [pickTags(pick), el("p", { class: "why-plain", text: pick.reason }), missedBox(pick)];
  $("why-banner").replaceChildren(...banner.filter(Boolean)); // no missed step: no box
  show("problem-view"); // first, so the first answer box can take the keyboard
  startStep();
}

// A line graph from the problem's points, such as force against position. Drawn as
// SVG shapes made one by one, never from text, like the rest of the page.
function renderGraph(graph) {
  const box = $("problem-graph");
  box.hidden = !graph;
  if (!graph) {
    box.replaceChildren();
    return;
  }
  const W = 420, H = 240, left = 52, right = 16, top = 16, bottom = 44;
  const xs = graph.points.map((p) => p[0]);
  const ys = graph.points.map((p) => p[1]);
  const xMin = Math.min(0, ...xs);
  const xMax = Math.max(0, ...xs) > xMin ? Math.max(0, ...xs) : xMin + 1;
  const yMin = Math.min(0, ...ys);
  const yMax = Math.max(0, ...ys) > yMin ? Math.max(0, ...ys) : yMin + 1;
  const sx = (x) => left + ((x - xMin) / (xMax - xMin)) * (W - left - right);
  const sy = (y) => top + ((yMax - y) / (yMax - yMin)) * (H - top - bottom);
  const make = (tag, attrs, text) => {
    const node = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const label = (v) => (Math.abs(v - Math.round(v)) < 1e-9 ? String(Math.round(v)) : String(+v.toFixed(2)));
  const svg = make("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", class: "graph-svg", "aria-labelledby": "graph-title" });
  const description = graph.points.map((p) => `(${label(p[0])}, ${label(p[1])})`).join(", ");
  svg.append(make("title", { id: "graph-title" }, `${graph.y_label} against ${graph.x_label}: straight lines through ${description}`));
  // Gridlines at even steps (so areas can be counted), plus every point's own value.
  const niceStep = (span) => [0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000].find((s) => span / s <= 6) || span / 5;
  const ticks = (low, high, own) => {
    const step = niceStep(high - low);
    const even = [];
    for (let v = Math.ceil(low / step) * step; v <= high + 1e-9; v += step) even.push(+v.toFixed(6));
    const mine = own.map((v) => +v.toFixed(6));
    // An even tick too close to a point's own value would print on top of it.
    const clear = even.filter((v) => mine.every((m) => m === v || Math.abs(m - v) >= step * 0.4));
    return [...new Set([...clear, ...mine])].sort((a, b) => a - b);
  };
  const xTicks = ticks(xMin, xMax, xs);
  const yTicks = ticks(yMin, yMax, [0, ...ys]);
  for (const x of xTicks) {
    svg.append(make("line", { x1: sx(x), y1: top, x2: sx(x), y2: H - bottom, class: "grid" }));
    svg.append(make("text", { x: sx(x), y: H - bottom + 16, "text-anchor": "middle", class: "tick" }, label(x)));
  }
  for (const y of yTicks) {
    svg.append(make("line", { x1: left, y1: sy(y), x2: W - right, y2: sy(y), class: "grid" }));
    svg.append(make("text", { x: left - 6, y: sy(y) + 4, "text-anchor": "end", class: "tick" }, label(y)));
  }
  svg.append(make("line", { x1: left, y1: sy(0), x2: W - right, y2: sy(0), class: "axis" }));
  svg.append(make("line", { x1: sx(0), y1: top, x2: sx(0), y2: H - bottom, class: "axis" }));
  svg.append(make("polyline", { points: graph.points.map((p) => `${sx(p[0])},${sy(p[1])}`).join(" "), class: "plot" }));
  svg.append(make("text", { x: (left + W - right) / 2, y: H - 8, "text-anchor": "middle", class: "axis-label" }, graph.x_label));
  svg.append(make("text", { x: 14, y: (top + H - bottom) / 2, "text-anchor": "middle", class: "axis-label", transform: `rotate(-90 14 ${(top + H - bottom) / 2})` }, graph.y_label));
  box.replaceChildren(svg);
}

function startStep() {
  state.attempt = 1;
  state.order = null; // a new step starts from its own shuffled items
  state.hintShown = false;
  state.stepStarted = performance.now();
  renderSteps();
}

function renderSteps() {
  const steps = state.problem.steps;
  const items = [];
  for (let i = 0; i <= state.stepIndex && i < steps.length; i++) {
    items.push(i < state.stepIndex ? doneStep(steps[i], state.results[i]) : currentStep(steps[i]));
  }
  $("steps").replaceChildren(...items);
  const current = steps[state.stepIndex];
  renderMastery(state.mastery, current ? current.skill_name : null);
  const focus = $("steps").querySelector(".step.current input:not([disabled]), .step.current .order-item button:not([disabled])");
  // A choice step keeps the keyboard on its first option; a typed answer on its box.
  if (focus) focus.focus({ preventScroll: true });
}

function stepHead(step, mark) {
  // Mark the steps that practice the skill this problem was picked for, so the
  // reason above points at something the student can see while working.
  const target = step.skill_name === state.pick.skill_name
    ? el("span", { class: "chip follow small", text: "Picked for this skill" })
    : null;
  return el(
    "div",
    { class: "step-head" },
    el("span", { class: "step-num", text: `Step ${step.position} of ${state.problem.steps.length}` }),
    el("span", { class: "step-skill", text: step.skill_name }),
    target,
    mark,
  );
}

function doneStep(step, result) {
  let mark;
  if (result.outcome === "first") {
    const text = result.firstHint ? "✓ Right first try, with hint" : "✓ Right first try";
    mark = el("span", { class: "step-mark right", text });
  } else if (result.outcome === "second") {
    mark = el("span", { class: "step-mark", text: "Right on 2nd try" });
  } else {
    mark = el("span", { class: "step-mark wrong", text: "Answer shown" });
  }
  return el(
    "li",
    { class: "step done" },
    stepHead(step, mark),
    el("p", { class: "step-prompt", text: step.prompt }),
    el("p", { class: "step-given", text: `Answer: ${answerText(result.shown)}` }),
  );
}

function currentStep(step) {
  const form = el("form", { class: "step-form", onsubmit: (event) => onCheck(event, step) });
  const hintBox = el("p", { class: "hint", tabindex: "-1", hidden: !state.hintShown, text: `Hint: ${step.hint}` });
  const actions = el(
    "div",
    { class: "actions" },
    el("button", { class: "btn primary", type: "submit", text: "Check" }),
    state.hintShown ? null : el("button", {
      class: "btn",
      type: "button",
      text: "Show hint",
      onclick: (event) => {
        state.hintShown = true;
        hintBox.hidden = false;
        event.currentTarget.remove();
        hintBox.focus(); // the button is gone, so keep the keyboard on the hint
      },
    }),
  );
  // Answer, then what went wrong, then the hint, then the buttons.
  const slot = el("div", { class: "feedback-slot", role: "status", "aria-live": "polite" });
  form.append(answerInput(step), slot, hintBox, actions);
  return el(
    "li",
    { class: "step current" },
    stepHead(step, state.attempt === 2 ? el("span", { class: "step-mark", text: "One more try" }) : null),
    el("p", { class: "step-prompt", id: `prompt-${step.position}`, text: step.prompt }),
    form,
  );
}

function answerInput(step) {
  if (step.kind === "choice") {
    const name = `step-${step.position}`;
    return el(
      "fieldset",
      { class: "options" },
      el("legend", { class: "visually-hidden", text: step.prompt }),
      ...step.options.map((option) => {
        const tried = state.attempt === 2 && option === state.results[state.stepIndex]?.firstGiven;
        return el(
          "label",
          { class: "option" },
          el("input", { type: "radio", name, value: option, disabled: tried }),
          el("span", { text: tried ? `${option} (your first try)` : option }),
        );
      }),
    );
  }
  if (step.kind === "expression") {
    const symbols = step.symbols.map((s) => (SYMBOL_LOOKS[s] ? `${SYMBOL_LOOKS[s]} (type ${s})` : s));
    return el(
      "div",
      { class: "expression-box" },
      el("input", {
        type: "text",
        name: "expression",
        "aria-labelledby": `prompt-${step.position}`,
        "aria-describedby": `symbols-${step.position}`,
        placeholder: "type a formula",
        autocomplete: "off",
        autocapitalize: "off",
        spellcheck: "false",
      }),
      el(
        "p",
        { class: "small muted", id: `symbols-${step.position}` },
        `You can use: ${symbols.join(", ")}. Write * for times (2Fd also means 2·F·d), / to divide, ^ for powers, and sqrt( ), sin( ), cos( ).`,
      ),
    );
  }
  if (step.kind === "number") {
    return el(
      "div",
      { class: "number-row" },
      el("input", {
        type: "text",
        inputmode: "decimal",
        name: "number",
        "aria-labelledby": `prompt-${step.position}`,
        placeholder: "a number",
        autocomplete: "off",
      }),
      el("span", { class: "small muted", text: "Just the number, no units." }),
    );
  }
  // An order step: move items up and down until they are in order.
  const list = el("ol", { class: "order-list", "aria-labelledby": `prompt-${step.position}` });
  const order = state.order && state.order.position === step.position ? state.order.items : [...step.items];
  state.order = { position: step.position, items: order };
  const move = (from, to, direction) => {
    [order[from], order[to]] = [order[to], order[from]];
    draw();
    // Keep the keyboard on the item that moved: its same arrow, or the other if at an end.
    const row = list.children[to];
    const same = row.querySelector(`button[data-dir=${direction}]:not([disabled])`);
    (same || row.querySelector("button:not([disabled])")).focus();
  };
  const draw = () => {
    list.replaceChildren(
      ...order.map((item, i) =>
        el(
          "li",
          { class: "order-item" },
          el("span", { class: "order-text", text: item }),
          el("button", {
            type: "button", text: "↑", "data-dir": "up", "aria-label": `Move up: ${item}`, disabled: i === 0,
            onclick: () => move(i, i - 1, "up"),
          }),
          el("button", {
            type: "button", text: "↓", "data-dir": "down", "aria-label": `Move down: ${item}`,
            disabled: i === order.length - 1,
            onclick: () => move(i, i + 1, "down"),
          }),
        ),
      ),
    );
  };
  draw();
  return list;
}

function readGiven(form, step) {
  if (step.kind === "choice") {
    const picked = form.querySelector("input[type=radio]:checked");
    return picked ? picked.value : null;
  }
  if (step.kind === "number") {
    const typed = form.querySelector("input[name=number]").value.trim();
    return typed === "" ? null : typed;
  }
  if (step.kind === "expression") {
    const typed = form.querySelector("input[name=expression]").value.trim();
    return typed === "" ? null : typed;
  }
  return [...state.order.items];
}

function setFeedback(form, className, ...children) {
  form.querySelector(".feedback-slot").replaceChildren(
    el("div", { class: `feedback ${className}` }, ...children),
  );
}

async function onCheck(event, step) {
  event.preventDefault();
  const form = event.currentTarget;
  const given = readGiven(form, step);
  if (given === null) {
    const ask = { choice: "Pick one option first.", expression: "Type a formula first." };
    setFeedback(form, "retype", ask[step.kind] || "Type a number first.");
    return;
  }
  if (state.busy) return; // a double click must not send the same try twice
  state.busy = true;
  const seconds = Math.max(0, (performance.now() - state.stepStarted) / 1000);
  let result;
  try {
    result = await api("/api/answer", {
      nickname: state.nickname,
      problem_id: state.problem.id,
      step_position: step.position,
      given,
      seconds: Math.round(seconds * 10) / 10,
      hints_used: state.hintShown ? 1 : 0,
      attempt: state.attempt,
      started_at: state.problem.started_at,
      variant: state.problem.variant,
    });
  } catch (error) {
    const message = error.status === 409
      ? `${error.detail || "This step was already saved."} Go back to the lesson and start practice again.`
      : "Could not reach the practice engine. Try Check again.";
    setFeedback(form, "retype", message);
    return;
  } finally {
    state.busy = false;
  }
  if (!result.readable) {
    const messages = {
      number: "That could not be read as a number. Type just the number, like 5.48 or -240.",
      expression: `That formula could not be read. ${result.why || "Check the brackets and symbols."}`,
    };
    const message = messages[step.kind] || "That answer did not match this step. Pick from the choices shown.";
    setFeedback(form, "retype", message);
    return;
  }
  renderMastery(result.mastery, step.skill_name);
  if (state.attempt === 1) {
    state.results[state.stepIndex] = {
      firstTryRight: result.correct,
      firstHint: state.hintShown,
      firstGiven: given,
    };
  }
  const record = state.results[state.stepIndex];
  if (result.correct) {
    record.outcome = state.attempt === 1 ? "first" : "second";
    record.shown = given;
    return endStep(form, "right", "Right!");
  }
  if (!result.step_done) {
    // A wrong first try: say why, show the hint, and allow one more try.
    state.attempt = 2;
    state.hintShown = true;
    state.stepStarted = performance.now();
    renderSteps();
    const newForm = $("steps").querySelector(".step.current form");
    const typed = step.kind === "number" || step.kind === "expression" ? `You typed ${given}. ` : "";
    setFeedback(
      newForm,
      "wrong",
      el("strong", { text: "Not quite. " }),
      typed,
      result.why || "Read the hint below, then try once more.",
    );
    return;
  }
  // A wrong second try: show the right answer and move on.
  record.outcome = "shown";
  record.shown = result.right_answer;
  endStep(
    form,
    "wrong",
    el("strong", { text: "Not this time. " }),
    result.why ? `${result.why} ` : "",
    "The answer is ",
    el("strong", { text: answerText(result.right_answer) }),
    ".",
  );
}

function endStep(form, className, ...message) {
  for (const control of form.querySelectorAll("input, button")) control.disabled = true;
  const last = state.stepIndex === state.problem.steps.length - 1;
  const next = el("button", {
    class: "btn primary",
    type: "button",
    text: last ? "Finish problem" : "Next step",
    onclick: () => {
      if (last) return finishProblem();
      state.stepIndex += 1;
      startStep();
    },
  });
  setFeedback(form, className, ...message);
  form.querySelector(".feedback-slot").append(el("div", { class: "actions" }, next));
  next.focus();
}

// ---------- after a problem ----------

function finishProblem() {
  state.done += 1;
  const right = state.results.filter((r) => r.firstTryRight).length;
  const total = state.problem.steps.length;
  $("summary-title").textContent = `${state.problem.title}: done`;
  $("summary-line").textContent = `Right on the first try: ${right} of ${total} steps.`;
  const skillNames = [...new Set(state.problem.steps.map((s) => s.skill_name))];
  $("summary-skills").replaceChildren(
    ...skillNames.map((name) => {
      const now = state.mastery.find((s) => s.name === name);
      const before = state.levelsBefore[name];
      const level = levelOf(now);
      let text;
      let direction = "";
      if (level !== before.level) {
        text = `${before.level} → ${level}`;
        direction = now.mastery >= before.mastery ? "up" : "down";
      } else if (now.mastery > before.mastery + 0.005) {
        text = `still ${level}, moving up`;
        direction = "up";
      } else if (now.mastery < before.mastery - 0.005) {
        text = `still ${level}, slipped a little`;
        direction = "down";
      } else {
        text = `still ${level}`;
      }
      return el("li", {}, `${name}: `, el("span", { class: direction, text }));
    }),
  );
  renderMastery(state.mastery);
  show("summary-view");
}

init();
