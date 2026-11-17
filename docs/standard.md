# One standard {#standard}

The trainer is one of several apps of the house: the wake word studio, Piper Voice Cloner, the Home Dashboard
editor and the Assist Router editor. They all follow **one shared standard** (`gpu-studio.md`), which gives them:

- the same commands;
- the same look and behaviour of the studio;
- documentation built the same way;
- the same rules for tests.

Once you know one of them, you know your way around the others.

This page lists everything that had to change in the trainer to meet the standard (November 2026). The details
of each change are in the last chapter, "Changelog".

## In short {#summary}

| Area | Before | After |
|---|---|---|
| Where it runs | a stdlib HTTP panel on Ubuntu, driven from the Mac over SSH, a systemd service | a studio in Docker on the GPU machine, starting with the machine |
| Data from Home Assistant | files copied from a Samba share | Assist Router's `assist_router/training/export` command (read-only, over the API) |
| Router code | a copy from the Mac's disk | the GitHub tag of the version Home Assistant runs |
| Look | its own panel with 5 steps | a studio like the editors: tree, middle, live cards, top bar |
| Settings | editing `trainer.yaml` by hand | forms, a draft, undo/redo, save with a diff, a history of 30 versions |
| Documentation | static HTML pages | MkDocs Material, PL and EN with the same anchors, pictures from the demo |
| Commands | its own names (`studio`, `studio-demo`, `show-login`…) | the shared names and groups of `make help` |
| Trying it | Python, uv and the router repository on the Mac | only Docker Desktop: `make demo` |
| Tests | 96 | 197 (18 of them in the browser, 2 with Docker) |

## The studio in Docker {#docker}

- **One image for the GPU machine** (`docker/Dockerfile`), with layers from the slowest to the quickest to rebuild:
  - system packages;
  - the environments of `scripts/setup.sh`: Home Assistant with the router's test requirements, Unsloth, the
    trainer's Ollama and llama.cpp;
  - the code last, so a code change rebuilds only that layer.
- **Self-tests** after the layers: both environments import and the guide is there.
- **torch pinned** with `TORCH_SPEC`, by default `torch==2.14.1` for driver 580 / CUDA 13.0. Unpinned, pip takes a
  newer CUDA that the driver cannot run.
- **Compose:**
  - the machine's UID/GID, a healthcheck and `restart: unless-stopped`, so the studio comes up with the machine;
  - data in `docker/data/`, the login in `docker/config/env` (mode 600).
- **`docker/install-ubuntu.sh`:**
  - checks Docker, Compose, permissions, the driver, the NVIDIA Container Toolkit and free space;
  - writes the login, enables Docker at boot, builds and starts the studio;
  - switches the old `router-trainer.service` off.
- **Removed:** the SSH mode, `deploy.py`, `scripts/deploy.sh`, `scripts/install-service.sh` and the old panel
  (copies in `backup/`).
- **The guide in the image:** its own `docs` stage builds it with `--strict`, and the studio serves it at `/docs/`,
  also without the internet.

## Data from Home Assistant {#ha-data}

- Assist Router got the command `assist_router/training/export`: administrators only, read-only. It returns:
  - `router.yaml`;
  - the log of unrecognized sentences;
  - the test files;
  - the automations with a conversation trigger, also those from `packages/`;
  - the `custom_sentences` files.
- The trainer needs only the address of Home Assistant and a token. No Samba share.
- The studio compares the router version in Home Assistant with its own and fetches the code of that version from
  GitHub (`router_repo: auto`).

## How the studio looks and behaves {#studio}

The same as the other studios and editors:

- **The top bar:**
  - ☰, the icon and the name;
  - a job chip (stage, percent, time left) and a machine chip (GPU, temperature, memory, switching off);
  - a power-off countdown with Cancel, the router version pill, the draft, undo/redo;
  - theme, YAML, **?** (the whole guide in a new tab), settings, history, save.
- **Three columns with movable dividers:**
  - the tree of steps on the left, with ✓ by the done ones;
  - the view in the middle;
  - live cards on the right.
  - The columns fold with the ‹ › buttons or Ctrl/⌘+B and Ctrl/⌘+Alt+B. The state survives a reload, and a narrow
    window starts with the right column folded.
- **Help in small windows:** a card's **?** opens a small window with a description and a link to the guide's
  anchor. ✕, Esc, a click outside or the same **?** close it. Only the top bar's **?** opens the whole guide.
- **Settings as forms:**
  - changing a field replaces only the value in the text of `trainer.yaml`, so comments stay and the diff shows
    one line;
  - a draft, undo/redo, save with a diff and a note, a history of 30 versions, a conflict when two people change it
    at once.
- **Jobs:**
  - a job history with the whole log, and an "Interrupted" state;
  - an interactive loss chart: step tip, full screen, zoom, pinning a step;
  - "Switch the machine off after the job", with a countdown that can be cancelled.
