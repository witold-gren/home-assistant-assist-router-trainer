// The Assist Router trainer studio: the training panel as an editor, laid out like the Home Dashboard and Assist
// Router editors (and the wake word studio it is taken from). Three columns: the tree (the steps, then the
// settings), the view of what is chosen (or the whole trainer.yaml) and on the side the YAML of the chosen part of
// the settings or the live job. Every change of trainer.yaml goes to a draft kept on the machine, which changes
// nothing until "Save"; undo and redo work over it. The draft is the text of the file, so its comments stay.

import { LitElement, html, nothing } from "./vendor/lit-all.min.js";
import { parse } from "./vendor/yaml.js";
import { LANGUAGES, translate } from "./i18n.js";
import { buildOutline, filterOutline, findNode, flattenOutline } from "./outline.js";
import { describeChanges, diffHunks, diffLines } from "./changes.js";
import * as common from "./views/common.js";
import { renderOverview } from "./views/overview.js";
import {
  renderDataset, renderDatasets, renderGenerate, renderHa, renderRouter, renderTest, renderTests,
} from "./views/data.js";
import { liveCard, renderJobs, renderLive, renderRun, renderRuns, renderTrain, updateJobs, updateLive } from "./views/training.js";
import { renderCompare, renderTry } from "./views/validation.js";
import {
  machineLabel, renderAccount, renderMachine, renderPower, renderSettings, settingsKnown, settingsPath, switchMachineOff,
} from "./views/settings.js";

const APP_TAG = "router-trainer-studio";
export const POLL_MS = 2000;
// A draft is kept this long after the last change, so typing does not send every letter.
export const DRAFT_SAVE_MS = 800;
// Steps that can be undone; typing in one place within this time is one step, not one per letter.
export const UNDO_LIMIT = 200;
const COALESCE_MS = 1500;
const THEME_KEY = "router-trainer-studio-theme";
const LANG_KEY = "router-trainer-studio-lang";
const WIDTHS_KEY = "router-trainer-studio-widths";
const COLLAPSED_KEY = "router-trainer-studio-collapsed";
const FOLDED_KEY = "router-trainer-studio-folded";
const FOLDED_WIDTH = 28; // a folded column stays as a narrow bar with its unfold button
const NARROW_WINDOW = 900; // below it the right column starts folded
const NODE_KEY = "router-trainer-studio-node";
export const THEMES = ["auto", "light", "dark"];
const THEME_ICONS = { auto: "mdi:theme-light-dark", light: "mdi:weather-sunny", dark: "mdi:weather-night" };
// The side columns: their width when nothing was chosen, and how narrow and wide a drag can make them.
export const COLUMNS = { left: { start: 290, min: 220, max: 520 }, right: { start: 380, min: 300, max: 680 } };

export function columnWidth(side, width) {
  const { min, max } = COLUMNS[side];
  return Math.round(Math.min(max, Math.max(min, Number(width) || COLUMNS[side].start)));
}

const readJson = (key, fallback) => {
  try {
    return JSON.parse(localStorage.getItem(key) ?? "null") ?? fallback;
  } catch {
    return fallback;
  }
};
const store = (key, value) => {
  try { localStorage.setItem(key, typeof value === "string" ? value : JSON.stringify(value)); } catch { /* private mode */ }
};
const safeParse = (text) => {
  try { return parse(text) || {}; } catch { return null; }
};


/** The guide in the studio's language: MkDocs, English at the top, Polish in pl/. */
export function docsUrl(language, page = "") {
  return `/docs/${language === "pl" ? "pl" : "en"}/${page}`;
}

