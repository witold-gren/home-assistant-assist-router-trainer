// Training: start it (models, dataset, the parameters of this run), follow it live (GPU, steps, the loss of the
// training and the dev part), the job's log, and the runs with their export and evaluation.

import {
  action, ask, busy, call, card, chips, choice, copyButton, duration, el, facts, field, input, job, refill, select, state,
  t, toast, when,
} from "./common.js";
import { compareTable } from "./validation.js";

const chosenModels = new Set();
let modelsKnown = false;
const overrides = {};
let datasetName = "";
let thenExport = true;

const status = () => state.status || {};

// --- start --------------------------------------------------------------------------------------------

export function renderTrain() {
  const models = status().models || [];
  if (!modelsKnown && models.length) { models.forEach((m) => chosenModels.add(m)); modelsKnown = true; }
  const datasets = status().datasets || [];
  if (!datasetName && datasets.length) datasetName = datasets[datasets.length - 1].name;
  const settings = status().model_settings || {};
  const first = settings[[...chosenModels][0]] || {};
  const params = [["epochs", "epochs"], ["learning_rate", "lr"], ["lora_r", "lora_r"], ["lora_alpha", "lora_alpha"]]
    .map(([key, label]) => field(t(label), input(overrides[key] ?? "", (value) => { overrides[key] = value; },
      { type: "number", step: "any", placeholder: first[key] ?? "", "data-override": key })));
  const datasetChoice = datasets.length
    ? choice(datasets.map((d) => [d.name, `${d.name} · train ${d.train} · dev ${d.dev}`]), datasetName,
      (value) => { datasetName = value; }, { "data-dataset": "" })
    : el("p", { class: "hint warn" }, t("no_dataset"));
  const exportBox = el("input", { type: "checkbox", "data-then-export": "" });
  exportBox.checked = thenExport;
  exportBox.addEventListener("change", () => { thenExport = exportBox.checked; });
  const start = (resume) => async (event) => {
    const set = Object.fromEntries(Object.entries(overrides).filter(([, v]) => String(v).trim() !== "")
      .map(([k, v]) => [k, Number(v)]));
    const ok = await action("start", { kind: "train", dataset: datasetName, models: [...chosenModels], resume,
      then_export: thenExport, set }, event.currentTarget);
    if (ok) select("live");
  };
  const running = busy();
  return el("div", { class: "stack" },
    card(t("training_title"), "training",
      resumeNote(),
      field(t("dataset"), datasetChoice),
      field(t("models"), chips(models.map((m) => [m, m, (settings[m]?.base || "").split("/").pop()]), chosenModels, () => select("train"))),
      el("div", { class: "grid-2" }, ...params),
      el("p", { class: "hint" }, t("params_hint")),
      el("label", { class: "check" }, exportBox, el("span", {}, t("then_export"))),
      powerOffBox(),
      el("div", { class: "actions" },
        el("button", { class: "btn primary", "data-start": "", disabled: running || !datasets.length, onclick: start(false) },
          el("ha-icon", { icon: "mdi:play" }), t("start")),
        el("button", { class: "btn", "data-resume": "", disabled: running || !datasets.length, onclick: start(true) },
          el("ha-icon", { icon: "mdi:play-pause" }), t("resume")),
        stopButton()),
      el("p", { class: "hint" }, t("train_hint"))));
}

/** What Resume would really train, per chosen model: from which step, how many are left. */
function resumeNote() {
  const lines = [...chosenModels].map((model) => {
    const name = `${datasetName}-${model}`;
    const run = (status().runs || []).find((r) => r.name === name);
    const resume = run?.resume;
    if (!resume?.max_steps) return el("li", { "data-resume-note": name }, `${name}: ${t("resume_none")}`);
    const left = Math.max(0, resume.max_steps - (resume.step || 0));
    return el("li", { "data-resume-note": name, class: left ? "" : "warn" }, `${name}: `,
      left ? t("resume_from", { step: resume.step, max: resume.max_steps, left })
        : t("resume_nothing", { run: name, max: resume.max_steps }));
  });
  return datasetName && lines.length ? el("ul", { class: "hint resume-notes", "data-resume-notes": "" }, ...lines) : null;
}

