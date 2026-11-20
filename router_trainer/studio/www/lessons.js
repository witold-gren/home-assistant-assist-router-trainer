// The lessons of the studio (gpu-studio.md section 5a): every main task of the trainer as a short tour (tour.js) that
// goes where the task is done (a node of the tree, ⚙) and frames one part at a time; a step may wait for the framed
// button to be clicked (`advance: "click"`), so the task is done while learnt. The list (⚙ → Lessons) is in three
// groups and marks the ones gone through; a lesson that needs something the workspace has not got yet says what.
// The "?" of a card offers the lesson of its place ("Show me step by step").

import { lessonsDone } from "./tour.js";

const choose = (key) => (app) => {
  app._gear = false;
  app._yamlAll = false;
  app._dialog = null;
  app._select(key);
};
const status = (app) => app?._state?.status || {};
const firstRun = (app) => status(app).runs?.[0]?.name;
const activeTest = (app) => status(app).tests?.active || status(app).tests?.tests?.[0]?.name;
const firstDataset = (app) => status(app).datasets?.[0]?.name;

/** What a lesson needs in the workspace, and whether it has it. */
export const NEEDS = {
  test: (app) => Boolean(activeTest(app)),
  dataset: (app) => Boolean(firstDataset(app)),
  run: (app) => Boolean(firstRun(app)),
};

