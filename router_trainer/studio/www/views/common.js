// What every view of the studio shares: the state of the machine, the draft of trainer.yaml (live bindings the
// frame sets), the texts, small DOM helpers and the calls. Taken over from the wake word studio; the draft here
// is the text of trainer.yaml, changed through the YAML document so its comments stay.

import { isScalar, parseDocument } from "../vendor/yaml.js";
import { STUDIO_STRINGS } from "../i18n.js";

export let state = null; // the "state" call: jobs, GPU, Home Assistant, tests, datasets, runs …
export let settings = null; // the "settings/get" call: the saved trainer.yaml, its hash, the defaults
export let draftText = ""; // trainer.yaml being edited (the draft)

let hooks = {};

/** The frame gives the views its state, the settings and the draft (and gives them again after every change). */
export function bind(next) {
  if ("state" in next) state = next.state;
  if ("settings" in next) settings = next.settings;
  if ("draftText" in next) draftText = next.draftText;
}

/** What the views ask of the frame: redraw, mark the draft changed, refresh, selecting a node. */
export function setHooks(next) {
  hooks = next;
}

// The studio's own texts first, then the training panel's (sent with the state as `ui`).
export const t = (key, values = {}) => {
  const language = state?.language === "pl" ? "pl" : "en";
  const text = STUDIO_STRINGS[language][key] ?? STUDIO_STRINGS.en[key] ?? state?.ui?.[key] ?? key;
  return String(text).replace(/\{(\w+)\}/g, (_, name) => values[name] ?? "");
};

export const fmt = (value, digits = 2) =>
  value === null || value === undefined || Number.isNaN(value)
    ? "—"
    : Number(value).toLocaleString(state?.language || "en", { minimumFractionDigits: digits, maximumFractionDigits: digits });

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value !== false && value !== null && value !== undefined) node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) if (child !== null && child !== undefined && child !== false) node.append(child);
  return node;
}

export const icon = (name) => el("ha-icon", { icon: name });

// "2026-11-16T22:40:12" -> "2026-11-16 22:40"
export const when = (iso) => (iso ? String(iso).replace("T", " ").slice(0, 16) : "");

export function duration(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return h ? `${h} h ${m} min` : `${m} min ${String(s).padStart(2, "0")} s`;
}

// --- the draft of trainer.yaml ----------------------------------------------------------------------

let parsed = { text: null, data: null };

/** The draft as data (the saved defaults below it are in `settings.defaults`). */
export function draftData() {
  if (parsed.text !== draftText) {
    let data = null;
    try { data = parseDocument(draftText).toJS() || {}; } catch { data = null; }
    parsed = { text: draftText, data };
  }
  return parsed.data;
}

const lookup = (data, path) => path.reduce((value, key) => (value && typeof value === "object" ? value[key] : undefined), data);

/** A setting of the draft (undefined when the draft does not set it). */
export const getSetting = (path) => lookup(draftData() || {}, path);
/** What applies when the draft does not set it: trainer.example.yaml. */
export const defaultSetting = (path) => lookup(settings?.defaults || {}, path);

// a value written as YAML: plain when it reads back the same, else quoted
const PLAIN = /^[A-Za-z0-9_./@+-][A-Za-z0-9_./:@+ -]*$/;
const SPECIAL = /^(true|false|yes|no|on|off|null|~|[-+]?(\d|\.\d))/i;
function yamlScalar(value) {
  if (typeof value !== "string") return String(value);
  return PLAIN.test(value) && !SPECIAL.test(value) && value.trim() === value ? value : JSON.stringify(value);
}

/** Write a setting into the draft text; "" or null removes it (the default applies). A value the file
 * already has is replaced where it stands, so the rest of the file (comments, their alignment) stays as it is. */
export function setSetting(path, value, key = null) {
  const text = draftText || "";
  const doc = parseDocument(text);
  if (doc.errors.length) throw new Error(doc.errors[0].message);
  const node = doc.getIn(path, true);
  const remove = value === "" || value === null || value === undefined;
  if (!remove && isScalar(node) && node.range && typeof value !== "object") {
    const [start, end] = node.range;
    hooks.textChanged?.(text.slice(0, start) + yamlScalar(value) + text.slice(end), key ?? path.join("."));
    return;
  }
  if (remove) {
    if (doc.hasIn(path)) doc.deleteIn(path);
  } else {
    doc.setIn(path, value);
  }
  hooks.textChanged?.(String(doc), key ?? path.join("."));
}

/** The text of one part of the draft (a section or a model), for the YAML on the side. */
export function partText(path) {
  const doc = parseDocument(draftText || "");
  const node = doc.getIn(path, true);
  if (node === undefined) return "";
  const part = parseDocument("");
  part.contents = node;
  return String(part);
}

/** Put the text of one part back into the draft (an error when it is not YAML). */
export function setPartText(path, text) {
  const part = parseDocument(text);
  if (part.errors.length) throw new Error(part.errors[0].message);
  const doc = parseDocument(draftText || "");
  if (doc.errors.length) throw new Error(doc.errors[0].message);
  if (part.contents === null) doc.deleteIn(path);
  else doc.setIn(path, part.contents);
  hooks.textChanged?.(String(doc), `part:${path.join(".")}`, { keepSide: true });
}