/** "Switch the machine off after the job" in the start card too (the same setting as the right column). */
export function powerOffBox() {
  const ha = state.ha || {};
  if (!ha.power?.switch || !ha.url) return null;
  const box = el("input", { type: "checkbox", "data-power-after-start": "" });
  box.checked = Boolean(state.studio?.power_off?.after_training || state.studio?.power_off?.at);
  box.addEventListener("change", async () => {
    try {
      await call("power/off_after_training", { enabled: box.checked });
    } catch (err) {
      box.checked = !box.checked;
      toast(err.message, "error");
    }
  });
  return el("label", { class: "check" }, box, el("span", {}, t("side_power_off")));
}

export function stopButton() {
  return el("button", { class: "btn danger", "data-stop": "", disabled: !busy(), onclick: async (event) => {
    if (await ask(t("confirm_stop"), { danger: true })) action("stop", {}, event.currentTarget);
  } }, el("ha-icon", { icon: "mdi:stop" }), t("stop"));
}

// --- live ---------------------------------------------------------------------------------------------

function ring(value, max, text, warnAt, label) {
  const percent = value === null || value === undefined ? 0 : Math.max(0, Math.min(100, (100 * value) / max));
  const color = warnAt && percent >= warnAt ? "var(--warn)" : "var(--accent)";
  return el("div", { class: "meter" },
    el("div", { class: "ring", style: `--value: ${percent}; --color: ${color}` },
      el("span", {}, value === null || value === undefined ? "—" : text)),
    el("span", {}, label));
}

/** The stage, the time and the GPU's rings (the right column and the live view). */
export function liveCard() {
  const j = job();
  const progress = state.progress || {};
  const gpu = status().gpu;
  const end = j?.running ? Date.now() / 1000 : j?.finished || Date.now() / 1000;
  return el("section", { class: "card live-card", "data-live": "" },
    el("div", { class: "live-head" },
      el("div", {}, el("div", { class: "label" }, t("stage")),
        el("div", { class: "stage" }, progress.stage || (j ? j.title : "—"))),
      el("div", { class: "elapsed" }, el("div", { class: "label" }, t("elapsed")),
        el("div", {}, j?.started ? duration(end - j.started) : "—"))),
    el("div", { class: "gpu" },
      el("div", { class: "gpu-name" }, el("span", {}, t("gpu")), " ", el("strong", {}, gpu ? gpu.name : t("no_gpu"))),
      el("div", { class: "meters" },
        ring(gpu?.utilization, 100, `${Math.round(gpu?.utilization ?? 0)}%`, null, t("utilization")),
        ring(gpu?.memory_used, gpu?.memory_total || 1, `${((gpu?.memory_used ?? 0) / 1024).toFixed(1)}G`, 90, t("memory")),
        ring(gpu?.temperature, 95, `${Math.round(gpu?.temperature ?? 0)}°`, 85, t("temperature")),
        ring(gpu?.power, 480, `${Math.round(gpu?.power ?? 0)}W`, null, t("power")))));
}

const chartView = { range: null, pinned: null, overlay: null, points: [] };

/** Loss of the training (blue) and of the dev part (orange) against the step - one x axis for both. Hover shows a
 * step's values; in full screen dragging zooms in and a click pins a step. */
