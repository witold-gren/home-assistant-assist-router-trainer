# FAQ: errors and fixes {#faq}

Every known error of the studio and the commands: the exact message (or symptom), the cause and the fix.
A new error that is not here? Add it to this page (PL and EN) with its fix.

## Installation and Docker {#faq-docker}

| Message / symptom | Cause and fix |
|---|---|
| "error: Docker is missing", "the Docker Compose plugin is missing" | Install Docker from Docker's repository and `docker-compose-plugin` ([Installation](installation.md#install-machine)). |
| "error: this user cannot use Docker" | `sudo usermod -aG docker $(id -un)`, then log out and in. |
| "error: the NVIDIA driver is missing" | `sudo ubuntu-drivers install` and a reboot. |
| "error: nvidia-smi does not see the card" | The driver is installed but not loaded: reboot; after a kernel update a reboot is often enough. |
| "error: NVIDIA driver … is too old for the image's CUDA 13.0" | The image's PyTorch needs driver 580 or newer: `sudo ubuntu-drivers install` (or `sudo apt install nvidia-driver-580`) and a reboot. |
| "error: the NVIDIA Container Toolkit is missing" | Install `nvidia-container-toolkit`, then `sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker`. |
| "warning: the container does not see the GPU" | The toolkit is not set up for Docker or the driver is older than the image's PyTorch needs (driver 580 / CUDA 13.0). `docker run --rm --gpus all ubuntu nvidia-smi` must show the card; `make doctor` (from the Mac, through ssh) checks the container. |
| The page does not open after switching the machine on | Docker does not start with the system (`sudo systemctl enable --now docker`) or the container failed: `make logs` from the Mac. |
| "error: ROUTER_TRAINER_UI_AUTH must be user:password" | A missing or wrong line in `docker/config/env`; run `make install` (writes a new login). |
| "error: STUDIO_TRUSTED_NETWORKS: 'home' is not a network like 192.168.1.0/24" | The line in `docker/config/env` needs networks such as `192.168.1.0/24`, comma-separated: `make install STUDIO_TRUSTED_NETWORKS=192.168.1.0/24`. |
| The login page still opens on the home network | The network is not in `STUDIO_TRUSTED_NETWORKS`, or the connection comes through another address (on the machine itself `localhost` is Docker's gateway, so the login stays there). See [No login on the home network](installation.md#trusted-networks). |
| Login: "Too many attempts" | Five wrong passwords from one address - wait a minute. The password: `make login`. |
| "Docker is not installed: install and start Docker Desktop" / "Docker is not running: start Docker Desktop" (`make demo`, `make docs`, `make docs-serve`, `make docs-build`, `make doctor`) | Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and start it (the whale in the menu bar must say it is running), then the same command again. Nothing else is needed for these commands. |
| "uv is not installed (development only): curl -LsSf https://astral.sh/uv/install.sh \| sh" (`make setup`, `make test`) | Only for working on the code. Run the command from the message (or `brew install uv`); uv brings the Python of `PYTHON_VERSION` itself. |
| `make doctor`: "-- ssh user@machine: the machine is off or ssh needs a key" | The machine is off (switch it on in Home Assistant) or ssh asks for a password: `ssh-copy-id user@machine` once. `make doctor` only checks; it never installs anything. |
| `make docs-serve`: the address shows another page or "address already in use" | Port 9791 is taken by another program: `make docs-serve DOCS_PORT=9792`. |
| "GPU_HOST is not set" | The Mac does not know the machine: `GPU_HOST=user@machine` in `~/.config/gpu-studio/host.mk` (shared by all studios) or `Makefile.local`. |
| "'…' is still running" / "fetching from Home Assistant is still running" | Another job is running; wait or press <span class="ui">Stop</span>. |
| After a container restart the job says "Interrupted" | A restart (update, `make deploy`) stops the job. Resume training from its checkpoint (<span class="ui">Resume</span>); generating starts where it ended. |
| "The studio did not answer within … s - check the machine (make status) and try again." / "The studio cannot be reached - is the machine on?" | The machine is off or busy, or the container is restarting. `make status` from the Mac; the page asks again by itself and the message goes once the studio answers. |
| The tour does not show when the studio opens | It shows once per browser; after Skip, Esc or Done it is remembered. ⚙ → <span class="ui">Tour of the studio</span> shows it again. In private browsing the browser cannot remember it, so it does not start by itself there. |
| A lesson frames nothing, only the screen is dimmed | Its part is not on the screen yet (a result before the first automatic training, the export before a trained model): the lesson frames the nearest part instead; <span class="ui">Next</span> goes on. |

## Home Assistant and the router code {#faq-ha}

| Message / symptom | Cause and fix |
|---|---|
| "Assist Router in Home Assistant is too old for the trainer - update it to 0.1.8 or newer" | The export command is in Assist Router 0.1.8 and newer. Update the integration through HACS and restart HA. |
| "Home Assistant refused the export: the token's user must be an administrator" | The token belongs to an ordinary user. Make a token on an administrator account. |
| "Home Assistant rejected the token", "HA token rejected" in the top bar | A wrong, expired or deleted token. Every refusal is a failed login for HA (`ip_ban`), so the studio stops asking HA until <span class="ui">Connect to HA</span> with a new token. |
| "Home Assistant 403: refused - this computer's address may be banned …" | HA banned the address after failed logins: remove the entry from `/config/ip_bans.yaml` and restart HA. |
| "Home Assistant at … cannot be reached" | A wrong address or HA is restarting. Give the full address with the port, e.g. `http://192.168.1.10:8123`. |
| Red pill "Router 0.1.7 ≠ HA 0.1.8" | The studio has other router code than HA: **Router code** → <span class="ui">Fetch router {version}</span>. |
| "git clone v…: Remote branch … not found" | That version is not a tag on GitHub (a local, unreleased version). Release it or point `router_repo` at a folder with the code. |
| "This router version needs other Python packages than the image has" | The router's requirements changed: set `ROUTER_REF=v…` in `docker/.env` and `make deploy`. |
| "…/router.yaml missing" | <span class="ui">Fetch from Home Assistant</span> first. |
| "No test yet", "no generated test '…'" | Create a test or choose another active one. |

## Test and training data {#faq-data}

| Message / symptom | Cause and fix |
|---|---|
| "… missing - freeze the test first" | In **Generate** tick freezing the test. Needed after every change of the active test or the review. |
| "dataset … missing - build it first" | Generate with building the dataset, then the same name in **Start training**. |
| "router.yaml or the home changed since this dataset was built" | The integration's prompts changed. Build the dataset again. |
| "the trainer's Ollama did not start (…)" | See the named log; usually port 11535 is taken - change `ollama.local_port`. |
| A model (e.g. Bielik) does not download from Hugging Face: "bad record MAC", TLS error | Download the GGUF in a browser and upload it through the Ollama API (`/api/blobs`, then `/api/create`). In zsh write `${repo}:Q4_K_M`, not `$repo:Q4_K_M`. |
| Few test cases, many "dropped automatically" | "models disagree" is the normal filtering. When almost everything goes, raise the numbers in `test:` or check the judge (Gemma 26B). |
| Many rejected control commands | `generated/control_rejected.jsonl`; device aliases in HA help. |
| "… lower-case letters, digits, . _ - (up to 41 chars)" | The name of a dataset, test or run: lower-case letters, digits and `. _ -`. |
| Saving the settings: "dataset.dev_fraction: between 0 and 0.5", "models.e4b.epochs: a number" | A value out of range or not a number - correct the field; the draft stays. |
| Saving: "trainer.yaml was changed elsewhere since this draft was begun" | The file changed elsewhere (e.g. in a terminal). <span class="ui">Save anyway</span> overwrites it - the previous version stays in the <span class="ui">History</span>. |

## Training and export {#faq-train}

| Message / symptom | Cause and fix |
|---|---|
| "only … of … GB free on the GPU …" | Another process holds the card (`nvidia-smi` on the machine), e.g. another container with a model. Stop it. |
| "no CUDA GPU - training needs an NVIDIA card" | The container does not see the card - see [Installation and Docker](#faq-docker). |
| "CUDA out of memory" | Lower `batch_size` (raise `grad_accum`) or `max_seq_length`. |
| The overfitting warning | The dev loss rises - stop; fewer epochs or a lower learning rate ([Reading the chart](good-practice.md#chart)). |
| "chat template turn markers not found" | The base model has another chat template than Gemma 4; use the models of `models:`. |
| "…/merged missing - train the model first" | Exporting a run without a finished training. |
| "nothing left to train" when resuming | The run already reached its last step: start a new run with more epochs ([Resuming](good-practice.md#resume)). |
| The disk fills up | `du -sh docker/data/workspace/*`; old runs are in `runs/`, the smoke test's copy in `workspace-smoke`. |
| The machine did not switch off after the job | Not after <span class="ui">Stop</span>, not after a container restart; an error (no token, switch unavailable) shows in the top bar ([Switching off after the job](home-assistant.md#power-off-after)). |

## Evaluation {#faq-eval}

| Message / symptom | Cause and fix |
|---|---|
| The test stops with "Connection reset" | Not enough memory on the Jetson: add big models to `evaluate.unload_first` and run the evaluation again (it appends results). |
| Results differ from the router's model comparison | Another test - compare only on the same active test. |
| Great dev loss, weak test | The model learnt the templates - [Recipes](good-practice.md#recipes). |