export const redraw = () => hooks.redraw?.();
export const refresh = () => hooks.refresh?.();
export const select = (key) => hooks.select?.(key);

// --- talking to the studio ----------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(message, status, body = {}) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

// every call has a time limit: a studio that does not answer never leaves the page waiting
export const CALL_TIMEOUT_MS = 20000;
const callTimeout = () => window.__studioCallTimeoutMs || CALL_TIMEOUT_MS;

export async function call(type, data = {}, { timeout = callTimeout() } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  let response;
  try {
    response = await fetch("/api/call", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...data, type }),
      signal: controller.signal,
    });
  } catch (err) {
    if (err.name === "AbortError") throw new ApiError(t("call_timeout", { seconds: Math.round(timeout / 1000) }), 0, {});
    throw new ApiError(t("call_offline"), 0, {});
  } finally {
    clearTimeout(timer);
  }
  const body = await response.json().catch(() => ({}));
  if (response.status === 401 && body.login) {
    location.assign("/login");
    throw new ApiError(body.error, 401, body);
  }
  if (!response.ok) throw new ApiError(body.error || response.statusText, response.status, body);
  return body;
}

/** An action of the training panel (start a job, fetch from HA, review a case …); its result, or null on error. */
// actions the server answers only when done (its own limits: git clone 300 s, a sentence for the models
// 900 s); every other action starts a job and answers at once
const LONG_ACTIONS = { router_fetch: 320000, try: 920000 };

export async function action(name, extra = {}, button = null) {
  if (button) button.classList.add("busy");
  try {
    const answer = await call("action", { action: name, ...extra }, { timeout: LONG_ACTIONS[name] || callTimeout() });
    await refresh();
    return answer.result ?? true;
  } catch (err) {
    toast(err.message, "error");
    return null;
  } finally {
    if (button) button.classList.remove("busy");
  }
}

export const job = () => state?.status?.job || null;
export const busy = () => Boolean(job()?.running);

// --- toasts, questions ------------------------------------------------------------------------------

export function toast(text, kind = "") {
  let box = document.getElementById("toasts");
  if (!box) {
    box = el("div", { id: "toasts", class: "toasts", "aria-live": "polite" });
    document.body.append(box);
  }
  const node = el("div", { class: `toast ${kind}` }, text);
  box.append(node);
  setTimeout(() => node.remove(), Math.max(kind === "error" ? 7000 : 3500, String(text).length * 70));
}

// a question in the studio's own window; resolves true for OK, false for Cancel, Esc or a click outside
export function ask(message, { danger = false } = {}) {
  const ok = el("button", { type: "button", class: `btn ${danger ? "danger" : "primary"}`, "data-ask-ok": "" }, "OK");
  const cancel = el("button", { type: "button", class: "btn", "data-ask-cancel": "" }, t("cancel"));
  const dialog = el("dialog", { class: "ask" }, el("p", {}, message), el("div", { class: "actions" }, cancel, ok));
  document.body.append(dialog);
  return new Promise((resolve) => {
    const finish = (answer) => {
      if (dialog.open) dialog.close();
      dialog.remove();
      resolve(answer);
    };
    dialog.addEventListener("close", () => finish(false));
    ok.onclick = () => finish(true);
    cancel.onclick = () => finish(false);
    dialog.onclick = (e) => { if (e.target === dialog) finish(false); };
    dialog.showModal();
    ok.focus();
  });
}

/** A card of a view: its title, a "?" with the help of this step (state.help), the content. */
export function card(title, helpKey, ...children) {
  const help = helpKey && state?.help?.[helpKey];
  const button = help ? el("button", { type: "button", class: "help-btn", title: t("help"), "aria-label": t("help"),
    "aria-haspopup": "dialog", "data-help": helpKey, onclick: (event) => {
      event.stopPropagation();
      toggleHelp(event.currentTarget, title, help, state?.help?.links?.[helpKey]);
    } }, "?") : null;
  return el("section", { class: "card view-card" }, el("div", { class: "card-head" }, el("h2", {}, title), button), ...children);
}

// --- "?" of a view or a card: a small popup next to the button (gpu-studio.md section 5, "Help") ------------
// Only the top bar's "?" opens the guide; this one explains its one function and may link to the guide below.

let helpPopup = null;

export function closeHelp() {
  if (!helpPopup) return;
  helpPopup.anchor.setAttribute("aria-expanded", "false");
  helpPopup.node.remove();
  document.removeEventListener("keydown", helpPopup.onKey, true);
  document.removeEventListener("pointerdown", helpPopup.onOutside, true);
  window.removeEventListener("resize", closeHelp);
  helpPopup = null;
}