export function lossChart(points, { range = null, pinned = null, big = false, onRange = null, onPin = null } = {}) {
  const inRange = (p) => !range || (p.step >= range[0] && p.step <= range[1]);
  const shown = points.filter(inRange);
  const loss = shown.filter((p) => p.loss !== undefined && p.loss !== null);
  const evals = shown.filter((p) => p.eval_loss !== undefined && p.eval_loss !== null);
  if (loss.length < 2) return null;
  const W = big ? 1100 : 640, H = big ? 460 : 200, L = 44, R = 12, T = 10, B = 22;
  const steps = shown.map((p) => p.step);
  const minX = range ? range[0] : Math.min(...steps), maxX = range ? range[1] : Math.max(...steps);
  const values = [...loss.map((p) => p.loss), ...evals.map((p) => p.eval_loss)];
  const maxY = Math.max(...values) * 1.05, minY = Math.min(0, ...values);
  const x = (s) => L + ((s - minX) / Math.max(1, maxX - minX)) * (W - L - R);
  const y = (v) => T + (1 - (v - minY) / Math.max(1e-9, maxY - minY)) * (H - T - B);
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("data-loss-chart", big ? "big" : "");
  const add = (tag, attrs, text, parent = svg) => {
    const node = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (text) node.textContent = text;
    parent.append(node);
    return node;
  };
  for (const f of [0, 0.25, 0.5, 0.75, 1]) {
    const v = minY + f * (maxY - minY);
    add("line", { class: "grid", x1: L, x2: W - R, y1: y(v), y2: y(v) });
    add("text", { class: "axis", x: L - 6, y: y(v) + 3, "text-anchor": "end" }, v.toFixed(2));
  }
  const path = (list, key) => list.map((p, i) => `${i ? "L" : "M"}${x(p.step).toFixed(1)},${y(p[key]).toFixed(1)}`).join(" ");
  add("path", { class: "line-a", d: path(loss, "loss"), fill: "none", stroke: "var(--accent)", "stroke-width": 2 });
  if (evals.length > 1) add("path", { class: "line-b", d: path(evals, "eval_loss"), fill: "none", stroke: "var(--warn)", "stroke-width": 2 });
  for (const p of evals) add("circle", { cx: x(p.step), cy: y(p.eval_loss), r: 3, fill: "var(--warn)" });
  add("text", { class: "axis", x: L, y: H - 6 }, String(minX));
  add("text", { class: "axis", x: W - R, y: H - 6, "text-anchor": "end" }, String(maxX));

  // the values of the nearest step (hover) and of the pinned one
  const nearest = (step) => shown.reduce((best, p) => (Math.abs(p.step - step) < Math.abs(best.step - step) ? p : best), shown[0]);
  const lossAt = (step) => [...loss].reverse().find((p) => p.step <= step) || loss[0];
  const evalAt = (step) => [...evals].reverse().find((p) => p.step <= step);
  const describe = (step) => {
    const l = lossAt(step), e = evalAt(step);
    return `${t("step_of", { step, total: shown[shown.length - 1].max_steps ?? maxX })} · ${t("loss")} ${l ? l.loss.toFixed(4) : "—"}`
      + (e ? ` · ${t("eval_loss")} ${e.eval_loss.toFixed(4)}` : "");
  };
  const cursor = add("line", { class: "cursor", y1: T, y2: H - B, stroke: "var(--muted)", "stroke-dasharray": "3 3", visibility: "hidden" });
  const band = add("rect", { class: "zoom-band", y: T, height: H - T - B, fill: "var(--accent)", opacity: 0.12, visibility: "hidden" });
  const tip = el("div", { class: "chart-tip", "data-chart-tip": "", hidden: true });
  const pin = el("div", { class: "chart-pin", "data-chart-pin": "" }, pinned !== null ? describe(pinned) : "");
  if (pinned !== null && pinned >= minX && pinned <= maxX) {
    add("line", { class: "pinned", x1: x(pinned), x2: x(pinned), y1: T, y2: H - B, stroke: "var(--text)", "stroke-width": 1.5 });
  }
  const stepOf = (event) => {
    const box = svg.getBoundingClientRect();
    const px = ((event.clientX - box.left) / Math.max(1, box.width)) * W;
    return Math.round(minX + ((px - L) / (W - L - R)) * (maxX - minX));
  };
  let dragFrom = null;
  svg.addEventListener("mousemove", (event) => {
    const p = nearest(stepOf(event));
    cursor.setAttribute("x1", x(p.step));
    cursor.setAttribute("x2", x(p.step));
    cursor.setAttribute("visibility", "visible");
    tip.hidden = false;
    tip.textContent = describe(p.step);
    if (dragFrom !== null) {
      const a = Math.min(x(dragFrom), x(p.step)), b = Math.max(x(dragFrom), x(p.step));
      band.setAttribute("x", a);
      band.setAttribute("width", b - a);
      band.setAttribute("visibility", "visible");
    }
  });
  svg.addEventListener("mouseleave", () => { cursor.setAttribute("visibility", "hidden"); tip.hidden = true; });
  if (onRange || onPin) {
    svg.addEventListener("mousedown", (event) => { dragFrom = nearest(stepOf(event)).step; event.preventDefault(); });
    svg.addEventListener("mouseup", (event) => {
      const to = nearest(stepOf(event)).step, from = dragFrom;
      dragFrom = null;
      band.setAttribute("visibility", "hidden");
      if (from === null) return;
      if (Math.abs(to - from) >= 2 && onRange) onRange([Math.min(from, to), Math.max(from, to)]);
      else if (onPin) onPin(to);
    });
  }
  return el("div", { class: `chart ${big ? "big" : ""}` }, svg, tip, pin,
    el("div", { class: "legend" },
      el("span", {}, el("i", { style: "background: var(--accent)" }), t("loss")),
      el("span", {}, el("i", { style: "background: var(--warn)" }), t("eval_loss"))));
}

