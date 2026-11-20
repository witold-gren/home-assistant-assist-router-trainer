// The tree of the studio: the steps in the order they are done, then the settings (trainer.yaml).
// A node: {key, icon, label, children, count?, warn?, hint?, busy?, done?} (done: the step is behind you, a ✓); groups: {key: "g:…", label, children}.

export const VIEWS = ["overview", "auto", "ha", "router", "tests", "generate", "datasets", "train", "live", "jobs", "runs",
  "compare", "try", "settings", "look", "power", "machine", "account"];

// the parts of trainer.yaml with a form of their own (key in the tree -> path in the file)
export const SETTINGS = [
  ["ollama", "mdi:robot-outline"],
  ["teacher", "mdi:account-key-outline"],
  ["generate", "mdi:creation"],
  ["test", "mdi:clipboard-check-outline"],
  ["holdout", "mdi:snowflake"],
  ["dataset", "mdi:database-outline"],
  ["export", "mdi:export-variant"],
  ["evaluate", "mdi:scale-balance"],
];

const node = (key, icon, label, extra = {}) => ({ key, icon, label, children: [], ...extra });

export function buildOutline({ state, data, t }) {
  const status = state?.status || {};
  const tests = status.tests?.tests || [];
  const active = status.tests?.active;
  const datasets = status.datasets || [];
  const runs = status.runs || [];
  const job = status.job;
  const router = state?.router || {};
  const snapshot = status.snapshot;
  const models = Object.keys(data?.models || state?.status?.model_settings || {});
  const routerWarn = router.ha_version && !router.matches ? t("router_mismatch", { used: router.version || "?", ha: router.ha_version }) : null;
  const haWarn = state?.ha?.rejected ? t("ha_token_rejected") : null;
  return [
    {
      key: "g:start", label: t("g_start"), children: [
        node("overview", "mdi:view-dashboard-outline", t("n_overview")),
        node("auto", "mdi:brain", t("n_auto"), { busy: job?.running && job.kind === "auto" }),
      ],
    },
    {
      key: "g:ha", label: t("g_ha"), children: [
        node("ha", "mdi:home-assistant", t("n_ha"), { warn: haWarn, hint: state?.ha?.checked?.name, done: Boolean(state?.inputs) }),
        node("router", "mdi:source-branch", t("n_router"), { warn: routerWarn, count: router.version || undefined, done: Boolean(router.matches) }),
      ],
    },
    {
      key: "g:test", label: t("g_test"), children: [
        node("tests", "mdi:clipboard-check-outline", t("n_tests"), {
          count: tests.length,
          done: Boolean(active && tests.some((test) => test.name === active)),
          children: tests.map((test) => node(`test/${test.name}`, test.name === active ? "mdi:star" : "mdi:clipboard-text-outline",
            test.name === "ha" ? t("test_ha") : test.name, { hint: test.name === active ? t("test_active") : undefined })),
        }),
      ],
    },
    {
      key: "g:dataset", label: t("g_dataset"), children: [
        node("generate", "mdi:creation", t("n_generate"), { busy: job?.running && job.kind === "data", done: datasets.length > 0 }),
        node("datasets", "mdi:database-outline", t("n_datasets"), {
          count: datasets.length,
          children: datasets.map((d) => node(`dataset/${d.name}`, "mdi:table", d.name, {
            warn: snapshot?.fingerprint && d.fingerprint && d.fingerprint !== snapshot.fingerprint ? t("fingerprint_warning") : null,
          })),
        }),
      ],
    },
    {
      key: "g:train", label: t("g_train"), children: [
        node("train", "mdi:play-circle-outline", t("n_train"), { busy: job?.running && job.kind === "train", done: runs.length > 0 }),
        node("live", "mdi:chart-line", t("n_live"), { busy: Boolean(job?.running) }),
        node("jobs", "mdi:console", t("n_jobs")),
        node("runs", "mdi:history", t("n_runs"), {
          count: runs.length,
          done: runs.some((r) => r.export),
          children: runs.map((r) => node(`run/${r.name}`, r.compare ? "mdi:check-decagram-outline" : r.export ? "mdi:export-variant" : "mdi:brain",
            r.name)),
        }),
      ],
    },
    {
      key: "g:validate", label: t("g_validate"), children: [
        node("compare", "mdi:scale-balance", t("n_compare"), { count: runs.filter((r) => r.compare).length, done: runs.some((r) => r.compare) }),
        node("try", "mdi:message-text-outline", t("n_try")),
      ],
    },
    {
      key: "g:settings", label: t("g_settings"), children: [
        node("look", "mdi:palette-outline", t("gear_title")),
        node("settings", "mdi:file-cog-outline", "trainer.yaml", {
          children: [
            ...SETTINGS.map(([key, icon]) => node(`settings/${key}`, icon, t(`s_${key}`))),
            node("settings/models", "mdi:brain", t("s_models"), {
              children: models.map((m) => node(`settings/models/${m}`, "mdi:chip", m)),
            }),
          ],
        }),
        node("power", "mdi:power", t("n_power")),
        node("machine", "mdi:server", t("n_machine")),
        node("account", "mdi:account-key-outline", t("n_account")),
      ],
    },
  ];
}

/** The tree with only the nodes whose label holds the text (and their ancestors). */
export function filterOutline(groups, search) {
  const text = search.trim().toLowerCase();
  if (!text) return groups;
  const keep = (item) => {
    const children = (item.children || []).map(keep).filter(Boolean);
    return item.label.toLowerCase().includes(text) || children.length ? { ...item, children } : null;
  };
  return groups.map((group) => ({ ...group, children: group.children.map(keep).filter(Boolean) }))
    .filter((group) => group.children.length);
}

export function flattenOutline(items) {
  return items.flatMap((item) => [item, ...flattenOutline(item.children || [])]);
}

export function findNode(groups, key) {
  return flattenOutline(groups.flatMap((group) => group.children)).find((item) => item.key === key) || null;
}
