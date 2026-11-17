// Validation: the same test for the trained and the base model (per part, with the cases the training fixed
// and broke), and "Try it": one sentence for chosen models, nothing run in the home.

import { action, card, chips, el, input, state, t } from "./common.js";

export const PARTS = ["router", "control", "answers", "real", "wiki_answers"];

const scoreClass = (score, total) => {
  if (!total) return "";
  const share = score / total;
  return share >= 0.95 ? "good" : share >= 0.85 ? "ok" : "bad";
};
const count = (value) => (Array.isArray(value) ? value.length : value ?? 0);

/** The table of one comparison (compare.json or the results of a running evaluation). */
export function compareTable(report) {
  const rows = PARTS.filter((p) => report.parts?.[p]).map((p) => {
    const d = report.parts[p];
    const hasBase = d.base !== null && d.base !== undefined;
    const diff = hasBase ? d.trained - d.base : null;
    return el("tr", { "data-part": p },
      el("td", {}, t(`p_${p}`)),
      el("td", { class: scoreClass(d.trained, d.total) }, `${d.trained}/${d.total}`, el("span", { class: "small" }, d.trained_s ? ` ${d.trained_s} s` : "")),
      el("td", { class: hasBase ? scoreClass(d.base, d.total) : "" }, hasBase ? `${d.base}/${d.total}` : "—",
        el("span", { class: "small" }, d.base_s ? ` ${d.base_s} s` : "")),
      el("td", { class: diff > 0 ? "good" : diff < 0 ? "bad" : "" }, diff === null ? "—" : diff > 0 ? `+${diff}` : String(diff)),
      el("td", {}, `${count(d.fixed)} / ${count(d.broken)}`));
  });
  return el("table", { class: "results", "data-compare": "" },
    el("tr", {}, el("th", {}, t("part")), el("th", {}, t("trained")), el("th", {}, t("base")), el("th", {}, "±"),
      el("th", {}, `${t("fixed")} / ${t("broken")}`)), ...rows);
}

/** The broken cases of a run: what the training made worse (the most useful list after a run). */
function brokenCases(report) {
  const items = PARTS.flatMap((p) => (Array.isArray(report.parts?.[p]?.broken) ? report.parts[p].broken : [])
    .map((name) => `${t(`p_${p}`)}: ${typeof name === "string" ? name : JSON.stringify(name)}`));
  if (!items.length) return null;
  return el("details", {}, el("summary", { class: "hint" }, t("broken_cases", { count: items.length })),
    el("ul", { class: "samples" }, ...items.slice(0, 200).map((x) => el("li", {}, x))));
}

export function renderCompare() {
  const done = (state.status?.runs || []).filter((r) => r.compare);
  const active = state.status?.tests?.active;
  return el("div", { class: "stack" },
    el("p", { class: "hint" }, t("compare_hint", { test: active === "ha" ? t("test_ha") : active || "—" })),
    ...(done.length ? done.map((r) => card(r.name, "validation",
      el("p", { class: "hint" }, `${r.compare.trained} · ${r.compare.base}`), compareTable(r.compare), brokenCases(r.compare)))
      : [card(t("n_compare"), "validation", el("p", { class: "hint" }, t("no_compare")))]));
}

// --- try it ---------------------------------------------------------------------------------------------

const chosen = new Set();
let known = false;
let text = "";
let last = null;

function tryModels() {
  const names = [];
  for (const r of state.status?.runs || []) if (r.export) names.push(r.export.name);
  for (const m of Object.values(state.status?.model_settings || {})) if (m.baseline) names.push(m.baseline);
  return [...new Set(names)];
}

function results() {
  if (!last) return el("div", { "data-try-out": "" });
  return el("div", { class: "tiles", "data-try-out": "" }, ...Object.entries(last.models || {}).map(([model, r]) =>
    el("div", { class: "tile" }, el("div", { class: "name" }, model),
      el("div", { class: "value" }, r.topic || "?"), el("p", { class: "hint" }, r.router_s !== undefined ? `${r.router_s} s` : ""),
      r.control ? el("pre", { class: "terminal" }, JSON.stringify(r.control, null, 1) + (r.device ? `\n→ ${r.device}` : "")) : null,
      r.answer ? el("pre", { class: "terminal" }, r.answer) : null,
      r.error ? el("p", { class: "hint warn" }, r.error) : null)));
}

export function renderTry() {
  const names = tryModels();
  if (!known && names.length) { names.forEach((n) => chosen.add(n)); known = true; }
  const out = el("div", {}, results());
  const field = input(text, (value) => { text = value; }, { placeholder: t("try_placeholder"), "data-try-text": "" });
  const go = async (button) => {
    const result = await action("try", { text, models: [...chosen] }, button);
    if (result && result !== true) {
      last = result;
      out.replaceChildren(results());
    }
  };
  const button = el("button", { class: "btn primary", "data-try": "", onclick: (e) => go(e.currentTarget) }, t("try"));
  field.addEventListener("keydown", (e) => { if (e.key === "Enter") go(button); });
  return card(t("try_title"), "try",
    names.length ? chips(names.map((n) => [n, n]), chosen) : el("p", { class: "hint" }, t("no_try_models")),
    el("div", { class: "row" }, field, button), out);
}