/** The chart in the live view: its title, "how to read" (the guide), full screen. */
function chartBlock(points) {
  chartView.points = points;
  const chart = lossChart(points);
  if (!chart) return null;
  const how = el("a", { class: "guide-link", target: "_blank", rel: "noopener", "data-chart-how": "",
    href: `/docs/${state.language === "pl" ? "pl" : "en"}/good-practice/#chart` }, t("chart_how"));
  const full = el("button", { class: "btn small", type: "button", "data-chart-full": "", onclick: openFullChart },
    el("ha-icon", { icon: "mdi:fullscreen" }), t("chart_fullscreen"));
  chart.querySelector("svg").addEventListener("click", openFullChart);
  return el("div", { class: "chart-block" },
    el("div", { class: "card-head" }, el("div", { class: "label" }, t("chart_title")), el("span", { class: "grow" }), how, full),
    chart);
}

function openFullChart() {
  chartView.range = null;
  chartView.pinned = null;
  chartView.overlay = el("div", { class: "dialog-backdrop chart-full", "data-chart-overlay": "",
    onclick: (event) => { if (event.target === chartView.overlay) closeFullChart(); } });
  document.body.append(chartView.overlay);
  drawFullChart();
}

function closeFullChart() {
  chartView.overlay?.remove();
  chartView.overlay = null;
}

function drawFullChart() {
  if (!chartView.overlay) return;
  const chart = lossChart(chartView.points, { big: true, range: chartView.range, pinned: chartView.pinned,
    onRange: (range) => { chartView.range = range; drawFullChart(); },
    onPin: (step) => { chartView.pinned = step; drawFullChart(); } });
  chartView.overlay.replaceChildren(el("div", { class: "dialog chart-dialog" },
    el("div", { class: "card-head" }, el("h2", {}, t("chart_title")), el("span", { class: "grow" }),
      chartView.range ? el("button", { class: "btn small", "data-chart-reset": "", onclick: () => { chartView.range = null; drawFullChart(); } },
        t("chart_reset")) : null,
      el("button", { class: "btn small", "data-chart-close": "", onclick: closeFullChart }, t("close"))),
    el("p", { class: "hint" }, t("chart_pin")),
    chart || el("p", { class: "hint" }, t("no_progress"))));
}

document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeFullChart(); });

