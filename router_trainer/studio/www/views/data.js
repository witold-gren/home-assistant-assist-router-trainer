// The data: Home Assistant (the connection, the files of the router, the router code of HA's version), the
// test the models are compared on (generated or HA's, its review) and the dataset (steps, the built ones).

import {
  action, busy, card, chips, choice, el, facts, field, input, select, state, t, toast, when,
} from "./common.js";

const status = () => state.status || {};
export const REVIEW_PAGE = 150;
export const DATA_STEPS = ["testgen", "snapshot", "freeze", "router", "control", "answers", "build"];

// --- Home Assistant ----------------------------------------------------------------------------------

let haUrl = null;
let haToken = "";

function haStatus() {
  const ha = state.ha || {};
  if (ha.rejected) return el("p", { class: "hint warn", "data-ha-state": "rejected" }, t("ha_token_rejected"));
  if (ha.checked) {
    return el("p", { class: "ok-text", "data-ha-state": "ok" },
      t("ha_connected", { name: ha.checked.name || "Home Assistant", version: ha.checked.version || "" }));
  }
  return el("p", { class: "hint", "data-ha-state": "none" }, t("ha_not_connected"));
}

function fetchSummary() {
  const last = state.inputs;
  const fetching = state.fetching;
  if (fetching?.running) return el("p", { class: "hint", "data-fetching": "" }, t("fetching"));
  const parts = [];
  if (fetching && !fetching.running && !fetching.ok) parts.push(el("p", { class: "hint warn", "data-fetch-error": "" }, fetching.error));
  if (last) {
    parts.push(el("p", { class: "hint" }, t("fetched_at", { time: new Date(last.fetched * 1000).toLocaleString(state.language) })),
      facts([t("router_in_ha"), last.version || "—"], [t("log_rows"), String(last.log_rows ?? 0)],
        [t("automations"), String(last.automations ?? 0)], [t("custom_sentences"), String(last.custom_sentences ?? 0)],
        [t("test_files"), String(["tests", "test_data"].filter((k) => last.files?.[k]).length)]));
  } else {
    parts.push(el("p", { class: "hint" }, t("not_fetched")));
  }
  return el("div", { "data-fetch-summary": "" }, ...parts);
}

export function renderHa() {
  const ha = state.ha || {};
  if (haUrl === null) haUrl = ha.url || "";
  const connect = async (event) => {
    const result = await action("ha", { url: haUrl, token: haToken }, event.currentTarget);
    if (result) {
      haToken = "";
      toast(t("ha_connected", { name: result.name || "", version: result.version || "" }), "ok");
      select("ha");
    }
  };
  return el("div", { class: "stack" },
    card(t("ha_title"), "inputs",
      field(t("ha_url"), input(haUrl, (v) => { haUrl = v.trim(); }, { placeholder: "http://homeassistant.local:8123", "data-ha-url": "" })),
      field(t("ha_token"), input("", (v) => { haToken = v.trim(); }, { type: "password", autocomplete: "off",
        placeholder: ha.token_set ? t("ha_token_saved") : "", "data-ha-token": "" }), t("ha_token_admin_hint")),
      el("div", { class: "actions" }, el("button", { class: "btn primary", "data-ha-connect": "", onclick: connect }, t("ha_connect"))),
      haStatus()),
    card(t("inputs_title"), "inputs",
      el("p", { class: "hint" }, t("inputs_hint")),
      el("div", { class: "actions" }, el("button", { class: "btn primary", "data-ha-fetch": "",
        disabled: !ha.checked || ha.rejected || state.fetching?.running,
        onclick: (e) => action("fetch", {}, e.currentTarget) }, el("ha-icon", { icon: "mdi:download" }), t("fetch_from_ha"))),
      fetchSummary()));
}

// --- the router code -------------------------------------------------------------------------------

export function renderRouter() {
  const r = state.router || {};
  const ha = r.ha_version;
  const verdict = !ha ? el("p", { class: "hint" }, t("router_unknown"))
    : r.matches ? el("p", { class: "ok-text", "data-router-ok": "" }, t("router_matches", { version: r.version }))
      : el("p", { class: "hint warn", "data-router-mismatch": "" }, t("router_mismatch", { used: r.version || "?", ha }));
  return card(t("n_router"), "router",
    facts([t("router_used"), r.version || "—"], [t("router_in_ha"), ha || "—"]),
    el("p", { class: "hint mono" }, r.path || ""),
    verdict,
    r.rebuild ? el("p", { class: "hint warn", "data-router-rebuild": "" }, t("router_rebuild")) : null,
    r.mode === "path" ? el("p", { class: "hint" }, t("router_path_mode")) : el("div", { class: "actions" },
      el("button", { class: "btn primary", "data-router-fetch": "", disabled: !ha || r.matches || busy(),
        onclick: (e) => action("router_fetch", {}, e.currentTarget) }, el("ha-icon", { icon: "mdi:source-branch-sync" }),
        t("router_fetch", { version: ha || "?" }))));
}