export const LESSONS = [
  // --- the start: from nothing to a model in use -------------------------------------------------------------
  {
    key: "connect",
    icon: "mdi:home-assistant",
    help: ["inputs"],
    steps: [
      { key: "url", targets: ["[data-ha-url]"], side: "left", prepare: choose("ha") },
      { key: "token", targets: ["[data-ha-token]"], side: "left" },
      { key: "check", targets: ["[data-ha-connect]"], side: "left", advance: "click" },
      { key: "state", targets: ["[data-ha-state]"], fallback: ["[data-ha-connect]"], side: "left" },
    ],
  },
  {
    key: "fetch",
    icon: "mdi:cloud-download-outline",
    help: ["router"],
    steps: [
      { key: "fetch", targets: ["[data-ha-fetch]"], side: "left", prepare: choose("ha") },
      { key: "summary", targets: ["[data-fetch-summary]"], fallback: ["[data-ha-fetch]"], side: "left" },
      { key: "router", targets: ["[data-router-ok]", "[data-router-mismatch]", "[data-router-fetch]"], side: "left", prepare: choose("router") },
      { key: "done", targets: ["[data-node='ha']", "[data-node='router']"], side: "right" },
    ],
  },
  {
    key: "auto",
    icon: "mdi:brain",
    help: ["auto"],
    steps: [
      { key: "test", targets: ["[data-auto-test]"], side: "left", prepare: choose("auto") },
      { key: "models", targets: ["[data-view='auto'] [data-chip]"], side: "left" },
      { key: "options", targets: ["[data-auto-router-only]", "[data-auto-upload]"], side: "left" },
      { key: "start", targets: ["[data-auto-start]"], side: "left" },
      { key: "power", targets: ["[data-power-card]"], fallback: ["[data-side]"], side: "left" },
    ],
  },
  {
    key: "result",
    icon: "mdi:check-decagram-outline",
    help: [],
    steps: [
      { key: "card", targets: ["[data-auto-result]"], fallback: ["[data-auto-start]"], side: "left", prepare: choose("auto") },
      { key: "recommended", targets: ["[data-auto-recommended]"], fallback: ["[data-auto-result]", "[data-auto-start]"], side: "left" },
      { key: "use", targets: ["[data-use-model]", "[data-model-in-use]"], fallback: ["[data-auto-result]", "[data-auto-start]"], side: "left" },
      { key: "restore", targets: ["[data-restore-model]", "[data-router-model]"], fallback: ["[data-auto-result]", "[data-auto-start]"], side: "left" },
    ],
  },
  {
    key: "progress",
    icon: "mdi:chart-line",
    help: ["live"],
    steps: [
      { key: "chart", targets: ["[data-loss-chart]", "[data-progress]"], fallback: ["[data-middle]"], side: "left", prepare: choose("live") },
      { key: "overfit", targets: ["[data-overfit]"], fallback: ["[data-loss-chart]", "[data-middle]"], side: "left" },
      { key: "top", targets: ["[data-job-pill]", "[data-machine]"], fallback: ["[data-node='live']"], side: "below" },
      { key: "stop", targets: ["[data-stop]"], fallback: ["[data-middle]"], side: "left" },
    ],
  },
  // --- further: each step on its own ---------------------------------------------------------------------------
  {
    key: "test",
    icon: "mdi:clipboard-check-outline",
    help: ["test", "review"],
    needs: "test",
    steps: [
      { key: "list", targets: ["[data-test-card]"], side: "left", prepare: choose("tests") },
      { key: "new", targets: ["[data-testgen]"], side: "left" },
      { key: "review", targets: ["[data-review]"], fallback: ["[data-middle]"], side: "left", prepare: (app) => choose(`test/${activeTest(app)}`)(app) },
      { key: "case", targets: ["[data-case]"], fallback: ["[data-review]", "[data-middle]"], side: "left" },
    ],
  },
  {
    key: "generate",
    icon: "mdi:creation",
    help: ["generate"],
    steps: [
      { key: "what", targets: ["[data-view='generate']"], side: "inside", prepare: choose("generate") },
      { key: "start", targets: ["[data-generate]"], side: "left" },
      { key: "settings", targets: ["[data-view='settings/generate']"], side: "inside", prepare: choose("settings/generate") },
      { key: "yaml", targets: ["[data-side-yaml]"], side: "left" },
    ],
  },
  {
    key: "dataset",
    icon: "mdi:database-outline",
    help: ["dataset"],
    needs: "dataset",
    steps: [
      { key: "list", targets: ["[data-dataset]"], side: "left", prepare: choose("datasets") },
      { key: "one", targets: ["[data-view^='dataset/']"], side: "inside", prepare: (app) => choose(`dataset/${firstDataset(app)}`)(app) },
      { key: "fingerprint", targets: ["[data-fingerprint]"], fallback: ["[data-view^='dataset/']"], side: "left" },
    ],
  },
  {
    key: "train",
    icon: "mdi:play-circle-outline",
    help: ["training"],
    steps: [
      { key: "models", targets: ["[data-chip]"], side: "left", prepare: choose("train") },
      { key: "dataset", targets: ["[data-dataset]"], fallback: ["[data-chip]"], side: "left" },
      { key: "then", targets: ["[data-then-export]", "[data-power-after-start]"], fallback: ["[data-chip]"], side: "left" },
      { key: "start", targets: ["[data-start]"], side: "left" },
      { key: "settings", targets: ["[data-view^='settings/models']"], side: "inside", prepare: choose("settings/models") },
    ],
  },
  {
    key: "resume",
    icon: "mdi:restart",
    help: [],
    steps: [
      { key: "button", targets: ["[data-resume]"], fallback: ["[data-start]"], side: "left", prepare: choose("train") },
      { key: "notes", targets: ["[data-resume-notes]"], fallback: ["[data-resume]", "[data-start]"], side: "left" },
      { key: "jobs", targets: ["[data-job-history]", "[data-view='jobs']"], side: "inside", prepare: choose("jobs") },
    ],
  },
  {
    key: "compare",
    icon: "mdi:scale-balance",
    help: ["runs", "validation"],
    needs: "run",
    steps: [
      { key: "runs", targets: ["[data-run]"], side: "left", prepare: choose("runs") },
      { key: "export", targets: ["[data-export]", "[data-evaluate]"], fallback: ["[data-view^='run/']"], side: "left", prepare: (app) => choose(`run/${firstRun(app)}`)(app) },
      { key: "table", targets: ["[data-compare]"], fallback: ["[data-view='compare']"], side: "inside", prepare: choose("compare") },
      { key: "parts", targets: ["[data-part]"], fallback: ["[data-compare]", "[data-view='compare']"], side: "left" },
    ],
  },
  {
    key: "try",
    icon: "mdi:message-text-outline",
    help: ["try"],
    steps: [
      { key: "text", targets: ["[data-try-text]"], side: "left", prepare: choose("try") },
      { key: "models", targets: ["[data-view='try'] [data-chip]"], fallback: ["[data-try-text]"], side: "left" },
      { key: "go", targets: ["[data-try]"], side: "left" },
      { key: "out", targets: ["[data-try-out]"], fallback: ["[data-try]"], side: "left" },
    ],
  },
  {
    key: "jobs",
    icon: "mdi:console",
    help: [],
    steps: [
      { key: "list", targets: ["[data-job-history]", "[data-view='jobs']"], side: "inside", prepare: choose("jobs") },
      { key: "log", targets: ["[data-job-history-log]", "[data-side-job-card]"], fallback: ["[data-side]"], side: "left" },
      { key: "live", targets: ["[data-node='live']"], side: "right" },
    ],
  },
  // --- set up once ---------------------------------------------------------------------------------------------
  {
    key: "teacher",
    icon: "mdi:account-key-outline",
    help: [],
    steps: [
      { key: "roles", targets: ["[data-teacher-provider]"], side: "left", prepare: choose("settings/teacher") },
      { key: "key", targets: ["[data-teacher-key]"], fallback: ["[data-teacher-provider]"], side: "left" },
      { key: "check", targets: ["[data-teacher-check]"], side: "left" },
    ],
  },
  {
    key: "handoff",
    icon: "mdi:swap-horizontal",
    help: [],
    steps: [
      { key: "manual", targets: ["[data-teacher-provider]"], side: "left", prepare: choose("settings/teacher") },
      { key: "export", targets: ["[data-handoff-export]"], fallback: ["[data-view='settings/teacher']"], side: "left" },
      { key: "import", targets: ["[data-handoff-import]", "[data-handoff-file]", "[data-handoff-text]"], fallback: ["[data-view='settings/teacher']"], side: "left" },
    ],
  },
  {
    key: "settings",
    icon: "mdi:file-cog-outline",
    help: ["settings"],
    steps: [
      { key: "form", targets: ["[data-view='settings/generate']"], side: "inside", prepare: choose("settings/generate") },
      { key: "side", targets: ["[data-side-yaml]"], side: "left" },
      { key: "draft", targets: ["[data-draft-state]", "[data-undo]", "[data-redo]"], side: "below" },
      { key: "save", targets: ["[data-save]"], side: "below-end" },
      // History opens a modal window, which would cover the bubble: the lesson says what is there instead
      { key: "history", targets: ["[data-history]"], side: "below-end" },
    ],
  },
  {
    key: "yaml",
    icon: "mdi:code-braces",
    help: [],
    steps: [
      { key: "button", targets: ["[data-yaml]"], side: "below-end", prepare: choose("settings") },
      { key: "whole", targets: ["[data-yaml-all]"], fallback: ["[data-middle]"], side: "inside", prepare: (app) => { app._yamlAll = true; } },
      { key: "back", targets: ["[data-tree]"], side: "right", prepare: (app) => { app._yamlAll = false; } },
    ],
  },
  {
    key: "power",
    icon: "mdi:power",
    help: ["power", "machine"],
    steps: [
      { key: "switch", targets: ["[data-view='power']"], side: "inside", prepare: choose("power") },
      { key: "save", targets: ["[data-power-save]"], fallback: ["[data-view='power']"], side: "left" },
      { key: "after", targets: ["[data-power-card]"], fallback: ["[data-side]"], side: "left" },
      { key: "machine", targets: ["[data-view='machine']"], side: "inside", prepare: choose("machine") },
    ],
  },
  {
    key: "look",
    icon: "mdi:palette-outline",
    help: [],
    steps: [
      { key: "gear", targets: ["[data-settings]"], side: "below-end", advance: "click", prepare: (app) => { app._gear = false; } },
      { key: "choices", targets: ["[data-gear-box]"], fallback: ["[data-settings]"], side: "left" },
      { key: "learn", targets: ["[data-gear-tour]", "[data-gear-lessons]"], fallback: ["[data-settings]"], side: "left" },
    ],
  },
];

// The three groups of the list: the start, further steps, set up once.
export const GROUPS = [
  ["lessons_start", ["connect", "fetch", "auto", "result", "progress"]],
  ["lessons_more", ["test", "generate", "dataset", "train", "resume", "compare", "try", "jobs"]],
  ["lessons_once", ["teacher", "handoff", "settings", "yaml", "power", "look"]],
];

export const lessonByKey = (key) => LESSONS.find((lesson) => lesson.key === key) ?? null;

/** The lesson for the "?" of a card (its help key), or null. */
export const lessonFor = (helpKey) => LESSONS.find((lesson) => lesson.help.includes(helpKey)) ?? null;

/** Whether a lesson can run in this workspace: what it needs is there. */
export const lessonReady = (lesson, app) => !lesson.needs || NEEDS[lesson.needs](app);

export { lessonsDone };