/** What the log says so far: the generators' counters, the training steps and losses, results, problems. */
function progressParts() {
  const p = state.progress || {};
  const parts = [];
  const counters = Object.entries(p.counters || {});
  if (counters.length) {
    parts.push(el("div", { class: "counters" }, ...counters.map(([name, c]) => el("div", { class: "counter" },
      el("div", { class: "row" }, el("span", {}, name), el("span", {}, `${c.done}/${c.target}${c.rejected ? ` · −${c.rejected}` : ""}`)),
      el("div", { class: "bar" }, el("div", { style: `width:${Math.min(100, (100 * c.done) / Math.max(1, c.target))}%` }))))));
  }
  const metrics = p.metrics || [];
  if (metrics.length) {
    const last = metrics[metrics.length - 1];
    const lastLoss = [...metrics].reverse().find((m) => m.loss !== undefined);
    const lastEval = [...metrics].reverse().find((m) => m.eval_loss !== undefined);
    if (last.max_steps) {
      parts.push(el("p", { class: "hint" }, `${p.info?.base || ""} · ${t("step_of", { step: last.step, total: last.max_steps })}`),
        el("div", { class: "bar" }, el("div", { style: `width:${Math.min(100, (100 * last.step) / last.max_steps)}%` })));
    }
    parts.push(facts([t("loss"), lastLoss ? lastLoss.loss.toFixed(4) : null], [t("eval_loss"), lastEval ? lastEval.eval_loss.toFixed(4) : null],
      [t("examples"), p.info?.train ? String(p.info.train) : null], p.info?.skipped ? [t("skipped_long"), String(p.info.skipped), "warn"] : null));
    const chart = chartBlock(metrics);
    if (chart) parts.push(chart);
    if (chartView.overlay) { chartView.points = metrics; drawFullChart(); }
    const advice = overfitting(metrics);
    if (advice) parts.push(el("p", { class: "hint warn", "data-overfit": "" }, advice));
  }
  const results = Object.values(p.results || {});
  if (results.length) {
    parts.push(el("div", { class: "label" }, t("results_title")),
      compareTable({ parts: Object.fromEntries(results.map((r) => [r.part, r])) }));
  }
  if ((p.errors || []).length) {
    parts.push(el("div", { class: "label" }, t("errors")), el("pre", { class: "terminal" }, p.errors.join("\n")));
  }
  return parts.length ? parts : [el("p", { class: "hint" }, t("no_progress"))];
}

/** Dev loss rising twice in a row while the training loss falls: learning by heart. */
export function overfitting(metrics) {
  const evals = metrics.filter((m) => m.eval_loss !== undefined && m.eval_loss !== null);
  if (evals.length < 3) return null;
  const [a, b, c] = evals.slice(-3);
  return c.eval_loss > b.eval_loss && b.eval_loss > a.eval_loss ? t("overfit_advice") : null;
}

const live = { progress: null, shown: "" };

export function renderLive() {
  live.progress = el("div", { "data-progress": "" });
  live.shown = "";
  const view = el("div", { class: "stack" },
    el("div", { "data-live-slot": "" }, liveCard()),
    card(t("progress_title"), "live", live.progress),
    el("div", { class: "actions" }, stopButton()));
  updateLive(view);
  return view;
}

export function updateLive(view) {
  view.querySelector("[data-live-slot]")?.replaceChildren(liveCard());
  const shown = JSON.stringify([state.language, state.progress]);
  if (live.progress && shown !== live.shown) {
    live.shown = shown;
    live.progress.replaceChildren(...progressParts());
  }
  const stop = view.querySelector("[data-stop]");
  if (stop) stop.disabled = !busy();
}

// --- the job's log and the machine check -----------------------------------------------------------

function jobBadge() {
  const j = job();
  if (!j) return null;
  const kind = j.running ? "ok" : j.state === "ok" ? "good" : j.state === "stopped" ? "" : "bad";
  return el("span", { class: `badge ${kind}`, "data-job-state": j.state }, `${j.title || j.kind} · ${t(j.state)}`);
}

/** Earlier jobs (newest first) with their state and time; a click shows the job's whole log. */
function historyCard() {
  const list = el("div", { class: "job-history", "data-job-history": "" }, el("p", { class: "hint" }, t("loading")));
  const shown = el("pre", { class: "terminal", "data-job-history-log": "", hidden: true });
  call("jobs/history").then(({ jobs }) => {
    if (!jobs.length) return list.replaceChildren(el("p", { class: "hint" }, t("jobs_empty")));
    list.replaceChildren(el("table", { class: "table" },
      el("thead", {}, el("tr", {}, el("th", {}, t("jobs_title")), el("th", {}, t("jobs_when")), el("th", {}, t("jobs_took")), el("th", {}, ""))),
      el("tbody", {}, ...jobs.map((j) => el("tr", { "data-job-row": j.log },
        el("td", {}, j.title || j.kind),
        el("td", {}, j.started ? new Date(j.started * 1000).toLocaleString(state.language) : "—"),
        el("td", {}, j.started && j.finished ? duration(j.finished - j.started) : "—"),
        el("td", {}, el("span", { class: `badge ${j.state === "ok" ? "good" : j.state === "stopped" ? "" : "bad"}`, "data-job-history-state": j.state }, t(j.state)),
          " ", el("button", { class: "btn small", "data-job-history-open": j.log, onclick: async () => {
            try {
              shown.textContent = (await call("jobs/log", { log: j.log })).text || "—";
              shown.hidden = false;
            } catch (err) {
              toast(err.message, "error");
            }
          } }, t("jobs_log"))))))));
  }).catch((err) => list.replaceChildren(el("p", { class: "hint warn" }, err.message)));
  return el("section", { class: "card" }, el("div", { class: "card-head" }, el("h2", {}, t("jobs_title"))), list, shown);
}