// --- tests ------------------------------------------------------------------------------------------------

const testsInfo = () => status().tests || { active: "ha", tests: [] };
const total = (test) => Object.values(test.counts || {}).reduce((a, b) => a + b, 0);
let newTest = "";

function testFacts(test) {
  const n = test.counts || {};
  const dropped = Object.values(test.dropped || {}).reduce((a, b) => a + b, 0);
  return facts([t("p_router"), String(n.router ?? 0)], [t("p_control"), String(n.control ?? 0)],
    [t("p_answers"), String(n.answers ?? 0)], [t("p_real"), String(n.real ?? 0)], [t("p_wiki_answers"), String(n.wiki_answers ?? 0)],
    [t("test_rejected"), String(test.rejected ?? 0)], [t("test_dropped"), String(dropped)]);
}

export function renderTests() {
  const info = testsInfo();
  return el("div", { class: "stack" },
    card(t("test_title"), "test",
      el("p", { class: "hint" }, t("test_hint")),
      info.tests.length ? field(t("test_active"), choice(info.tests.map((test) => [test.name,
        `${test.name === "ha" ? t("test_ha") : test.name} · ${total(test)}`]), info.active, async (value) => {
        await action("active_test", { name: value });
        toast(t("test_refreeze"));
      }, { "data-test-active": "" })) : el("p", { class: "hint warn" }, t("test_missing")),
      el("div", { class: "row" },
        input(newTest, (v) => { newTest = v.trim(); }, { placeholder: t("test_name"), "data-test-name": "" }),
        el("button", { class: "btn primary", "data-testgen": "", disabled: busy(), onclick: async (e) => {
          if (await action("testgen", { name: newTest }, e.currentTarget)) select("live");
        } }, el("ha-icon", { icon: "mdi:creation" }), t("test_generate"))),
      el("p", { class: "hint" }, t("testgen_hint"))),
    ...info.tests.map((test) => el("section", { class: "card", "data-test-card": test.name },
      el("div", { class: "card-head" }, el("h2", {}, el("a", { href: `#/test/${encodeURIComponent(test.name)}` },
        test.name === "ha" ? t("test_ha") : test.name)),
        test.name === info.active ? el("span", { class: "badge good" }, t("test_active")) : null),
      testFacts(test))));
}

export function renderTest(name) {
  const info = testsInfo();
  const test = info.tests.find((x) => x.name === name);
  if (!test) return card(name, null, el("p", { class: "hint" }, t("test_missing")));
  const list = el("div", { class: "list", "data-review": "" }, el("p", { class: "hint" }, t("loading")));
  action("review_list", { name }).then((cases) => {
    if (!Array.isArray(cases)) { list.replaceChildren(el("p", { class: "hint" }, "—")); return; }
    // a page at a time: a test has hundreds of cases
    const row = (c) => {
      const box = el("input", { type: "checkbox", "data-case": c.id });
      box.checked = c.rejected;
      const line = el("label", { class: `case ${c.rejected ? "rejected" : ""}` }, box,
        el("span", {}, el("span", { class: "badge" }, t(`p_${c.section}`)), " ", c.text), el("small", { class: "hint" }, c.expect));
      box.addEventListener("change", async () => {
        line.classList.toggle("rejected", box.checked);
        await action("review", { name, case: c.id, rejected: box.checked });
        toast(t("test_refreeze"));
      });
      return line;
    };
    let shown = 0;
    const more = el("button", { class: "btn small", type: "button", "data-review-more": "" });
    const page = () => {
      const next = cases.slice(shown, shown + REVIEW_PAGE).map(row);
      shown += next.length;
      more.before(...next);
      more.textContent = t("show_more", { count: cases.length - shown });
      more.hidden = shown >= cases.length;
    };
    more.addEventListener("click", page);
    list.replaceChildren(more);
    page();
  });
  return el("div", { class: "stack" },
    card(name === "ha" ? t("test_ha") : name, "test", testFacts(test),
      name === info.active ? el("p", { class: "ok-text" }, t("test_is_active"))
        : el("div", { class: "actions" }, el("button", { class: "btn", "data-make-active": "", onclick: async (e) => {
          await action("active_test", { name }, e.currentTarget);
          toast(t("test_refreeze"));
        } }, t("make_active")))),
    card(t("test_review"), "review", list));
}

