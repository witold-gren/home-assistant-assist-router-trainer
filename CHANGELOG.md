# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions: [SemVer](https://semver.org/).

## [Unreleased]

## [0.4.1] - 2026-11-20

### Added
- **Tuning lessons** (⚙ → Lessons → Tuning): compare different models, tune the training (epochs, learning rate,
  LoRA, batch, memory - when to raise or lower each), what to fix when the result is weak, how many and which
  sentences, speech (recordings, Piper, Whisper), contrast pairs, commands and answers, the test's size and
  protection; and two set up once: your home's words, Ollama / export / evaluation. 29 lessons in all.
- Forms for what had none: speech and the label check, contrast pairs (`pairs`, `extra`, `max_pairs`) in
  Generation; a new **Your home's words** part (`topic_overrides`, `intent_topics`, `fallback_topic`,
  `slot_values`, music, shopping); **Add a model** on the list of models (the parameters copied from the first).
- Saving checks the contrast pairs, `topic_overrides`, `intent_topics` and `slot_values` (a typo stopped a job
  hours later before).
- Guide: every parameter in Doing it well → Parameters, new recipes (topics mixed up, dropped labels, gibberish,
  the small model behind the base, a new topic, commands with "Only the topic").

### Changed
- Lessons: Next on a step that waits for a click does what the click does (⚙ opens), so the following steps have
  their part; a lesson waits only for quick buttons (a list in `lessons.js`, checked by a test) - training, export,
  "Use in Assist Router", Stop and switching off are only framed.
- The bubble never covers its frame: when the chosen side has no room the other sides are tried.

### Fixed
- The studio's container ran in UTC: the dates of files, logs and jobs were 1-2 hours off Home Assistant's. It
  takes the machine's time zone now (`/etc/localtime`, gpu-studio.md section 3); after `make deploy`.
- A part cut off by its scrolled column (not only by the window) is scrolled to, once a step.

## [0.4.0] - 2026-11-20

### Added
- **Automatic training** (Start → Automatic training, `router-trainer auto`): one Start for the whole road as one
  job - fetching from Home Assistant and the router code of its version, the test (Home Assistant's own or a new
  one for the home, no review waiting), the snapshot, generating, the dataset, training of each chosen model,
  export to the home Ollama and the comparison with the router model Assist Router uses now. The **Result** card
  shows per model the accuracy and the time of choosing the topic, new against now, a verdict and the recommended
  model.
- **Use in Assist Router** (after a confirmation; `router-trainer router-model --use MODEL`): sets the router model
  in Assist Router's options through Home Assistant's own options flow, the other options untouched; a model that
  is not in the home Ollama is refused. **Restore** puts the earlier model back.
- Guide: "Automatic training" in Step by step (PL/EN).
- **Tour of the studio** (gpu-studio.md section 5a): the first time the studio opens in a browser, one part of the
  screen at a time is framed with a bubble saying what it is and where it is set; ⚙ → Tour of the studio shows it
  again, Esc or Skip ends it.
- **Lessons** (⚙ → Lessons): 19 tasks of the trainer in three groups (the start, further steps, set up once), each a
  short tour that goes where the task is done, frames one thing at a time and moves on when the framed button is
  clicked; done lessons get a ✓. The "?" of a card offers its lesson ("Show me step by step"). Guide: The screen →
  The tour and the lessons, two FAQ entries.
- **Fixed contrast pairs** (`generate.router.contrast.extra`): pairs always added to the automatic ones (or to the
  list), first - for a new topic that has no evaluation errors yet.
