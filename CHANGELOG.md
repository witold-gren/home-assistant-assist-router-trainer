# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions: [SemVer](https://semver.org/).

## [0.2.0] - 2026-11-17

### Added
- Guide: a "One standard" page (PL/EN) - everything changed in the trainer to follow the shared standard of the
  house's apps: the studio in Docker, data from Home Assistant, look, speed, documentation, make commands, tests.
- **The same make commands as every GPU studio** (gpu-studio.md §2): `make help` in the standard's groups:
  1. Start (only Docker Desktop: `demo`, `demo-clean`, `docs`, `docs-serve`, `doctor`), 2. GPU machine,
  3. Development, then the trainer's own commands on the machine. `docs`, `docs-build` and `docs-serve` run in
  Docker (the Dockerfile's `docs` stage; `docs-serve` on http://localhost:9791 with `docs/` mounted), without
  `.venv` or the Assist Router repository. `make doctor` runs on the Mac without `setup`: Docker, Chrome, uv,
  `GPU_HOST` and ssh, then the GPU, Unsloth and Ollama in the container through ssh; it installs nothing.
  `make test` never builds images (`-m "not docker"`), `make test-docker` does, `make test-all` = lint + test +
  test-browser + test-docker. `.venv` through uv with `PYTHON_VERSION` (3.13, what Home Assistant of the
  router's test requirements needs); without uv a message with the install command. FAQ entries for the new
  messages (PL/EN).
- **Try it on a Mac with only Docker Desktop** (gpu-studio.md §8b): `make demo` builds a small demo image
  (`docker/Dockerfile` target `demo`: Python slim, no CUDA or training libraries, arm64 and amd64; the Assist
  Router code from the repository next to this one when it is there, else its tag from GitHub) and runs it with
  `docker run --rm --init` on http://localhost:8791, demo/demo; Ctrl+C removes the container, `make demo-clean`
  the image; without Docker a plain message. The old demo from `.venv` is `make demo-local`. The same short
  section in both READMEs and on the Installation page (PL/EN, `#try-on-a-mac`); tests check it against the
  Makefile, and a `docker` test builds the image, logs in and checks that no container is left.

### Changed
- `make doctor` now runs on the Mac (it was a check inside the container on the machine; that part runs through
  ssh). `make clean` also removes `.venv`. `make docs` no longer needs Python.
- **The studio replaces the panel and the Mac → SSH road.** The trainer runs only on the Ubuntu GPU
  machine, in Docker (`docker/Dockerfile`, `docker/compose.yaml`, `docker/install-ubuntu.sh`,
  `make install`): the image holds both environments, the trainer's Ollama and llama.cpp (built by
  `scripts/setup.sh --deps-only`), the code is the last, quick layer; `restart: unless-stopped` starts
  the studio with the machine. Removed: `deploy.py`, `scripts/deploy.sh`, `scripts/install-service.sh`,
  the SSH backend, the old static panel (`router-trainer ui` is now the studio).
- The studio (`router-trainer studio`, `router_trainer/studio/`) follows the wake word studio and the
  Home Dashboard / Assist Router editors: login (`ROUTER_TRAINER_UI_AUTH`, signed cookie, pause after
  failed logins), one `POST /api/call`, a tree of the steps, views with a "?" each, live GPU and job,
  trainer.yaml as forms with a server-side draft, undo/redo, save with the changed parts and lines
  (a changed value replaces only itself - comments and their alignment stay), conflict "Save anyway",
  history of 30 versions; switching the machine off 120 s after a job (cancellable, never after Stop).
- Inputs come from Home Assistant through Assist Router's export command
  (`assist_router/training/export`, Assist Router 0.1.8+, administrator token), not from the config
  share; `router-trainer fetch`.
- `router_repo: auto`: the router code of the version Home Assistant runs, cloned from GitHub into
  the workspace (`router-trainer router`, "Fetch router" in the studio); a red pill when they differ.
- Guide (PL/EN) rewritten as MkDocs Material (`docs/*.md` English, `docs/*.pl.md` Polish, the same
  anchors): what it is, installation, the screen, step by step, doing it well (every parameter with its
  default, range and effect), Home Assistant and power, FAQ, changes; screenshots of the studio in both
  languages (`make screenshots`). Built into the image (`/docs/`, the studio's "?" opens it in a new tab)
  and into "Home documents" (docs-hub, type mkdocs). `make docs`, `make docs-serve`, `make docs-build`.
- Follows the shared GPU studio standard (`~/Home Assistant/standards/gpu-studio.md`): `make install`,
  `deploy`, `login`, `logs`, `status` from the Mac through `GPU_HOST` in `~/.config/gpu-studio/host.mk`
  (or `Makefile.local`); `docker-up/down/logs/shell` on the machine; `demo` (port 8791), `test`,
  `test-browser`, `icons`. Renamed: `show-login` → `login`, `studio-demo` → `demo`, `studio-icons` →
  `icons`, `shell` → `docker-shell`; `make studio` removed (the demo is the local studio).
- Docker: compose runs as the machine's user and has a healthcheck; torch pinned for driver 580 /
  CUDA 13.0 (`TORCH_SPEC`, default `torch==2.14.1`); the guide is its own image stage
  (`mkdocs build --strict`); import self-tests after the environments and after the code;
  `install-ubuntu.sh` switches the old `router-trainer.service` off.
- Top bar in the standard order: menu, icon and name; the job chip (stage, %, time left) and the machine
  chip (GPU %, temperature, memory) with switch-off; the countdown "Switching off in 1:45 · Cancel" and
  its error; the router pill; draft, undo/redo; look, YAML, "?", ⚙, History, Save.
- `make migrate` / `make migrate-finish`: from the old systemd setup to the container.

### Added
- The left and the right column fold to a narrow bar (‹ / ›, Ctrl/⌘+B and Ctrl/⌘+Alt+B), remembered by the
  browser; the right one starts folded in a window narrower than 900 px.
- The tree marks done steps with ✓. A card's "?" opens a small popup next to it (what the card does, a quiet
  link to its part of the guide; ✕, Esc, a click beside it or the "?" close it) - only the top bar's "?"
  opens the guide.
- The page never hangs: the state is asked for again only after the last answer (never two at once,
  not in a background tab), every request has a time limit with a clear message, a test's cases are shown
  150 at a time, the draft is saved one save at a time (changes made meanwhile go in one save after it; a
  failed save is tried again with the next change or on Save, never in a loop). Playwright checks a slow studio, a hidden tab, a request without an answer and long tasks
  over 500 ms on every view.
- The training start card: "Switch the machine off after the job" and what Resume will really train
  ("from step 510 of 806 - 296 steps left", or nothing left).
- Job history (`jobs/history.jsonl`, written by the runner) with each job's whole log; a job whose
  runner vanished (container restart) shows "Interrupted".
- The loss chart: the values of a step on hover, full screen with drag-to-zoom and a pinned step,
  "How to read the chart" (the guide).
- Tests: nothing leaves 127.0.0.1 (blocked at the socket) and switching off in a test is only written
  down (autouse fixtures, `tests/test_safety.py`); the guide (`tests/test_docs.py`: pages, anchors,
  pictures, button names, card links, the parameter table = the code); the Makefile
  (`tests/test_makefile.py`); Playwright for the top bar, the countdown and its cancel, a job's
  progress, the chart and the job history.
- Power of the GPU machine (as in home-assistant-wakeword): step 1 has an optional section with the
  machine's switch in Home Assistant, the plug's power sensor (suggestions from HA) and the "off"
  threshold (5 W), kept in `workspace/home_assistant.json` (now mode 600). The header gets a button
  with the machine's state (off / starting / on · W / shutting down / checking… / no reading from
  HA); a click asks and switches the machine on or off through `switch.turn_on` / `turn_off`. The
  panel never switches the machine off while a job runs on it. Example HA package:
  `docs/home-assistant/maszyna_gpu.yaml`.
