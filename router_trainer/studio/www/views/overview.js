// The overview: the road from the home's data to a model on the Jetson, what is done and the next step.

import { card, el, select, state, t } from "./common.js";

/** The steps in order: [key of the node, title, done?, what is there]. */
export function steps() {
  const s = state.status || {};
  const ha = state.ha || {};
  const inputs = state.inputs;
  const router = state.router || {};
  const tests = s.tests?.tests || [];
  const datasets = s.datasets || [];
  const runs = s.runs || [];
  const trained = runs.filter((r) => r.trained);
  return [
    ["ha", t("o_ha"), Boolean(ha.checked && !ha.rejected), ha.checked ? `${ha.checked.name} · ${ha.checked.version}` : ""],
    ["ha", t("o_inputs"), Boolean(inputs), inputs ? t("o_inputs_done", { rows: inputs.log_rows ?? 0, automations: inputs.automations ?? 0 }) : ""],
    ["router", t("o_router"), Boolean(router.matches), router.version ? `${router.version} / ${router.ha_version || "?"}` : ""],
    ["tests", t("o_test"), tests.some((x) => x.name === s.tests?.active), s.tests?.active === "ha" ? t("test_ha") : s.tests?.active || ""],
    ["generate", t("o_dataset"), datasets.length > 0, datasets.length ? datasets[datasets.length - 1].name : ""],
    ["train", t("o_train"), trained.length > 0, trained.length ? trained.map((r) => r.name).join(", ") : ""],
    ["runs", t("o_export"), runs.some((r) => r.export), runs.filter((r) => r.export).map((r) => r.export.name).join(", ")],
    ["compare", t("o_validate"), runs.some((r) => r.compare), ""],
  ];
}

export function renderOverview() {
  const list = steps();
  const next = list.find((step) => !step[2]);
  return el("div", { class: "stack" },
    card(t("o_title"), null, el("p", { class: "hint" }, t("o_intro")),
      el("ol", { class: "steps", "data-steps": "" }, ...list.map(([key, title, done, detail]) => el("li", { class: done ? "done" : "",
        "data-step": key },
        el("ha-icon", { icon: done ? "mdi:check-circle" : "mdi:circle-outline" }), " ",
        el("a", { href: `#/${key}` }, title), detail ? el("small", { class: "hint" }, ` · ${detail}`) : null))),
      next ? el("div", { class: "callout", "data-next": next[0] }, el("strong", {}, t("o_next")), " ", next[1], " ",
        el("button", { class: "btn primary small", onclick: () => select(next[0]) }, t("o_go"))) :
        el("p", { class: "ok-text" }, t("o_all_done"))),
    card(t("o_hardware_title"), null, el("p", { class: "hint" }, t("o_hardware"))));
}
