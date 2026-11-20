// Automatic training: one Start for the whole road (Home Assistant → test → data → training → export →
// comparison), the summary of the last run and "Use in Assist Router" after a confirmation.

import { action, ask, busy, card, chips, el, field, input, redraw, select, state, t, toast } from "./common.js";
import { powerOffBox, stopButton } from "./training.js";

const chosenModels = new Set();
let modelsKnown = false;
let datasetName = "";
let test = "ha";
let upload = true;
let routerOnly = true; // the small model chooses the topic; commands and answers stay with the answer model
let summary = null; // {summary, remembered} from the studio
let routerModel = null; // {model, choices} from Home Assistant
let loading = false;

const status = () => state.status || {};

function today() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `home-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`;
}

/** The summary and the router model in Home Assistant, asked once per visit (and after a change). */
async function refresh() {
  if (loading) return;
  loading = true;
  try {
    summary = (await action("auto_summary")) || { summary: null, remembered: null }; // asked once even on an error
    routerModel = await action("router_model"); // null: Home Assistant did not answer
  } finally {
    loading = false;
    redraw(); // the view open now - the page may have moved on meanwhile
  }
}

export function forgetAuto() {
  summary = null;
  routerModel = null;
}

export function renderAuto() {
  const models = Object.keys(status().model_settings || {});
  if (!modelsKnown && models.length) { models.forEach((m) => chosenModels.add(m)); modelsKnown = true; }
  if (!datasetName) datasetName = today();
  if (summary === null && !loading) refresh();
  const running = busy();
  const testChoice = el("div", { class: "segmented", role: "radiogroup", "data-auto-test": "" },
    ...[["ha", t("auto_test_ha")], ["new", t("auto_test_new")]].map(([value, label]) => el("button", {
      type: "button", class: test === value ? "on" : "", "aria-pressed": String(test === value), "data-value": value,
      onclick: () => { test = value; redraw(); },
    }, label)));
  const onlyBox = el("input", { type: "checkbox", "data-auto-router-only": "" });
  onlyBox.checked = routerOnly;
  onlyBox.addEventListener("change", () => { routerOnly = onlyBox.checked; });
  const uploadBox = el("input", { type: "checkbox", "data-auto-upload": "" });
  uploadBox.checked = upload;
  uploadBox.addEventListener("change", () => { upload = uploadBox.checked; });
  const start = async (event) => {
    const ok = await action("start", { kind: "auto", dataset: datasetName.trim(), models: [...chosenModels], test, upload,
      router_only: routerOnly },
      event.currentTarget);
    if (ok) { forgetAuto(); select("live"); }
  };
  return el("div", { class: "stack" },
    card(t("auto_title"), "auto",
      el("p", {}, t("auto_intro")),
      el("ol", { class: "hint auto-steps" }, ...["auto_step_fetch", "auto_step_test", "auto_step_data", "auto_step_train",
        "auto_step_compare"].map((key) => el("li", {}, t(key)))),
      field(t("auto_name"), input(datasetName, (value) => { datasetName = value; }, { "data-auto-name": "" })),
      field(t("models"), chips(models.map((m) => [m, m, (status().model_settings?.[m]?.base || "").split("/").pop()]),
        chosenModels, redraw)),
      field(t("auto_test"), testChoice),
      el("label", { class: "check" }, onlyBox, el("span", {}, t("auto_router_only"))),
      el("p", { class: "hint" }, t("auto_router_only_hint")),
      el("label", { class: "check" }, uploadBox, el("span", {}, t("auto_upload"))),
      powerOffBox(),
      el("div", { class: "actions" },
        el("button", { class: "btn primary", "data-auto-start": "", disabled: running || !chosenModels.size, onclick: start },
          el("ha-icon", { icon: "mdi:play" }), t("auto_start")),
        stopButton()),
      el("p", { class: "hint" }, t("auto_time"))),
    resultCard());
}

function fmtScore(value) {
  return value === null || value === undefined ? "–" : String(value);
}

function fmtSeconds(value) {
  return value === null || value === undefined ? "–" : `${Number(value).toFixed(2)} s`;
}

function resultCard() {
  const last = summary?.summary;
  const remembered = summary?.remembered;
  const inUse = routerModel?.model;
  const rows = (last?.models || []).map((m) => el("tr", { "data-auto-model": m.run },
    el("td", {}, m.model),
    el("td", {}, m.missing ? t("auto_missing") : `${fmtScore(m.trained)} / ${fmtScore(m.base)}`),
    el("td", {}, m.missing ? "–" : `${fmtSeconds(m.trained_s)} / ${fmtSeconds(m.base_s)}`),
    el("td", { class: m.better ? "ok" : "warn" }, m.missing ? "–" : t(m.better ? "auto_better" : m.accurate ? "auto_slower" : "auto_worse")),
    el("td", {}, m.missing ? null : useButton(m.ollama, inUse))));
  return card(t("auto_result_title"), "auto",
    last
      ? el("div", { class: "stack" },
        el("p", { class: "hint" }, t("auto_result_of", { dataset: last.dataset, finished: last.finished })),
        el("table", { class: "table", "data-auto-result": "" },
          el("thead", {}, el("tr", {}, ...["models", "auto_router_score", "auto_router_time", "auto_verdict", ""].map(
            (key) => el("th", {}, key ? t(key) : "")))),
          el("tbody", {}, ...rows)),
        el("p", { class: last.recommended ? "" : "hint warn", "data-auto-recommended": "" },
          last.recommended ? t("auto_recommended", { run: last.recommended }) : t("auto_none")))
      : el("p", { class: "hint" }, t("auto_no_result")),
    el("p", { class: "hint", "data-router-model": "" },
      routerModel ? t("auto_in_use", { model: inUse || "?" }) : t("auto_in_use_unknown")),
    remembered?.previous
      ? el("div", { class: "actions" }, el("button", { class: "btn", "data-restore-model": "", onclick: restore },
        el("ha-icon", { icon: "mdi:undo" }), t("auto_restore", { model: remembered.previous })))
      : null);
}

function useButton(model, inUse) {
  if (model === inUse) return el("span", { class: "ok", "data-model-in-use": model }, t("auto_used"));
  return el("button", { class: "btn", "data-use-model": model, onclick: async (event) => {
    const button = event.currentTarget;
    if (!(await ask(t("auto_use_confirm", { model, current: routerModel?.model || "?" })))) return;
    const result = await action("use_model", { model }, button);
    if (result) {
      toast(t("auto_used_toast", { model }));
      forgetAuto();
      refresh();
    }
  } }, el("ha-icon", { icon: "mdi:check-decagram-outline" }), t("auto_use"));
}

async function restore(event) {
  const previous = summary?.remembered?.previous;
  if (!(await ask(t("auto_restore_confirm", { model: previous })))) return;
  const result = await action("restore_model", {}, event.currentTarget);
  if (result) {
    toast(t("auto_used_toast", { model: previous }));
    forgetAuto();
    refresh();
  }
}