- Own icon: a teal speech bubble with branching arrows as the SVG favicon, PNG 32 px, the 180 px
  apple-touch icon and the header logo; the panel's accent colour is teal/green (the wakeword panel
  stays violet).

### Changed
- The page loads at once while the GPU machine is off: `/api/state` answers with the last known state
  and asks the machine (SSH) and Home Assistant in a background thread, one check at a time, with
  the network calls outside the lock. Until the first answer the header status pulses "Checking the
  machine…"; an unexpected failure of the check is shown, never "checking" for ever. Measured with
  the machine off: about 7.1 s per request before, about 0.02 s now.
- Requests to `homeassistant.local` go to its IPv4 address looked up once (kept 5 min): macOS waited
  5 s for an IPv6 mDNS answer on every request. HTTPS keeps the name.
- Home Assistant 403 says what to check: a banned address (`ip_bans.yaml`, e.g. behind a VPN) or a
  user who is not an administrator.
- A remote machine without a host is not reported as a connection error any more.
- A token Home Assistant rejects (401) is sent once only: every 401 is a failed login for HA's
  ip_ban, so the panel stops all questions to HA (machine state, entities, jobs reading the home)
  and says “Home Assistant rejected the token”; “Connect to HA” in step 1 checks it again.
- Power settings: the machine switch and the power sensor are lists of Home Assistant's entities, “name (entity id)” sorted by name (“Loading entities from HA…” meanwhile, “↻ Suggestions from HA” asks again, a saved id HA no longer lists stays, typed by hand when HA gives no list) - the same as in piper-voice-cloner.

## [0.1.0] - 2026-10-27

First version.

### Added
- Data generators for the three roles of Assist Router: router (sentence triggers, built-in HA
  intents, teacher paraphrases, knowledge questions, gibberish, real questions from the log),
  control (commands planned from the home snapshot, written and parsed back by the teacher, kept
  only when the parse matches the plan) and answers (made-up data with facts computed in Python,
  live HA data, Wikipedia summaries).
- The frozen test: training sentences equal or close to a test sentence are dropped (normalized
  text, word stems, character trigrams), when generating and again when building the dataset.
- Datasets in the integration's chat format with a stable dev split and a dataset card.
- Training with Unsloth (LoRA / QLoRA), loss on answers only, checkpoints, stop and resume, metrics
  in the log.
- Export to GGUF, a local check, upload to the home Ollama; the frozen test for the trained and the
  base model with fixed and broken cases.
- The training panel (local or over SSH), background jobs, `router-trainer` CLI, setup and service
  scripts, guide in Polish and English with screenshots (`scripts/screenshots.py`, demo data).
- Home Assistant connection in the panel: address + long-lived token, checked and saved in the
  workspace (mode 600); Home Assistant is only read.
- `scripts/deploy.sh` (`router-trainer deploy`): from the Mac, send everything to the GPU machine,
  build its environments when missing, start the panel there as a service and print its address.
- `Makefile` (as in home-assistant-wakeword): `make help` lists the steps in Polish or English -
  setup, `deploy`, panel and service, `smoke`, `testgen`, `data`, `train`, `resume`, tests.
- The panel: a **Guide** button before the language switch opens the guide of the repository
  (`docs/<lang>/`, served by the panel) in a new tab; a **?** at each step explains what the step
  will do; a favicon. The guide has an FAQ with every known error message and its fix.
- `router-trainer smoke`: the whole road in miniature in a separate workspace (small data, a short
  E2B training, export, test against the base model), the smoke model removed afterwards.