- **Login** with a lock after five wrong passwords.

## Speed {#performance}

- The state is asked for only after the previous answer, at most one question at a time. A tab in the background
  does not ask at all.
- An identical state redraws nothing.
- Every question has a time limit and ends in a clear message: usually 20 s, "Try it" 920 s, "Fetch the router"
  320 s.
- The draft is saved one save at a time. Changes made meanwhile go in one save, and an error does not start a loop
  of retries.
- The test review shows 150 cases at a time. Every view on the demo data stays under 500 ms per task.

## Documentation {#docs}

- **The guide, rewritten in MkDocs Material**, in English and Polish with the same anchors. Chapters:
  - What it is, Installation, The screen, Step by step;
  - Doing it well (a table of every parameter with the code's values), Home Assistant and power;
  - FAQ, this page, Changelog.
- **Pictures** from the demo in both languages (`make screenshots`).
- **An FAQ entry for every known error:** the exact message, the cause and the fix. Every new error goes in, in
  both languages.
- **"Try it on a Mac":** the same short section in both READMEs and on the
  [Installation](installation.md#try-on-a-mac) page.
- **Checks:** the build runs with `--strict`, and tests watch:
  - the button names in the text, which must be real texts of the studio;
  - the anchors, the pictures and the parameter table.
- The guide is also on the shared documentation site of the house, with zero dead links.

## Make commands {#make}

The same names and groups in every app (`make help` in Polish or English):

| Group | Commands | Needs |
|---|---|---|
| 1. Start | `help`, `demo`, `demo-clean`, `docs`, `docs-serve`, `doctor` | only Docker Desktop |
| 2. GPU machine | `install`, `deploy`, `login`, `logs`, `status`, `docker-up/down/logs/shell`, `migrate`, `migrate-finish` | Docker Desktop, ssh, rsync |
| 3. Development | `setup`, `demo-local`, `test`, `test-browser`, `test-docker`, `test-all`, `lint`, `format`, `docs-build`, `screenshots`, `icons`, `clean` | uv (it brings the Python of `PYTHON_VERSION` itself) |
| 4. Without the studio | `fetch`, `router`, `smoke`, `testgen`, `data`, `train`, `resume`, `export`, `evaluate` | on the machine, in the container |

- **One machine address for every app:** `~/.config/gpu-studio/host.mk`. Exceptions go to `Makefile.local`, which
  is not in git.
- **Renamed:** `show-login` → `login`, `studio-demo` → `demo`, `studio-icons` → `icons`, `shell` → `docker-shell`.
  `make studio` is gone, and there are no aliases.
- **`make demo`** builds a small demo image (no CUDA or training libraries, works on arm64 and amd64) and runs it on
  http://localhost:8791 with the login demo/demo. Ctrl+C removes the container.
- **`make docs`, `docs-build` and `docs-serve` run in Docker.** The live preview is at http://localhost:9791.
- **`make doctor`** checks Docker, Chrome, uv, the machine's address and ssh on the Mac, then the card and the
  environment in the container over ssh. It installs nothing.
- **Tests:** `make test` never builds images; `make test-docker` does. `make test-all` = lint, test, test-browser
  and test-docker.

## Tests {#tests}

| Stage | Tests |
|---|---|
| Before (panel + SSH) | 96 |
| Studio in Docker, Playwright | 120 |
| The shared standard (Makefile, Docker, top bar, docs) | 149 |
| Help windows and speed | 154–155 |
| Folding columns | 157 |
| "Try it on a Mac", the demo in Docker | 162–166 |
| The shared make commands | 197 |

- **Tests connect to nothing but 127.0.0.1.** The block works at the socket level, so it covers aiohttp and
  WebSocket too.
- **Switching the machine off is harmless in tests:** a stand-in replaces the real switch.
- **Playwright** checks:
  - the top bar, the countdown and cancelling it, starting a job and its progress, the chart, the job history;
  - the help windows, folding columns and one draft save at a time;
  - the time limits and 500 ms per task of the page.
- **The Docker test** builds the demo image, logs in, checks the guide and that no container is left after
  stopping. Another test builds the guide in Docker.

## What is left {#left}

- **Checking on the GPU machine:**
  - installing it and migrating the old workspace;
  - a run of the whole road (`smoke`) and starting after a restart;
  - whether Unsloth accepts `torch==2.14.1`.
- **Updating Assist Router in Home Assistant to 0.1.8** (released on 17 November 2026, it has the export command).
  With an older version "Fetch from Home Assistant" ends in an error described in the [FAQ](faq.md).
- **Smaller points of the standard:**
  - Stop writes `stop_requested` into the job state;
  - pictures without paths, addresses or names;
  - the old "How to train?" window goes in version 0.2.0.