// --- the dataset ----------------------------------------------------------------------------------------

const steps = new Set(DATA_STEPS.filter((s) => s !== "testgen"));
let datasetName = "";

export function renderGenerate() {
  const s = status();
  const generated = s.generated || {};
  const datasets = s.datasets || [];
  if (!datasetName) datasetName = datasets.length ? datasets[datasets.length - 1].name : "";
  const inputs = Object.values(s.inputs || {});
  return el("div", { class: "stack" },
    card(t("data_title"), "generate",
      facts([t("inputs"), inputs.length ? `${inputs.filter(Boolean).length}/${inputs.length}` : null],
        [t("snapshot"), s.snapshot ? `${s.snapshot.targets} · ${when(s.snapshot.taken)}` : null],
        [t("holdout"), s.holdout ? String(s.holdout.sentences) : null],
        [`${t("generated")}: ${t("st_router")}`, String(generated.router ?? 0)],
        [`${t("generated")}: ${t("st_control")}`, String(generated.control ?? 0)],
        [`${t("generated")}: ${t("st_answers")}`, String(generated.answers ?? 0)]),
      field(t("dataset"), input(datasetName, (v) => { datasetName = v.trim(); }, { placeholder: "paz27", "data-dataset-name": "" }),
        t("dataset_hint")),
      field(t("steps_label"), chips(DATA_STEPS.map((step) => [step, t(`st_${step}`)]), steps)),
      el("div", { class: "actions" }, el("button", { class: "btn primary", "data-generate": "", disabled: busy(), onclick: async (e) => {
        const ok = await action("start", { kind: "data", dataset: datasetName, steps: DATA_STEPS.filter((x) => steps.has(x)) },
          e.currentTarget);
        if (ok) select("live");
      } }, el("ha-icon", { icon: "mdi:creation" }), t("generate"))),
      el("p", { class: "hint" }, t("generate_hint"))));
}

function datasetCard(d) {
  const snapshot = status().snapshot;
  const warning = snapshot?.fingerprint && d.fingerprint && d.fingerprint !== snapshot.fingerprint;
  const roles = Object.entries(d.roles || {}).map(([r, n]) => `${t(`st_${r}`)} ${n}`).join(" · ");
  return [
    el("p", { class: "hint" }, `${when(d.created)} · ${roles}`),
    facts(["train", String(d.train ?? "—")], ["dev", String(d.dev ?? "—")], [t("holdout_dropped"), String(d.holdout_rejected ?? 0)]),
    warning ? el("p", { class: "hint warn", "data-fingerprint": "" }, t("fingerprint_warning")) : null,
    (d.holdout_samples || []).length ? el("details", {}, el("summary", { class: "hint" }, t("holdout_samples")),
      el("ul", { class: "samples" }, ...d.holdout_samples.map((x) => el("li", {}, `${x.text}  ≈  ${x.test}`)))) : null,
  ];
}

export function renderDatasets() {
  const datasets = status().datasets || [];
  return el("div", { class: "stack" }, ...(datasets.length ? datasets.slice().reverse().map((d) => el("section", { class: "card", "data-dataset": d.name },
    el("div", { class: "card-head" }, el("h2", {}, el("a", { href: `#/dataset/${encodeURIComponent(d.name)}` }, d.name))),
    ...datasetCard(d))) : [card(t("datasets"), "dataset", el("p", { class: "hint" }, t("no_dataset")))]));
}

export function renderDataset(name) {
  const d = (status().datasets || []).find((x) => x.name === name);
  if (!d) return card(name, null, el("p", { class: "hint" }, t("no_dataset")));
  const sources = Object.entries(d.sources || {}).sort((a, b) => b[1] - a[1]);
  const topics = Object.entries(d.topics || {}).sort((a, b) => b[1] - a[1]);
  const table = (rows) => el("table", { class: "results" }, ...rows.map(([k, v]) => el("tr", {}, el("td", {}, k), el("td", {}, String(v)))));
  return el("div", { class: "stack" },
    card(d.name, "dataset", ...datasetCard(d),
      el("div", { class: "actions" }, el("button", { class: "btn primary", onclick: () => select("train") },
        el("ha-icon", { icon: "mdi:play" }), t("train_on_this")))),
    sources.length ? card(t("dataset_sources"), null, table(sources)) : null,
    topics.length ? card(t("dataset_topics"), null, table(topics)) : null);
}