function toggleHelp(anchor, title, text, page) {
  const again = helpPopup?.anchor === anchor;
  closeHelp();
  if (again) return;
  const node = el("div", { class: "help-pop", role: "dialog", "aria-label": title, "data-help-pop": "" },
    el("div", { class: "help-pop-head" }, el("strong", {}, title),
      el("button", { type: "button", class: "ghost help-pop-close", "aria-label": t("close"), "data-help-close": "",
        onclick: closeHelp }, "✕")),
    el("p", {}, text),
    page ? el("a", { class: "guide-link", "data-guide-link": page, target: "_blank", rel: "noopener",
      href: `/docs/${state.language === "pl" ? "pl" : "en"}/${page}` }, `${t("guide_more")} →`) : null);
  document.body.append(node);
  const box = anchor.getBoundingClientRect();
  const width = node.offsetWidth;
  node.style.top = `${Math.round(box.bottom + window.scrollY + 6)}px`;
  node.style.left = `${Math.round(Math.max(8, Math.min(window.innerWidth - width - 8, box.right - width)) + window.scrollX)}px`;
  anchor.setAttribute("aria-expanded", "true");
  const onKey = (event) => { if (event.key === "Escape") { event.stopPropagation(); closeHelp(); } };
  const onOutside = (event) => { if (!node.contains(event.target) && event.target !== anchor) closeHelp(); };
  helpPopup = { node, anchor, onKey, onOutside };
  document.addEventListener("keydown", onKey, true);
  document.addEventListener("pointerdown", onOutside, true);
  window.addEventListener("resize", closeHelp);
}

/** A row of facts: big value, small name. */
export function facts(...pairs) {
  return el("div", { class: "tiles" }, ...pairs.filter(Boolean).map(([name, value, cls = ""]) =>
    el("div", { class: `tile ${cls}` }, el("div", { class: "name" }, name), el("div", { class: "value" }, value ?? "—"))));
}

// --- fields -------------------------------------------------------------------------------------------

export function field(label, input, hint) {
  return el("label", { class: "field" }, el("span", {}, label), input, hint ? el("p", { class: "hint" }, hint) : null);
}

export function input(value, oninput, attrs = {}) {
  const node = el("input", { ...attrs });
  node.value = value ?? "";
  node.addEventListener("input", () => oninput(node.value, node));
  return node;
}

export function choice(options, value, onchange, attrs = {}) {
  const node = el("select", attrs, ...options.map(([v, label]) => el("option", { value: v }, label)));
  node.value = value ?? "";
  node.addEventListener("change", () => onchange(node.value));
  return node;
}

/** Chips with a checkbox each; `chosen` is a Set kept by the view. */
export function chips(items, chosen, onchange = () => {}) {
  return el("div", { class: "chips" }, ...items.map(([value, label, sub]) => {
    const box = el("input", { type: "checkbox", "data-chip": value });
    box.checked = chosen.has(value);
    box.addEventListener("change", () => { if (box.checked) chosen.add(value); else chosen.delete(value); onchange(); });
    return el("label", { class: "chip" }, box, el("span", {}, label, sub ? el("small", {}, sub) : null));
  }));
}

/** A number of the settings: empty = the default (shown as the placeholder). */
export function settingNumber(path, attrs = {}) {
  const fallback = defaultSetting(path);
  const node = input(getSetting(path) ?? "", (value) => {
    const number = value.trim() === "" ? null : Number(value);
    if (number !== null && Number.isNaN(number)) return;
    setSetting(path, number);
  }, { type: "number", step: "any", placeholder: fallback ?? "", "data-setting": path.join("."), ...attrs });
  return node;
}

export function settingText(path, attrs = {}) {
  return input(getSetting(path) ?? "", (value) => setSetting(path, value.trim() || null),
    { placeholder: defaultSetting(path) ?? "", "data-setting": path.join("."), ...attrs });
}

export function settingCheck(path, label) {
  const box = el("input", { type: "checkbox", "data-setting": path.join(".") });
  box.checked = Boolean(getSetting(path) ?? defaultSetting(path));
  box.addEventListener("change", () => setSetting(path, box.checked, path.join(".")));
  return el("label", { class: "check" }, box, el("span", {}, label));
}

// --- clipboard ----------------------------------------------------------------------------------------

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = el("textarea", { readonly: true, style: "position:fixed;top:-1000px;opacity:0" });
    area.value = text;
    document.body.append(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

export function copyButton(getText) {
  const button = el("button", { class: "copy-btn", type: "button" }, el("span", {}, t("copy")));
  button.addEventListener("click", async () => {
    const label = button.querySelector("span");
    const text = await getText();
    if (!text || !(await copyText(text))) return toast(t("copy_failed"), "error");
    button.classList.add("done");
    label.textContent = t("copied");
    setTimeout(() => { button.classList.remove("done"); label.textContent = t("copy"); }, 1600);
    return undefined;
  });
  return button;
}

/** A terminal keeps its scroll: at the bottom it follows new lines, scrolled up it stays where it is. */
export function refill(pre, text) {
  if (!pre || pre.textContent === text) return;
  const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 20;
  pre.textContent = text;
  if (atBottom) pre.scrollTop = pre.scrollHeight;
}