/** m:ss (or h:mm:ss) of a number of seconds. */
export function clock(seconds) {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${r}` : `${m}:${r}`;
}

/** How far the job is (0..1) now and at its first reading: training steps, else the generators' counters. */
export function jobFraction(progress) {
  const steps = (progress.metrics || []).filter((p) => p.max_steps);
  if (steps.length) {
    const last = steps[steps.length - 1];
    return { now: Math.min(1, last.step / last.max_steps), first: Math.min(1, steps[0].step / steps[0].max_steps) };
  }
  const counters = Object.values(progress.counters || {});
  const target = counters.reduce((sum, c) => sum + (c.target || 0), 0);
  if (!target) return null;
  const done = counters.reduce((sum, c) => sum + Math.min(c.done || 0, c.target || 0), 0);
  return { now: done / target, first: 0 };
}

class RouterTrainerStudio extends LitElement {
  static properties = {
    _state: { state: true },
    _settings: { state: true },
    _selected: { state: true },
    _search: { state: true },
    _collapsed: { state: true },
    _widths: { state: true },
    _folded: { state: true },
    _theme: { state: true },
    _dialog: { state: true },
    _notice: { state: true },
    _saving: { state: true },
    _past: { state: true },
    _future: { state: true },
    _yamlAll: { state: true },
    _menu: { state: true },
    _gear: { state: true },
    _error: { state: true },
  };

  // light DOM: the views are plain DOM and share studio.css
  createRenderRoot() {
    return this;
  }

  constructor() {
    super();
    this._state = null;
    this._settings = null;
    this._current = "";
    this._saved = "";
    this._past = [];
    this._future = [];
    this._search = "";
    this._viewVersion = 0;
    const widths = readJson(WIDTHS_KEY, {});
    this._widths = { left: columnWidth("left", widths.left), right: columnWidth("right", widths.right) };
    this._collapsed = new Set(readJson(COLLAPSED_KEY, []));
    const folded = readJson(FOLDED_KEY, null);
    this._folded = folded && typeof folded === "object"
      ? { left: Boolean(folded.left), right: Boolean(folded.right) }
      : { left: false, right: window.innerWidth < NARROW_WINDOW };
    let theme = null;
    try { theme = localStorage.getItem(THEME_KEY); } catch { theme = null; }
    this._theme = THEMES.includes(theme) ? theme : "auto";
    try { this._language = localStorage.getItem(LANG_KEY); } catch { this._language = null; }
    this._selected = decodeURIComponent(location.hash.replace(/^#\/?/, "")) || readJson(NODE_KEY, null) || "overview";
    this._jobsSeen = new Set();
    this._jobsKnown = false;
    this._onKey = this._onKey.bind(this);
    this._onHash = this._onHash.bind(this);
    this._onGuide = this._onGuide.bind(this);
    this._onUnload = this._onUnload.bind(this);
    this._onOutside = this._onOutside.bind(this);
    this._applyTheme();
  }

  connectedCallback() {
    super.connectedCallback();
    window.addEventListener("keydown", this._onKey);
    window.addEventListener("click", this._onOutside);
    window.addEventListener("hashchange", this._onHash);
    window.addEventListener("pagehide", this._onUnload);
    document.addEventListener("click", this._onGuide);
    matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => this._applyTheme());
    common.setHooks({
      textChanged: (text, key, options) => this._changed(text, key, options),
      redraw: () => this._redraw(),
      refresh: () => this._refresh(),
      select: (key) => { this._select(key); this._redraw(); },
    });
    this._load();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener("keydown", this._onKey);
    window.removeEventListener("click", this._onOutside);
    window.removeEventListener("hashchange", this._onHash);
    window.removeEventListener("pagehide", this._onUnload);
    document.removeEventListener("click", this._onGuide);
    clearTimeout(this._poller);
    document.removeEventListener("visibilitychange", this._onVisible);
    common.closeHelp();
  }

  _t(key, values) {
    return translate(this._state?.language, key, values, this._state?.ui);
  }

  // --- the look -------------------------------------------------------------------------------------

  _applyTheme() {
    const dark = this._theme === "dark" || (this._theme === "auto" && matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }

  _setTheme(theme) {
    this._theme = theme;
    store(THEME_KEY, theme);
    this._applyTheme();
  }

  _nextTheme() {
    this._setTheme(THEMES[(THEMES.indexOf(this._theme) + 1) % THEMES.length]);
  }

  async _setLanguage(language) {
    this._language = language;
    store(LANG_KEY, language);
    await this._refresh();
    this._redraw();
  }

  // --- loading, the state, the settings ------------------------------------------------------------

  async _load() {
    try {
      const [state, settings] = await Promise.all([this._callState(), common.call("settings/get")]);
      this._setState(state);
      this._applySettings(settings);
      this._error = null;
    } catch (err) {
      this._error = err.message;
    }
    this._onVisible = () => { if (!document.hidden) this._poll(); };
    document.addEventListener("visibilitychange", this._onVisible);
    this._schedulePoll();
  }

  /** Polling never overlaps: the next state is asked for only after the last answer, and not in a tab in
   * the background (it starts again when the tab is shown). */
  _schedulePoll() {
    clearTimeout(this._poller);
    this._poller = setTimeout(() => this._poll(), POLL_MS);
  }

  async _poll() {
    clearTimeout(this._poller);
    if (document.hidden || this._polling || !this.isConnected) return;
    this._polling = true;
    try {
      await this._refresh();
    } finally {
      this._polling = false;
      if (!document.hidden && this.isConnected) this._schedulePoll();
    }
  }

  _callState() {
    return common.call("state", { language: this._language || null });
  }

  _setState(state) {
    const text = JSON.stringify(state);
    if (text === this._stateText) return; // nothing new: nothing drawn again
    this._stateText = text;
    this._state = state;
    common.bind({ state });
    document.documentElement.lang = state.language;
    document.title = this._t("title");
  }

  /** The state again - at most one request at a time: a refresh asked for while one runs (after an
   * action) is done once more right after it, never in parallel. */
  async _refresh() {
    if (this._inflight) {
      this._again = true;
      return this._inflight;
    }
    this._inflight = (async () => {
      do {
        this._again = false;
        try {
          this._setState(await this._callState());
          this._error = null;
        } catch (err) {
          this._error = err.message;
          return;
        }
        this._afterState();
      } while (this._again);
    })();
    try {
      await this._inflight;
    } finally {
      this._inflight = null;
    }
  }

  _applySettings(settings) {
    this._settings = settings;
    this._hash = settings.hash;
    this._saved = settings.text;
    if (settings.draft) {
      this._current = settings.draft.text;
      this._base = settings.draft.base;
      this._draftOnServer = true;
      this._draftAt = settings.draft.changed;
    } else {
      this._current = settings.text;
      this._base = settings.hash;
      this._draftOnServer = false;
      this._draftAt = null;
    }
    this._sideText = null;
    this._allText = null;
    common.bind({ settings, draftText: this._current });
    this._redraw();
  }

  /** After every state: a job that ended (a toast, the lists again). */
  _afterState() {
    const job = this._state.status?.job;
    if (job && !job.running) {
      const key = `${job.log}:${job.state}`;
      if (!this._jobsSeen.has(key)) {
        this._jobsSeen.add(key);
        if (this._jobsKnown) common.toast(`${job.title || job.kind}: ${this._t(job.state)}`, job.state === "ok" ? "ok" : "error");
        this._redraw();
      }
    }
    this._jobsKnown = true;
  }

  // --- the draft, undo and redo ----------------------------------------------------------------------

  get _dirty() {
    return this._current !== this._saved;
  }

  get _conflict() {
    return this._draftOnServer && this._base !== this._hash;
  }

  /** New text of the draft (a form, the YAML); one undo step unless quick typing in the same place. */
  _changed(text, key = null, { keepSide = false, keepAll = false, redraw = false } = {}) {
    if (text !== this._current) {
      const now = Date.now();
      const merge = key && this._lastEdit?.key === key && now - this._lastEdit.at < COALESCE_MS;
      if (!merge) this._past = [...this._past, this._current].slice(-UNDO_LIMIT);
      this._lastEdit = key ? { key, at: now } : null;
      this._future = [];
      this._current = text;
      common.bind({ draftText: text });
      if (!keepSide) this._sideText = null;
      if (!keepAll) this._allText = null;
      this._scheduleDraft();
    }
    if (redraw) this._viewVersion += 1;
    this.requestUpdate();
  }

  _redraw() {
    this._viewVersion += 1;
    this.requestUpdate();
  }

  _scheduleDraft() {
    this._pending = true;
    this._draftFailed = false; // a new change: a failed save is tried again
    clearTimeout(this._draftTimer);
    this._draftTimer = setTimeout(() => this._saveDraft(), DRAFT_SAVE_MS);
  }

  /** The draft to the server - one save at a time (gpu-studio.md section 9a): a save asked for while one runs
   * waits for it, and the changes made meanwhile go in one save after it. A failed save says so and is tried
   * again only with the next change, or when Save forces it - never in a loop. */
  async _saveDraft({ force = false } = {}) {
    clearTimeout(this._draftTimer);
    while (this._draftInflight) await this._draftInflight;
    if (!this._pending || (this._draftFailed && !force)) return;
    this._pending = false;
    this._saving = true;
    this._draftInflight = (async () => {
      try {
        if (!this._dirty) {
          // back to the file as it is: no draft is needed
          if (this._draftOnServer) await common.call("draft/discard");
          this._draftOnServer = false;
          this._base = this._hash;
          this._draftAt = null;
        } else {
          await common.call("draft/save", { text: this._current, base: this._base });
          this._draftOnServer = true;
          this._draftAt = new Date().toISOString();
        }
        this._draftFailed = false;
      } catch (err) {
        this._pending = true;
        this._draftFailed = true;
        this._notice = { kind: "error", text: this._t("error", { message: err.message }) };
      }
    })();
    try {
      await this._draftInflight;
    } finally {
      this._draftInflight = null;
      this._saving = false;
    }
  }

  // the page closes with a change not sent yet: send it on the way out
  _onUnload() {
    if (!this._pending) return;
    const body = this._dirty ? { type: "draft/save", text: this._current, base: this._base } : { type: "draft/discard" };
    navigator.sendBeacon?.("/api/call", JSON.stringify(body));
  }

  _restoreText(text) {
    this._current = text;
    this._lastEdit = null;
    this._sideText = null;
    this._allText = null;
    common.bind({ draftText: text });
    this._scheduleDraft();
    this._redraw();
  }

  _undo() {
    if (!this._past.length) return;
    this._future = [this._current, ...this._future];
    const previous = this._past.at(-1);
    this._past = this._past.slice(0, -1);
    this._restoreText(previous);
  }

  _redo() {
    if (!this._future.length) return;
    this._past = [...this._past, this._current];
    const next = this._future[0];
    this._future = this._future.slice(1);
    this._restoreText(next);
  }

  async _discard() {
    if (!(await common.ask(this._t("discard_confirm"), { danger: true }))) return;
    clearTimeout(this._draftTimer);
    this._pending = false;
    try {
      await common.call("draft/discard");
    } catch (err) {
      this._notice = { kind: "error", text: this._t("error", { message: err.message }) };
    }
    this._past = [];
    this._future = [];
    this._applySettings(await common.call("settings/get"));
  }

  /** A click outside ☰ and ⚙ closes their windows (the click on ☰ or ⚙ itself toggles them). */
  _onOutside(event) {
    if (!this._menu && !this._gear) return;
    if (event.composedPath().some((el) => el.classList?.contains("menu-wrap"))) return;
    this._menu = false;
    this._gear = false;
  }

  _onKey(event) {
    if (event.key === "Escape" && (this._menu || this._gear)) {
      this._menu = false;
      this._gear = false;
      return;
    }
    const mod = event.ctrlKey || event.metaKey;
    if (!mod || this._dialog || document.querySelector("dialog.ask[open]")) return;
    if (event.code === "KeyB") {
      // Ctrl/⌘+B the left column, Ctrl/⌘+Alt+B the right one (the code: Alt changes the letter on a Mac)
      event.preventDefault();
      this._fold(event.altKey ? "right" : "left");
      return;
    }
    const key = event.key.toLowerCase();
    if (key === "s") {
      event.preventDefault();
      this._openSave();
      return;
    }
    // in a text field its own undo works; elsewhere the editor's
    const typing = ["TEXTAREA", "INPUT", "SELECT"].includes(document.activeElement?.tagName);
    if (typing) return;
    if (key === "z" || key === "y") {
      event.preventDefault();
      if (key === "y" || event.shiftKey) this._redo();
      else this._undo();
    }
  }

  // --- the tree ---------------------------------------------------------------------------------------

  _outline() {
    return buildOutline({ state: this._state, data: safeParse(this._current), t: (k, v) => this._t(k, v) });
  }

  _select(key) {
    this._selected = key;
    this._yamlAll = false;
    this._sideText = null;
    store(NODE_KEY, key);
    if (decodeURIComponent(location.hash.slice(2)) !== key) history.replaceState(null, "", `#/${encodeURIComponent(key)}`);
    this._unfoldTo(key);
    this.querySelector(".middle")?.scrollTo?.(0, 0);
  }

  _onHash() {
    const key = decodeURIComponent(location.hash.replace(/^#\/?/, ""));
    if (key && key !== this._selected) this._select(key);
  }

  _unfoldTo(key) {
    const groups = this._outline();
    const next = new Set(this._collapsed);
    for (const group of groups) {
      for (const item of group.children) {
        const inside = flattenOutline(item.children || []).some((child) => child.key === key);
        if (item.key === key || inside) next.delete(group.key);
        if (inside) {
          next.delete(item.key);
          for (const child of flattenOutline(item.children)) {
            if (flattenOutline(child.children || []).some((c) => c.key === key)) next.delete(child.key);
          }
        }
      }
    }
    if (next.size !== this._collapsed.size) {
      this._collapsed = next;
      store(COLLAPSED_KEY, [...next]);
    }
  }

  _toggle(key) {
    const next = new Set(this._collapsed);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    this._collapsed = next;
    store(COLLAPSED_KEY, [...next]);
  }

  _foldAll(fold) {
    const keys = flattenOutline(this._outline().flatMap((group) => group.children)).filter((item) => item.children?.length)
      .map((item) => item.key);
    this._collapsed = new Set(fold ? keys : []);
    store(COLLAPSED_KEY, [...this._collapsed]);
  }

  /** Fold or unfold a column; its width before folding comes back when it is unfolded. */
  _fold(side, folded = !this._folded[side]) {
    this._folded = { ...this._folded, [side]: folded };
    store(FOLDED_KEY, this._folded);
  }

  _foldButton(side) {
    const folded = this._folded[side];
    const label = this._t(`${folded ? "unfold" : "fold"}_${side}`);
    const arrow = (side === "left") === folded ? "›" : "‹";
    return html`<button class="ghost fold-col" data-fold-col=${side} aria-expanded=${!folded} title=${label} aria-label=${label}
      @click=${() => this._fold(side)}>${arrow}</button>`;
  }

  _renderFolded(side) {
    return html`<div class="folded-col ${side}" data-folded=${side}>${this._foldButton(side)}</div>`;
  }

  _renderSplitter(side) {
    if (this._folded[side]) return html`<div class="splitter off" data-splitter=${side} aria-hidden="true"></div>`;
    const move = (event) => {
      const box = this.getBoundingClientRect();
      const width = side === "left" ? event.clientX - box.left : box.right - event.clientX;
      this._widths = { ...this._widths, [side]: columnWidth(side, width) };
    };
    const start = (event) => {
      event.preventDefault();
      const bar = event.currentTarget;
      bar.setPointerCapture?.(event.pointerId);
      bar.classList.add("dragging");
      const stop = () => {
        bar.classList.remove("dragging");
        bar.removeEventListener("pointermove", move);
        bar.removeEventListener("pointerup", stop);
        bar.removeEventListener("pointercancel", stop);
        store(WIDTHS_KEY, this._widths);
      };
      bar.addEventListener("pointermove", move);
      bar.addEventListener("pointerup", stop);
      bar.addEventListener("pointercancel", stop);
    };
    const reset = () => {
      this._widths = { ...this._widths, [side]: COLUMNS[side].start };
      store(WIDTHS_KEY, this._widths);
    };
    return html`<div class="splitter" role="separator" aria-orientation="vertical" title=${this._t("resize")}
      data-splitter=${side} @pointerdown=${start} @dblclick=${reset}></div>`;
  }

  // --- the views ---------------------------------------------------------------------------------------

  /** What a node shows: its view, how it follows the state, and the part of trainer.yaml on the side. */
  _spec(key = this._selected) {
    const [kind, id] = key.includes("/") ? [key.slice(0, key.indexOf("/")), key.slice(key.indexOf("/") + 1)] : [key, null];
    const live = { side: "live" };
    const status = this._state.status || {};
    switch (kind) {
      case "overview": return { ...live, render: renderOverview };
      case "ha": return { ...live, render: renderHa };
      case "router": return { ...live, render: renderRouter };
      case "tests": return { ...live, render: renderTests };
      case "test": return (status.tests?.tests || []).some((x) => x.name === id) ? { ...live, render: () => renderTest(id) } : null;
      case "generate": return { ...live, render: renderGenerate };
      case "datasets": return { ...live, render: renderDatasets };
      case "dataset": return { ...live, render: () => renderDataset(id) };
      case "train": return { ...live, render: renderTrain };
      case "live": return { side: "jobs", render: renderLive, update: updateLive };
      case "jobs": return { ...live, render: renderJobs, update: updateJobs };
      case "runs": return { ...live, render: renderRuns };
      case "run": return { ...live, render: () => renderRun(id) };
      case "compare": return { ...live, render: renderCompare };
      case "try": return { ...live, render: renderTry };
      case "settings": return settingsKnown(id)
        ? { render: () => renderSettings(id), yaml: id && id !== "models" ? settingsPath(id) : null } : null;
      case "power": return { ...live, render: renderPower };
      case "machine": return { ...live, render: renderMachine };
      case "look": return { ...live, render: () => this._lookView() };
      case "account": return { ...live, render: renderAccount };
      default: return null;
    }
  }

  /** What in the state a view shows: when it changes, the view is drawn again (not while typing in it). */
  _signature() {
    const s = this._state;
    const st = s.status || {};
    return JSON.stringify([s.ha, s.inputs, s.fetching, s.router, s.machine, s.task?.running, s.task?.name, s.studio?.power_off,
      st.tests, (st.datasets || []).map((d) => d.name), (st.runs || []).map((r) => [r.name, r.trained, Boolean(r.export), Boolean(r.compare)]),
      st.job && [st.job.kind, st.job.running, st.job.state], st.snapshot, st.holdout, st.generated]);
  }

  _buildView(spec) {
    try {
      return spec.render();
    } catch (err) {
      console.error(err); // eslint-disable-line no-console
      return common.card(this._t("error", { message: err.message }), null, common.el("pre", { class: "terminal" }, err.stack || ""));
    }
  }

  _mountView() {
    const host = this.querySelector(".view-host");
    if (!host || !this._state || !this._settings) return;
    let spec = this._spec();
    if (!spec && this._state.checking) {
      // the machine's state is not read yet (tests, datasets, runs): wait for it, do not leave the node
      host.replaceChildren(common.el("p", { class: "hint" }, this._t("loading")));
      this._mountedKey = null;
      return;
    }
    if (!spec) {
      this._select("overview");
      spec = this._spec();
    }
    const key = `${this._selected}|${this._viewVersion}|${this._state.language}`;
    if (key !== this._mountedKey) {
      this._mountedKey = key;
      this._signatureShown = this._signature();
      host.replaceChildren(this._buildView(spec));
      return;
    }
    if (spec.update) {
      spec.update(host.firstElementChild);
      return;
    }
    const signature = this._signature();
    const typing = host.contains(document.activeElement) && ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName);
    if (signature !== this._signatureShown && !typing && !spec.yaml) {
      this._signatureShown = signature;
      host.replaceChildren(this._buildView(spec));
    }
  }

  updated() {
    const dialog = this.querySelector("dialog.frame-dialog");
    if (dialog && !dialog.open) dialog.showModal();
    this._mountView();
    const slot = this.querySelector("[data-side-live]");
    if (slot && this._state) slot.replaceChildren(liveCard());
    const job = this.querySelector("[data-side-job]");
    if (job) {
      const atBottom = job.scrollTop + job.clientHeight >= job.scrollHeight - 20;
      if (atBottom) job.scrollTop = job.scrollHeight;
    }
  }

  // --- saving and the history ---------------------------------------------------------------------

  async _openSave() {
    if (!this._dirty || !this._settings) return;
    await this._saveDraft({ force: true });
    this._saveState = { note: "", error: null, conflict: false, busy: false };
    this._dialog = "save";
  }

  async _save(force = false) {
    this._saveState = { ...this._saveState, busy: true, error: null };
    this.requestUpdate();
    try {
      await this._saveDraft({ force: true });
      await common.call("settings/save", { text: this._current, base: this._base, note: this._saveState.note, force });
      this._dialog = null;
      this._past = [];
      this._future = [];
      this._applySettings(await common.call("settings/get"));
      this._notice = { kind: "ok", text: this._t("saved") };
      await this._refresh();
    } catch (err) {
      this._saveState = { ...this._saveState, busy: false, conflict: Boolean(err.body?.conflict), error: err.message };
      this.requestUpdate();
    }
  }

  async _openHistory() {
    this._historyState = { versions: null, pick: null, text: null };
    this._dialog = "history";
    try {
      this._historyState = { ...this._historyState, versions: (await common.call("history/list")).versions };
    } catch (err) {
      this._historyState = { ...this._historyState, versions: [], error: err.message };
    }
    this.requestUpdate();
  }

  async _pickVersion(id) {
    this._historyState = { ...this._historyState, pick: id, text: null };
    this.requestUpdate();
    const { text } = await common.call("history/get", { id });
    this._historyState = { ...this._historyState, text };
    this.requestUpdate();
  }

  async _restoreVersion(id) {
    if (this._dirty && !(await common.ask(this._t("history_restore_confirm")))) return;
    clearTimeout(this._draftTimer);
    this._pending = false;
    const before = this._current;
    await common.call("history/restore", { id });
    this._dialog = null;
    this._applySettings(await common.call("settings/get"));
    if (before !== this._current) {
      this._past = [...this._past, before];
      this._future = [];
    }
    this._notice = { kind: "ok", text: this._t("restored") };
  }

  // --- the YAML of the chosen part and of the whole file -----------------------------------------------

  _onSideYaml(path, text) {
    this._sideText = text;
    try {
      common.setPartText(path, text);
      this._sideError = null;
      this._viewVersion += 1; // the form shows the new values
      this.requestUpdate();
    } catch (err) {
      this._sideError = this._t("yaml_error", { error: err.message });
      this.requestUpdate();
    }
  }

  _onAllYaml(text) {
    this._allText = text;
    const value = safeParse(text);
    this._allError = value === null || typeof value !== "object" || Array.isArray(value)
      ? this._t("yaml_not_map") : null;
    // the text is the draft as it is (also while not valid yet - "Save" checks it)
    this._changed(text, "all-yaml", { keepAll: true });
  }

  // --- the guide ("?" next to a field opens its part) --------------------------------------------------

  _onGuide(event) {
    const trigger = event.target.closest?.("[data-guide]");
    if (!trigger || !this.contains(trigger)) return;
    event.preventDefault();
    this._guideSection = trigger.dataset.guide;
    this._dialog = "guide";
    this.updateComplete.then(() => {
      const target = this._guideSection && this.querySelector(`#guide-${this._guideSection}`);
      if (target) target.scrollIntoView({ block: "start" });
    });
  }

  // --- rendering --------------------------------------------------------------------------------------

  render() {
    if (!this._state || !this._settings) {
      return html`<p class="loading">${this._error ? this._t("error", { message: this._error }) : this._t("loading")}</p>`;
    }
    const spec = this._spec() || this._spec("overview");
    return html`
      ${this._renderTop()} ${this._renderNotices()}
      <div class="cols" style="--left: ${this._folded.left ? FOLDED_WIDTH : this._widths.left}px; --right: ${this._folded.right ? FOLDED_WIDTH : this._widths.right}px">
        ${this._folded.left ? this._renderFolded("left") : this._renderTree()} ${this._renderSplitter("left")}
        <main class="middle" data-middle>
          ${this._yamlAll ? this._renderAllYaml() : html`<div class="view view-host" data-view=${this._selected}></div>`}
        </main>
        ${this._renderSplitter("right")} ${this._folded.right ? this._renderFolded("right") : this._renderSide(spec)}
      </div>
      ${this._renderDialog()}
    `;
  }

  /** The job chip: stage, how far (training steps or generated examples) and the time left. */
  _jobChip(job) {
    const progress = this._state.progress || {};
    const name = progress.stage || job.title || job.kind;
    const done = jobFraction(progress);
    if (done === null) return name;
    const percent = Math.floor(done.now * 100);
    const elapsed = job.started ? Date.now() / 1000 - job.started : 0;
    const rate = elapsed > 30 ? (done.now - done.first) / elapsed : 0;
    return rate > 0 && done.now < 1
      ? `${name} · ${this._t("job_chip_eta", { percent, eta: clock((1 - done.now) / rate) })}`
      : `${name} · ${this._t("job_chip_percent", { percent })}`;
  }

  /** The machine chip: the card's load, temperature and memory (from nvidia-smi in the container). */
  _machineChip() {
    const gpu = this._state.status?.gpu;
    if (!gpu || gpu.utilization == null) return "";
    const gb = (mb) => (mb == null ? "?" : (mb / 1024).toFixed(1));
    return this._t("machine_chip", { util: Math.round(gpu.utilization), temp: Math.round(gpu.temperature ?? 0),
      used: gb(gpu.memory_used), total: gb(gpu.memory_total) });
  }

  _renderTop() {
    const draftState = this._saving ? this._t("state_saving") : this._dirty ? this._t("state_draft") : this._t("state_clean");
    const job = this._state.status?.job;
    const machine = this._state.machine;
    const router = this._state.router || {};
    const power = this._state.studio?.power_off || {};
    const countdown = power.at ? Math.max(0, Math.round(power.at - Date.now() / 1000)) : null;
    return html`<header class="top">
      <span class="menu-wrap">
      <button class="ghost menu" data-menu aria-label=${this._t("menu")} title=${this._t("menu")}
        @click=${() => { this._menu = !this._menu; this._gear = false; }}>
        <ha-icon icon="mdi:menu"></ha-icon>
      </button>
      ${this._menu ? html`<div class="menu-pop" data-menu-pop @click=${() => { this._menu = false; }}>
        <span class="who" data-who>${this._state.studio?.trusted ? this._t("trusted_login")
          : this._t("logged_in", { user: this._state.studio?.user || "?" })}</span>
        <a href=${`/docs/${this._state.language === "pl" ? "pl" : "en"}/`} target="_blank" rel="noopener">
          <ha-icon icon="mdi:book-open-variant"></ha-icon>${this._t("docs")}</a>
        <button @click=${() => this._select("account")}><ha-icon icon="mdi:account-key-outline"></ha-icon>${this._t("n_account")}</button>
        ${this._state.studio?.trusted ? nothing : html`<button data-logout @click=${async () => {
          await fetch("/api/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
          location.assign("/login");
        }}><ha-icon icon="mdi:logout"></ha-icon>${this._t("logout")}</button>`}
      </div>` : nothing}
      </span>
      <img class="app-icon" src="/favicon.svg" alt="" width="22" height="22" />
      <h1>${this._t("title")}</h1>
      <span class="board" title=${this._settings.path}>trainer.yaml</span>
      ${job?.running || this._state.error ? html`<span class="pill ${this._state.error ? "bad" : "running"}" data-job-pill
        title=${this._state.progress?.stage || ""} @click=${() => this._select("live")}>
        <ha-icon icon=${this._state.error ? "mdi:alert-circle-outline" : "mdi:chart-line"}></ha-icon>
        ${this._state.error ? this._t("connection_error") : this._jobChip(job)}</span>` : nothing}
      ${machine ? html`<span class="pill ${machine.machine === "rejected" ? "bad" : ""}" data-machine title=${machine.error || machineLabel()}>
          <ha-icon icon="mdi:expansion-card-variant"></ha-icon>${this._machineChip() || machineLabel()}</span>
        <button class="ghost danger" data-power-off title=${this._t("power_turn_off")}
          ?disabled=${["off", "stopping", "unknown", "checking", "rejected"].includes(machine.machine)}
          @click=${(event) => switchMachineOff(event.currentTarget)}><ha-icon icon="mdi:power"></ha-icon></button>` : nothing}
      ${countdown !== null ? html`<span class="pill warn" data-power-countdown-top>
          <ha-icon icon="mdi:timer-outline"></ha-icon>${this._t("countdown_top", { time: clock(countdown) })} ·
          <button class="link" data-power-cancel-top @click=${async () => { await common.call("power/cancel"); await this._refresh(); }}>
            ${this._t("side_power_off_cancel")}</button></span>` : nothing}
      ${this._state.studio?.power_off_error ? html`<span class="pill bad" data-power-error-top
        title=${this._state.studio.power_off_error}><ha-icon icon="mdi:power-plug-off-outline"></ha-icon>${this._t("side_power_off_error",
        { error: this._state.studio.power_off_error })}</span>` : nothing}
      ${router.ha_version && !router.matches ? html`<span class="pill bad" data-router-pill title=${this._t("router_mismatch",
        { used: router.version || "?", ha: router.ha_version })} @click=${() => this._select("router")}>
        <ha-icon icon="mdi:source-branch"></ha-icon>${this._t("router_pill", { used: router.version || "?", ha: router.ha_version })}</span>` : nothing}
      <span class="grow"></span>
      <span class="pill ${this._dirty ? "draft" : ""}" data-draft-state=${this._dirty ? "draft" : "clean"}>
        <ha-icon icon=${this._dirty ? "mdi:pencil" : "mdi:check"}></ha-icon>${draftState}
      </span>
      <button class="ghost" data-undo title=${this._t("undo")} ?disabled=${!this._past.length} @click=${this._undo}>
        <ha-icon icon="mdi:undo"></ha-icon></button>
      <button class="ghost" data-redo title=${this._t("redo")} ?disabled=${!this._future.length} @click=${this._redo}>
        <ha-icon icon="mdi:redo"></ha-icon></button>
      ${this._dirty || this._draftOnServer ? html`<button class="ghost" data-discard @click=${this._discard}>${this._t("discard")}</button>` : nothing}
      <button class="ghost" data-theme-button=${this._theme} title=${this._t(`theme_${this._theme}`)} @click=${this._nextTheme}>
        <ha-icon icon=${THEME_ICONS[this._theme]}></ha-icon></button>
      <button class="ghost ${this._yamlAll ? "on" : ""}" data-yaml title=${this._t("yaml_hint")} @click=${() => { this._yamlAll = !this._yamlAll; }}>
        <ha-icon icon="mdi:code-braces"></ha-icon>${this._t("yaml")}</button>
      <a class="btn ghost" data-docs title=${this._t("docs_hint")} aria-label=${this._t("docs")}
        href=${docsUrl(this._state.language)} target="_blank" rel="noopener"><ha-icon icon="mdi:help-circle-outline"></ha-icon></a>
      <span class="menu-wrap">
        <button class="ghost ${this._gear ? "on" : ""}" data-settings title=${this._t("settings")} aria-expanded=${this._gear ? "true" : "false"}
          @click=${() => { this._gear = !this._gear; this._menu = false; }}>
          <ha-icon icon="mdi:cog-outline"></ha-icon></button>
        ${this._gear ? this._renderGear() : nothing}
      </span>
      <button class="ghost" data-history @click=${this._openHistory}><ha-icon icon="mdi:history"></ha-icon>${this._t("history")}</button>
      <button class="primary" data-save ?disabled=${!this._dirty} @click=${this._openSave}>
        <ha-icon icon="mdi:content-save"></ha-icon>${this._t("save")}</button>
    </header>`;
  }

  _renderNotices() {
    return html`
      ${this._error ? html`<div class="notice error" data-error-notice><span>${this._t("error", { message: this._error })}</span></div>` : nothing}
      ${this._state.error ? html`<div class="notice error" data-state-error><span>${this._state.error}</span></div>` : nothing}
      ${this._conflict ? html`<div class="notice error" data-conflict-notice><span>${this._t("conflict")}</span></div>` : nothing}
      ${this._notice ? html`<div class="notice ${this._notice.kind}" data-notice=${this._notice.kind}>
        <span>${this._notice.text}</span>
        <button class="ghost" aria-label=${this._t("close")} @click=${() => { this._notice = null; }}><ha-icon icon="mdi:close"></ha-icon></button>
      </div>` : nothing}
    `;
  }

  _renderTree() {
    const groups = filterOutline(this._outline(), this._search);
    const searching = Boolean(this._search.trim());
    const node = (item, depth) => {
      const open = searching || !this._collapsed.has(item.key);
      return html`
        <div class="node ${this._selected === item.key ? "sel" : ""} ${item.warn ? "warn" : ""} ${item.busy ? "busy" : ""}"
          style="padding-left: ${8 + depth * 16}px" data-node=${item.key} title=${item.warn ?? item.hint ?? ""}
          @click=${() => this._select(item.key)}>
          ${item.children.length
            ? html`<button class="fold" aria-label=${this._t("fold")} data-fold=${item.key}
                @click=${(event) => { event.stopPropagation(); this._toggle(item.key); }}>
                <ha-icon icon=${open ? "mdi:chevron-down" : "mdi:chevron-right"}></ha-icon></button>`
            : html`<span class="fold"></span>`}
          <ha-icon class="icon" icon=${item.warn ? "mdi:alert-outline" : item.icon}></ha-icon>
          <span class="label">${item.label}</span>
          ${item.done && !item.warn ? html`<span class="done-mark" data-done=${item.key} title=${this._t("state_done")}>✓</span>` : nothing}
          ${item.count !== undefined ? html`<span class="count">${item.count}</span>` : nothing}
        </div>
        ${open ? item.children.map((child) => node(child, depth + 1)) : nothing}
      `;
    };
    return html`<nav class="tree" data-tree>
      <div class="fold-row">${this._foldButton("left")}</div>
      <label class="search">
        <ha-icon icon="mdi:magnify"></ha-icon>
        <input data-search placeholder=${this._t("search")} .value=${this._search} @input=${(event) => { this._search = event.target.value; }} />
      </label>
      <div class="tree-tools">
        <button class="ghost" data-fold-all @click=${() => this._foldAll(true)}><ha-icon icon="mdi:unfold-less-horizontal"></ha-icon>${this._t("fold_all")}</button>
        <button class="ghost" data-unfold-all @click=${() => this._foldAll(false)}><ha-icon icon="mdi:unfold-more-horizontal"></ha-icon>${this._t("unfold_all")}</button>
      </div>
      ${groups.map((group) => {
        const groupOpen = searching || !this._collapsed.has(group.key);
        return html`
          <div class="group" data-group=${group.key}>
            <button class="fold" aria-label=${this._t("fold")} aria-expanded=${groupOpen} data-group-fold=${group.key}
              @click=${() => this._toggle(group.key)}>
              <ha-icon icon=${groupOpen ? "mdi:chevron-down" : "mdi:chevron-right"}></ha-icon></button>
            <span class="group-name" @click=${() => this._toggle(group.key)}>${group.label}</span>
          </div>
          ${groupOpen ? group.children.map((item) => node(item, 0)) : nothing}
        `;
      })}
    </nav>`;
  }

  _renderAllYaml() {
    const text = this._allText ?? this._current;
    return html`<section class="card" data-yaml-all>
      <div class="card-head"><h2>trainer.yaml</h2><span class="hint">${this._t("yaml_hint")}</span></div>
      ${this._allError ? html`<p class="field-error" data-yaml-error>${this._allError}</p>` : nothing}
      <textarea class="code" spellcheck="false" .value=${text} @input=${(event) => this._onAllYaml(event.target.value)}></textarea>
    </section>`;
  }

  _renderSide(spec) {
    const power = this._state.studio?.power_off || {};
    const seconds = power.at ? Math.max(0, Math.round(power.at - Date.now() / 1000)) : null;
    const ha = this._state.ha || {};
    const powerReady = Boolean(ha.power?.switch && ha.url);
    const job = this._state.status?.job;
    if (spec?.yaml) {
      const yaml = this._sideText ?? common.partText(spec.yaml);
      return html`<aside class="side" data-side>
        <div class="fold-row">${this._foldButton("right")}</div>
        <section class="card" data-side-yaml>
          <h3>${this._t("side_yaml")} · ${spec.yaml.join(".")}</h3>
          <p class="hint">${this._t("side_yaml_hint")}</p>
          ${this._sideError && this._sideText !== null ? html`<p class="field-error">${this._sideError}</p>` : nothing}
          <textarea class="code" spellcheck="false" data-side-yaml-text .value=${yaml}
            @input=${(event) => this._onSideYaml(spec.yaml, event.target.value)}></textarea>
        </section>
        <section class="card" data-draft-card>
          <h3>${this._t("side_draft")}</h3>
          ${this._settings.exists ? nothing : html`<p class="hint">${this._t("side_file_missing")}</p>`}
          ${this._dirty && this._draftAt ? html`<p>${this._t("side_draft_at", { time: new Date(this._draftAt).toLocaleString(this._state.language) })}</p>` : nothing}
          ${this._conflict ? html`<p class="hint warn">${this._t("draft_outdated")}</p>` : nothing}
          <p class="hint">${this._t("side_draft_note")}</p>
        </section>
      </aside>`;
    }
    return html`<aside class="side" data-side>
      <div class="fold-row">${this._foldButton("right")}</div>
      ${spec?.side === "jobs" ? nothing : html`<div data-side-live></div>`}
      ${spec?.side === "jobs" || job ? html`<section class="card" data-side-job-card>
        <h3>${this._t("side_job")}${job ? ` · ${job.title || job.kind} · ${this._t(job.state)}` : ""}</h3>
        <pre class="terminal" data-side-job>${(this._state.log || "").split("\n").slice(-40).join("\n") || "—"}</pre>
      </section>` : nothing}
      ${powerReady ? html`<section class="card" data-power-card>
        <label class="check"><input type="checkbox" data-power-after .checked=${Boolean(power.after_training) || seconds !== null}
          @change=${async (event) => {
            try {
              await common.call("power/off_after_training", { enabled: event.target.checked });
            } catch (err) {
              common.toast(err.message, "error");
            }
            await this._refresh();
          }} /><span>${this._t("side_power_off")}</span></label>
        <p class="hint">${this._t("side_power_off_hint", { seconds: this._state.studio?.power_off_delay ?? 120 })}</p>
        ${seconds !== null ? html`<p class="hint warn" data-power-countdown>${this._t("side_power_off_countdown", { seconds })}
          <button class="btn small" @click=${async () => { await common.call("power/cancel"); await this._refresh(); }}>
          ${this._t("side_power_off_cancel")}</button></p>` : nothing}
        ${this._state.studio?.power_off_error ? html`<p class="hint warn">${this._t("side_power_off_error", { error: this._state.studio.power_off_error })}</p>` : nothing}
      </section>` : nothing}
    </aside>`;
  }

  _renderDialog() {
    if (this._dialog === "save") return this._renderSave();
    if (this._dialog === "history") return this._renderHistory();
    if (this._dialog === "guide") return this._renderGuide();
    return nothing;
  }

  _dialogShell(name, title, body, foot = nothing, narrow = false) {
    const close = () => { this._dialog = null; };
    return html`<dialog class="frame-dialog ${narrow ? "narrow" : ""}" data-dialog=${name}
      @close=${() => { if (this._dialog === name) close(); }}
      @click=${(event) => { if (event.target === event.currentTarget) close(); }}>
      <div class="dialog-head"><h2>${title}</h2>
        <button class="ghost" data-close aria-label=${this._t("close")} @click=${close}><ha-icon icon="mdi:close"></ha-icon></button></div>
      <div class="dialog-body">${body}</div>
      ${foot === nothing ? nothing : html`<div class="dialog-foot">${foot}</div>`}
    </dialog>`;
  }

  _renderDiff(before, after) {
    return html`<div class="diff" data-diff>${diffHunks(diffLines(before, after)).map((line) => line.kind === "skip"
      ? html`<div class="skip">${this._t("save_lines_skipped", { count: line.count })}</div>`
      : html`<div class=${line.kind}>${line.kind === "added" ? "+ " : line.kind === "removed" ? "- " : "  "}${line.text}</div>`)}</div>`;
  }

  _renderSave() {
    const changes = describeChanges(safeParse(this._saved) || {}, safeParse(this._current) || {});
    const s = this._saveState;
    const chipsOf = (kind, keys) => keys.map((key) => html`<span class="change ${kind}">${key}</span>`);
    const body = html`
      <p class="hint">${this._t("save_intro")}</p>
      <div class="changes" data-changes>
        ${chipsOf("added", changes.added)} ${chipsOf("removed", changes.removed)} ${chipsOf("changed", changes.changed)}
      </div>
      ${this._renderDiff(this._saved, this._current)}
      <label class="field">${this._t("save_note")}
        <input data-save-note placeholder=${this._t("save_note_placeholder")} .value=${s.note}
          @input=${(event) => { s.note = event.target.value; }} /></label>
      ${s.conflict ? html`<p class="hint warn" data-save-conflict>${this._t("save_conflict")}</p>` : nothing}
      ${s.error && !s.conflict ? html`<p class="field-error" data-save-error>${s.error}</p>` : nothing}`;
    const foot = html`
      <button class="ghost" @click=${() => { this._dialog = null; }}>${this._t("cancel")}</button>
      ${s.conflict ? html`<button class="btn danger" data-save-force ?disabled=${s.busy} @click=${() => this._save(true)}>${this._t("save_force")}</button>` : nothing}
      <button class="primary ${s.busy ? "busy" : ""}" data-save-confirm ?disabled=${s.busy} @click=${() => this._save(false)}>
        <ha-icon icon="mdi:content-save"></ha-icon>${this._t("save_button")}</button>`;
    return this._dialogShell("save", this._t("save_title"), body, foot);
  }

  _renderHistory() {
    const h = this._historyState || {};
    const versions = h.versions;
    const body = html`
      <p class="hint">${this._t("history_intro")}</p>
      ${versions === null ? html`<p class="hint">${this._t("loading")}</p>` : !versions.length
        ? html`<p class="hint" data-history-empty>${this._t("history_empty")}</p>`
        : html`<div class="history">
          <div class="history-list">${versions.map((v) => html`<button class=${h.pick === v.id ? "on" : ""} data-version=${v.id}
            @click=${() => this._pickVersion(v.id)}>
            <span>${new Date(v.time).toLocaleString(this._state.language)}</span>
            <small>${[v.user ? this._t("history_by", { user: v.user }) : "", v.note].filter(Boolean).join(" · ")}</small>
          </button>`)}</div>
          <div>${h.pick ? (h.text === null ? html`<p class="hint">${this._t("loading")}</p>` : html`
              <p class="hint">${this._t("history_against")}</p>
              ${this._renderDiff(h.text, this._saved)}
              <div class="actions"><button class="primary" data-restore=${h.pick} @click=${() => this._restoreVersion(h.pick)}>
                <ha-icon icon="mdi:backup-restore"></ha-icon>${this._t("history_restore")}</button></div>`)
            : html`<p class="hint">${this._t("history_pick")}</p>`}</div>
        </div>`}`;
    return this._dialogShell("history", this._t("history_title"), body);
  }

  /** ⚙: the look and the language at hand; a choice works at once and the window stays open. */
  _renderGear() {
    return html`<div class="menu-pop gear-box" data-gear-box>
      <span class="gear-title">${this._t("gear_title")}</span>
      <span class="gear-label">${this._t("gear_theme")}</span>
      <div class="segmented" role="group" aria-label=${this._t("gear_theme")}>
        ${THEMES.map((theme) => html`<button class=${theme === this._theme ? "on" : ""} data-gear-theme=${theme}
          aria-pressed=${theme === this._theme ? "true" : "false"} @click=${() => this._setTheme(theme)}>
          ${this._t(`theme_choice_${theme}`)}</button>`)}
      </div>
      <span class="gear-label">${this._t("language")}</span>
      <div class="segmented" role="group" aria-label=${this._t("language")}>
        ${LANGUAGES.map((code) => html`<button class=${code === this._state.language ? "on" : ""} data-gear-language=${code}
          aria-pressed=${code === this._state.language ? "true" : "false"} @click=${() => this._setLanguage(code)}>
          ${this._t(`language_${code}`)}</button>`)}
      </div>
      <button class="gear-all" data-gear-all @click=${() => { this._gear = false; this._select("look"); }}>
        <ha-icon icon="mdi:palette-outline"></ha-icon>${this._t("gear_all")}</button>
    </div>`;
  }

  /** "Look and language" in the tree: the same choices as ⚙, as a view of its own. */
  _lookView() {
    const { el, card } = common;
    const group = (items, current, attr, pick) => {
      const box = el("div", { class: "segmented", role: "group" });
      for (const [value, label] of items) {
        const button = el("button", { class: value === current ? "on" : "", [attr]: value, onclick: () => {
          for (const other of box.children) other.classList.toggle("on", other === button);
          pick(value);
        } }, label);
        box.append(button);
      }
      return box;
    };
    return card(this._t("gear_title"), null,
      el("div", { class: "look-view" },
        el("p", { class: "hint" }, this._t("look_intro")),
        el("span", { class: "gear-label" }, this._t("gear_theme")),
        group(THEMES.map((theme) => [theme, this._t(`theme_choice_${theme}`)]), this._theme, "data-look-theme",
          (theme) => this._setTheme(theme)),
        el("span", { class: "gear-label" }, this._t("language")),
        group(LANGUAGES.map((code) => [code, this._t(`language_${code}`)]), this._state.language, "data-look-language",
          (code) => this._setLanguage(code)),
        el("p", { class: "hint" }, `${this._t("logged_in", { user: this._state.studio?.user || "?" })} · ${this._state.studio?.version || ""}`)));
  }

  _renderGuide() {
    const body = html`<div class="guide-body" data-guide-body .innerHTML=${this._state.help?.guide || ""}></div>`;
    const foot = html`<a class="btn" href=${`/docs/${this._state.language === "pl" ? "pl" : "en"}/`} target="_blank" rel="noopener">
      ${this._t("docs")}</a>`;
    return this._dialogShell("guide", this._t("guide_button"), body, foot);
  }
}

if (!customElements.get(APP_TAG)) customElements.define(APP_TAG, RouterTrainerStudio);

// the tree's helpers for the tests of the page
export { buildOutline, findNode };