- **Real speech in the router data:** natural questions read by Piper (every voice of the language) and written
  by Whisper of Home Assistant - the real mistakes of speech recognition with the right topic; and the home's own
  voice commands from `inputs/recordings` (Home Assistant's `debug_recording_dir`), written by Whisper and labelled
  by the teacher. Resumable; skipped when the home server does not answer.
- Automatic training: **Only choosing the topic** (`--roles router`) - no commands and answers are generated or
  trained when the small model only takes over the router.
- **Label check** of the router data (`check_labels`): every teacher sentence is read once more with the router's
  own prompt; one that lands in another topic is dropped with its Whisper copies and the paraphrases refill it
  (`generated/labels.json`, `generated/labels_dropped.jsonl`).
- **Voice recordings from Home Assistant** (Assist Router 0.1.11+): "Fetch from HA", `router-trainer fetch` and the
  automatic training bring the new speech-to-text recordings of `assist_pipeline: debug_recording_dir` into
  `inputs/recordings` (only the ones not there yet) - no copying by hand.
- **Home Assistant's `custom_sentences`** become router examples (source `custom`), like the built-in intents; an
  intent of the home's own `intent_script` gets the teacher's topic or `topic_overrides` `intent:<name>`.
- `router-trainer triggers`: every sentence trigger with its `id#number` key, topic and how it got it - the list
  to write `topic_overrides` from for a new home. `topic_overrides` take one trigger of an automation (`id#n`).
- `router-trainer languages [--check CODE]`: the language packs and what a new pack still lacks.
- Guide: **How the data is made** (every stage, from Home Assistant to the dataset, and the steps for a new home)
  and **A new language** (PL/EN).
- **Contrast pairs** (`contrast`): sentences on both sides of the border of topics that get mixed up, the pairs
  taken from the errors of the last evaluations (`pairs: auto`) or listed.

- **The teacher of each role** (`teacher.writer`, `teacher.judge`, `teacher.test_writer`): the
  studio's Ollama, any OpenAI-compatible API (OpenAI, OpenRouter, Groq, LM Studio, vLLM), Claude
  (Anthropic API: structured outputs, a fallback model when a request is declined) or by hand -
  e.g. Claude writes, the local Gemma judges. API answers are remembered (`generated/teacher/`), keys
  saved in the studio (`workspace/secrets`, mode 600), Check per role, a privacy warning. Settings →
  Teacher; guide: The teacher.
- **By hand** (`provider: manual`, `router-trainer handoff export|import writer|judge`, studio
  Export / Import): the writer's tasks (paraphrases, contrast pairs, commands per plan) for any AI
  chat, the answers back as rows of the source `external` with the same checks; the judge's
  sentences as prompts or a table to fill in - unjudged sentences wait outside the dataset.
- **A new language**: `router-trainer language new CODE [--home] [--answers FILE]` writes a checked
  machine translation of both packs, an example `router.yaml` and the test into
  `workspace/languages/<code>/`, with `REVIEW.md` for a speaker; `router-trainer language check
  CODE` runs both packs' checks. Guide: A new language (rewritten).
- **Language packs as folders** (`languages/pl/`: `texts.yaml`, `words.yaml`, `grammar.py`): the
  teacher prompts are `str.format` templates a translator edits without Python;
  `router-trainer languages --check CODE|FOLDER` lists a pack's problems (names, `{fields}`, prompts
  that do not fill in).

### Changed
- Language: without `language:` in `router.yaml` the data are made in Home Assistant's language (as the
  integration does), when there is a pack for it. Automation triggers are read in the router language (they were
  read as Polish) and Wikipedia titles come from `wikipedia_language` (they came from the Polish Wikipedia).
  Inflection of test facts, the „Below the article” word and the state words that are ordinary words moved to the
  language pack; accents and speaker names are handled for any language with Latin letters.
- Generating is faster: every teacher call uses one context (Ollama reloaded the model whenever writing and
  checking alternated between 4096 and 8192), the trainer's Ollama runs with two slots, flash attention and a
  q8_0 cache, and control commands are written and read back in rounds, side by side.
- Control commands: numbers as people say them („22”, „22,5” instead of „22.0”), and the "with a reason" style
  asks for a short reason only.

### Fixed
- The demo answered the Automatic training view's question about Assist Router's router model with an error
  ("The studio cannot be reached"); it shows the made-up home's model now.
- The judge of the generated test was asked to copy facts "from {what}" literally: the template
  missed its field.
- The log, the recordings and the label check share one store of the judge's topics
  (`generated/labels.json`) - a sentence is never judged twice.
- Control commands that set a value outright („Ustaw 22 stopnie”) were thrown away: the teacher reads them back
  with the change „ustaw”, which is the same as no change. A planned device that is found also counts under
  another domain (a switch and a script of the same name).

## [0.3.0] - 2026-11-18

### Added
- No login on the home network: `STUDIO_TRUSTED_NETWORKS=192.168.1.0/24` (comma-separated, empty by default) in
  `docker/config/env`, written by `make install STUDIO_TRUSTED_NETWORKS=…`. A connection from such a network is
  logged in at once; only the connection's own address counts, never a header. ☰ and Account then say
  "No login needed — this network is trusted" instead of offering to log out.
- The guide is published on GitHub Pages: https://witold-gren.github.io/home-assistant-assist-router-trainer/
  (`.github/workflows/docs.yml`, the same MkDocs requirements and Python as the image's docs stage, strict build).

### Fixed
- The guide links at the top of both READMEs pointed at HTML files that are not in the repository; they now lead to
  the documentation site.

## [0.2.1] - 2026-11-18

### Added
- "From zero to a model" page of the guide (PL and EN): every function of the studio step by step, from the first
  login to the model in Assist Router, with new pictures (⚙ window, look and language, job log, try it, machine check).
- "Look and language" in the tree under Settings (`mdi:palette-outline`); "All look and language" in ⚙ leads to it.
- Tests of the installer on a pretend machine and of the real command line run the way the studio runs jobs.

### Changed
- ⚙ in the top bar opens a small window under itself (theme, language, "All look and language") instead of a
  dialog, styled as in the other studios (segmented theme and language, labels on one line); Esc, a click beside
  it or ⚙ again close it, and ☰ closes the same way. The settings dialog is gone.

### Fixed
- The smoke test uses the router code fetched for the real workspace (in the container nothing lies next to the
  trainer), and the training step starts in the trainer's folder again.
- compose builds the studio stage by name (`target: app`), never the last stage of the Dockerfile by chance.
- The installer names the user with `id -un` (no `$USER` under `set -u`) and stops on an NVIDIA driver older
  than 580, which the image's CUDA 13.0 needs.
- Reviewing the test from Home Assistant before the first fetch shows one clear line, not a Python traceback.

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