export function renderJobs() {
  const log = el("pre", { class: "terminal tall", "data-log": "" }, state.log || "—");
  requestAnimationFrame(() => { log.scrollTop = log.scrollHeight; });
  const task = state.task;
  return el("div", { class: "stack" },
    el("section", { class: "card" }, el("div", { class: "card-head" }, el("h2", {}, t("log_title")), el("span", { "data-badge-slot": "" }, jobBadge())),
      el("div", { class: "terminal-wrap" }, copyButton(() => state.log || ""), log)),
    task ? el("section", { class: "card" }, el("div", { class: "card-head" }, el("h2", {}, t("task_title", { name: task.name }))),
      el("pre", { class: "terminal", "data-task": "" }, task.lines.join("\n"))) : null,
    historyCard());
}

export function updateJobs(view) {
  refill(view.querySelector("[data-log]"), state.log || "—");
  refill(view.querySelector("[data-task]"), (state.task?.lines || []).join("\n"));
  view.querySelector("[data-badge-slot]")?.replaceChildren(jobBadge() || "");
}

// --- runs ---------------------------------------------------------------------------------------------

const runs = () => status().runs || [];

function runLine(r) {
  const info = r.train_info;
  return [r.model, r.dataset, info ? `${t("trained_on")} ${info.minutes} ${t("minutes")}, loss ${Number(info.loss).toFixed(3)}` : r.checkpoint || ""]
    .filter(Boolean).join(" · ");
}

function runActions(r) {
  return el("div", { class: "actions" },
    el("button", { class: "btn", "data-export": r.name, disabled: !r.trained || busy(),
      onclick: (e) => action("start", { kind: "export", run: r.name }, e.currentTarget) }, el("ha-icon", { icon: "mdi:export-variant" }), t("export")),
    el("button", { class: "btn", "data-evaluate": r.name, disabled: !r.export || busy(),
      onclick: (e) => action("start", { kind: "evaluate", run: r.name }, e.currentTarget) }, el("ha-icon", { icon: "mdi:scale-balance" }), t("evaluate")));
}

export function renderRuns() {
  const list = runs();
  return card(t("runs"), "runs", list.length ? el("div", { class: "list" }, ...list.map((r) => el("div", { class: "item", "data-run": r.name },
    el("div", {}, el("a", { href: `#/run/${encodeURIComponent(r.name)}` }, el("strong", {}, r.name)), el("p", { class: "hint" }, runLine(r)),
      r.export ? el("span", { class: "badge good" }, r.export.name) : null),
    runActions(r)))) : el("p", { class: "hint" }, t("no_runs")));
}

export function renderRun(name) {
  const r = runs().find((run) => run.name === name);
  if (!r) return card(name, null, el("p", { class: "hint" }, t("no_runs")));
  const params = r.settings || {};
  const shown = ["epochs", "learning_rate", "lora_r", "lora_alpha", "batch_size", "grad_accum", "max_seq_length", "load_in_4bit"]
    .filter((k) => params[k] !== undefined);
  return el("div", { class: "stack" },
    card(r.name, "runs",
      el("p", { class: "hint" }, runLine(r)),
      facts(...shown.map((k) => [k, String(params[k])])),
      r.export ? el("p", {}, t("exported_as", { name: r.export.name })) : null,
      runActions(r)),
    r.compare ? card(t("results_title"), "validation", el("p", { class: "hint" }, `${r.compare.trained} · ${r.compare.base}`),
      compareTable(r.compare)) : null,
    r.created ? el("p", { class: "hint" }, t("run_created", { time: when(r.created) })) : null);
}
