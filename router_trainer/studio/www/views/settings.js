// Settings: trainer.yaml as forms (every field writes into the draft, comments stay; empty = the default shown
// grey), the machine's power through Home Assistant, the machine check and the account.

import {
  action, ask, call, card, choice, el, field, getSetting, input, select, setSetting, settingCheck, settingNumber,
  settingText, state, t, toast,
} from "./common.js";

const num = (path, hintKey) => field(path.at(-1), settingNumber(path), hintKey ? t(hintKey) : undefined);
const text = (path, hintKey) => field(path.at(-1), settingText(path), hintKey ? t(hintKey) : undefined);
const group = (title, ...children) => el("div", { class: "form-group" }, el("h3", {}, title), el("div", { class: "grid-2" }, ...children));

const FORMS = {
  ollama: () => [group(t("s_ollama"),
    text(["ollama", "jetson"], "h_jetson"), text(["ollama", "teacher"], "h_teacher"),
    text(["ollama", "test_writer"], "h_test_writer"), num(["ollama", "local_port"]), text(["ollama", "version"], "h_ollama_version"))],
  generate: () => [
    field("seed", settingNumber(["generate", "seed"]), t("h_seed")),
    group(t("st_router"),
      num(["generate", "router", "paraphrases_per_topic"], "h_paraphrases"), num(["generate", "router", "per_template"], "h_per_template"),
      num(["generate", "router", "native_intents"], "h_native"), num(["generate", "router", "knowledge"]),
      num(["generate", "router", "gibberish"]), num(["generate", "router", "max_per_topic"], "h_max_per_topic"),
      num(["generate", "router", "min_per_topic"], "h_min_per_topic"), num(["generate", "router", "noise"], "h_noise"),
      settingCheck(["generate", "router", "log_questions"], t("h_log_questions"))),
    group(t("st_control"),
      num(["generate", "control", "labels"], "h_labels"), num(["generate", "control", "sentences_per_label"])),
    group(t("st_answers"),
      num(["generate", "answers", "given"], "h_given"), num(["generate", "answers", "live_per_topic"]),
      num(["generate", "answers", "wikipedia"])),
  ],
  test: () => [group(t("s_test"),
    num(["test", "seed"]), num(["test", "router_per_topic"]), num(["test", "control"]), num(["test", "control_overhead"], "h_overhead"),
    num(["test", "answers"]), num(["test", "real_per_topic"]), num(["test", "real_max"]), num(["test", "wikipedia"]))],
  holdout: () => [group(t("s_holdout"),
    num(["holdout", "word_similarity"], "h_word_similarity"), num(["holdout", "char_similarity"], "h_char_similarity"))],
  dataset: () => [group(t("s_dataset"),
    num(["dataset", "dev_fraction"], "h_dev_fraction"),
    num(["dataset", "mix", "router"], "h_mix"), num(["dataset", "mix", "control"]), num(["dataset", "mix", "answers"]))],
  export: () => [group(t("s_export"),
    field("quantization", choice([["", "—"], ["q8_0", "q8_0"], ["bf16", "bf16"], ["f16", "f16"]],
      getSetting(["export", "quantization"]) ?? "", (v) => setSetting(["export", "quantization"], v || null),
      { "data-setting": "export.quantization" }), t("h_quantization")),
    text(["export", "name"], "h_export_name"))],
  evaluate: () => [group(t("s_evaluate"),
    field("unload_first", input((getSetting(["evaluate", "unload_first"]) || []).join(", "),
      (v) => setSetting(["evaluate", "unload_first"], v.split(",").map((x) => x.trim()).filter(Boolean)),
      { placeholder: "gemma4:26b", "data-setting": "evaluate.unload_first" }), t("h_unload_first")))],
};

function modelForm(model) {
  const path = (key) => ["models", model, key];
  return [
    group(model,
      text(path("base"), "h_base"), text(path("baseline"), "h_baseline"),
      settingCheck(path("load_in_4bit"), t("h_load_in_4bit"))),
    group(t("params"),
      num(path("epochs"), "h_epochs"), num(path("learning_rate"), "h_learning_rate"),
      num(path("lora_r"), "h_lora_r"), num(path("lora_alpha"), "h_lora_alpha"),
      num(path("batch_size"), "h_batch_size"), num(path("grad_accum"), "h_grad_accum"),
      num(path("max_seq_length"), "h_max_seq_length")),
  ];
}

/** A settings node the studio has a form for (none, "models", a section or models/<name>). */
export function settingsKnown(id) {
  return !id || id === "models" || id in FORMS || (id.startsWith("models/") && id.length > 7);
}

/** The path of a settings node in trainer.yaml (the YAML on the side edits it). */
export function settingsPath(id) {
  if (!id) return null;
  return id.startsWith("models/") ? ["models", id.slice("models/".length)] : [id];
}

