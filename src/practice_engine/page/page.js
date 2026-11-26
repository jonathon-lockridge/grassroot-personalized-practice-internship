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
// The skills panel shows a level, not a raw number, so a new student does not read a
// column of low percentages as failing grades. ALMOST is the mastery number from which
// a skill shows as "Almost there"; "Mastered" comes from the engine's own rule.
const ALMOST = 0.6;

const state = {
  nickname: null,
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
    throw error;
  }
  return response.json();
}

function show(view) {
  $("page-error").hidden = true;
  for (const id of ["next-view", "problem-view", "summary-view"]) $(id).hidden = id !== view;
  window.scrollTo({ top: 0 });
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

// The browser may refuse site storage; remembering the nickname is only a convenience.
function remember(nickname) {
  try {
    if (nickname === undefined) return localStorage.getItem("practice-nickname");
    localStorage.setItem("practice-nickname", nickname);
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
  $("see-next").addEventListener("click", loadNext);
  const saved = remember();
  if (saved) $("nickname").value = saved;
  try {
    const course = await api("/api/course");
    $("course-title").textContent = course.title;
  } catch (error) {
    $("course-title").textContent = "Could not reach the practice engine.";
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
  remember(nickname);
  $("welcome").hidden = true;
  $("app").hidden = false;
  const who = $("who");
  who.hidden = false;
  who.replaceChildren(
    `${nickname} · `,
    el("button", { class: "btn quiet", type: "button", text: "change", onclick: () => location.reload() }),
  );
  renderMastery(start.mastery);
  renderPicks(start.picks);
}

// ---------- skills panel ----------

function renderMastery(mastery, activeName = null) {
  state.mastery = mastery;
  $("mastery").replaceChildren(
    ...mastery.map((skill) => {
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
    }),
  );
}

// ---------- next problems ----------

async function loadNext() {
  try {
    const next = await api("/api/next", { nickname: state.nickname });
    renderPicks(next.picks);
  } catch (error) {
    showError("Could not get your next problems. Try again in a moment.");
  }
}

function pickTags(pick) {
  return el(
    "div",
    { class: "pick-tags" },
    el("span", { class: pick.is_follow_up ? "chip follow" : "chip", text: RULE_LABELS[pick.rule] || pick.rule }),
    el("span", { class: `chip ${pick.challenge}`, text: CHALLENGE_WORDS[pick.challenge] }),
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

function renderPicks(picks) {
  const cards = picks.map((pick, index) =>
    el(
      "article",
      { class: `card pick${index === 0 ? " first" : ""}` },
      pickTags(pick),
      el("div", { class: "pick-title", text: pick.title }),
      el("p", { class: "pick-reason", text: pick.reason }),
      missedBox(pick),
      el(
        "div",
        { class: "actions" },
        el("button", {
          class: index === 0 ? "btn primary" : "btn",
          type: "button",
          text: index === 0 ? "Start" : "Do this one instead",
          onclick: () => startProblem(pick),
        }),
      ),
    ),
  );
  $("picks").replaceChildren(...cards);
  if (!picks.length) $("picks").append(el("p", { text: "No problems left to pick." }));
  renderMastery(state.mastery);
  show("next-view");
}

// ---------- working a problem ----------

async function startProblem(pick) {
  try {
    state.problem = await api(`/api/problems/${encodeURIComponent(pick.problem_id)}`);
  } catch (error) {
    showError("Could not open that problem. Try again in a moment.");
    return;
  }
  $("page-error").hidden = true;
  state.pick = pick;
  state.stepIndex = 0;
  state.results = [];
  state.levelsBefore = Object.fromEntries(
    state.mastery.map((s) => [s.name, { level: levelOf(s), mastery: s.mastery }]),
  );
  $("problem-title").textContent = state.problem.title;
  $("problem-level").textContent = LEVELS[state.problem.difficulty];
  $("problem-prompt").textContent = state.problem.prompt;
  const banner = [pickTags(pick), el("p", { class: "why-plain", text: pick.reason }), missedBox(pick)];
  $("why-banner").replaceChildren(...banner.filter(Boolean)); // no missed step: no box
  startStep();
  show("problem-view");
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
    setFeedback(form, "retype", step.kind === "choice" ? "Pick one option first." : "Type a number first.");
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
    });
  } catch (error) {
    const message = error.status === 409
      ? "This step was already saved. Go back to Up next and open the problem again."
      : "Could not reach the practice engine. Try Check again.";
    setFeedback(form, "retype", message);
    return;
  } finally {
    state.busy = false;
  }
  if (!result.readable) {
    const message = step.kind === "number"
      ? "That could not be read as a number. Type just the number, like 5.48 or -240."
      : "That answer did not match this step. Pick from the choices shown.";
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
    const typed = step.kind === "number" ? `You typed ${given}. ` : "";
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