export function renderSettings(id) {
  if (!id) {
    return card("trainer.yaml", "settings", el("p", { class: "hint" }, t("settings_intro")),
      el("ul", { class: "samples" }, ...Object.keys(FORMS).map((key) => el("li", {},
        el("a", { href: `#/settings/${key}` }, t(`s_${key}`)))), el("li", {}, el("a", { href: "#/settings/models" }, t("s_models")))));
  }
  if (id === "models") {
    const models = Object.keys(getSetting(["models"]) || state.status?.model_settings || {});
    return card(t("s_models"), "settings", el("p", { class: "hint" }, t("models_intro")),
      el("ul", { class: "samples" }, ...models.map((m) => el("li", {}, el("a", { href: `#/settings/models/${m}` }, m)))));
  }
  const body = id.startsWith("models/") ? modelForm(id.slice("models/".length)) : FORMS[id]?.();
  if (!body) return null;
  return card(id.startsWith("models/") ? `${t("s_models")}: ${id.slice(7)}` : t(`s_${id}`), "settings",
    el("p", { class: "hint" }, t(`intro_${id.startsWith("models/") ? "models" : id}`)), ...body,
    el("p", { class: "hint" }, t("settings_empty_default")));
}

// --- the machine's power ---------------------------------------------------------------------------------

let entities = null; // switches and power sensors of Home Assistant, read once
const power = { switch: null, sensor: null, off_watts: null };

export function machineLabel() {
  const m = state.machine;
  if (!m) return "";
  const kind = m.machine || "unknown";
  const watts = m.watts === null || m.watts === undefined || kind === "off" ? "" : ` · ${Math.round(Number(m.watts))} W`;
  return t(`machine_${kind}`) + watts;
}

export async function switchMachineOff(button) {
  if (!(await ask(t("machine_off_confirm"), { danger: true }))) return;
  action("machine_off", {}, button);
}

function entityField(kind, value, onchange) {
  if (!entities) return input(value, onchange, { "data-power": kind, placeholder: kind === "switches" ? "switch.maszyna_gpu" : "sensor.…_power" });
  const list = [...(entities[kind] || [])].sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));
  const options = [["", t("ha_entity_choose")], ...(value && !list.some((e) => e.id === value) ? [[value, value]] : []),
    ...list.map((e) => [e.id, e.name ? `${e.name} (${e.id})` : e.id])];
  return choice(options, value, onchange, { "data-power": kind });
}

export function renderPower() {
  const saved = state.ha?.power || {};
  for (const key of Object.keys(power)) if (power[key] === null) power[key] = saved[key] ?? (key === "off_watts" ? 5 : "");
  const m = state.machine;
  const ready = Boolean(saved.switch && saved.sensor);
  const view = card(t("power_title"), "power",
    el("p", { class: "hint" }, t("power_hint")),
    field(t("power_switch"), entityField("switches", power.switch, (v) => { power.switch = v; }), t("power_switch_hint")),
    field(t("power_sensor"), entityField("sensors", power.sensor, (v) => { power.sensor = v; })),
    field(t("power_watts"), input(power.off_watts, (v) => { power.off_watts = Number(v) || 5; }, { type: "number", "data-power": "watts" }),
      t("power_watts_hint")),
    el("div", { class: "actions" },
      el("button", { class: "btn", "data-power-suggest": "", onclick: async (e) => {
        e.currentTarget.classList.add("busy");
        try { entities = await call("ha_entities"); select("power"); } catch (err) { toast(`${t("ha_entities_failed")} ${err.message}`, "error"); }
        e.currentTarget?.classList.remove("busy");
      } }, t("ha_entities_refresh")),
      el("button", { class: "btn primary", "data-power-save": "", onclick: async (e) => {
        if (await action("power_settings", { ...power }, e.currentTarget)) toast(t("saved"), "ok");
      } }, t("power_save"))),
    ready && m ? el("div", { class: "actions" }, el("span", { class: "pill" }, machineLabel()),
      el("button", { class: "btn danger", "data-machine-off": "", disabled: !["on", "starting"].includes(m.machine),
        onclick: (e) => switchMachineOff(e.currentTarget) }, el("ha-icon", { icon: "mdi:power" }), t("power_turn_off"))) : null,
    el("p", { class: "hint" }, t("power_after_hint", { seconds: state.studio?.power_off_delay ?? 120 })));
  return view;
}

// --- the machine check and the account -------------------------------------------------------------

export function renderMachine() {
  const task = state.task;
  return card(t("n_machine"), "machine",
    el("p", { class: "hint" }, t("machine_check_hint")),
    el("div", { class: "actions" }, el("button", { class: "btn primary", "data-check": "", onclick: (e) => action("check", {}, e.currentTarget) },
      el("ha-icon", { icon: "mdi:stethoscope" }), t("check"))),
    task?.name === "check" ? el("pre", { class: "terminal", "data-task": "" }, task.lines.join("\n")) : null);
}

export function renderAccount() {
  if (state.studio?.trusted) {
    return card(t("n_account"), null,
      el("p", { "data-trusted": "" }, t("trusted_login")),
      el("p", { class: "hint" }, t("trusted_hint")));
  }
  return card(t("n_account"), null,
    el("p", {}, t("logged_in", { user: state.studio?.user || "?" })),
    el("p", { class: "hint" }, t("account_hint")),
    el("p", { class: "hint" }, t("trusted_hint")),
    el("div", { class: "actions" }, el("button", { class: "btn", "data-logout-view": "", onclick: async () => {
      await fetch("/api/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      location.assign("/login");
    } }, el("ha-icon", { icon: "mdi:logout" }), t("logout"))));
}
