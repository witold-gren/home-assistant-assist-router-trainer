# home-assistant-assist-router-trainer - a smaller model for Assist Router, trained on your home.
#
#   make help        the steps in order (Polish or English, from $LANG; HELP_LANG=en|pl)
#   make install     from the Mac: first install on the GPU machine (GPU_HOST)
#   make deploy      from the Mac: every update - this repository to GPU_HOST and the studio rebuilt there
#
# The studio starts with the machine (Docker restart: unless-stopped). On the Mac, group 1 (make demo, make docs)
# needs only Docker Desktop; group 3 (development) needs uv, which brings Python $(PYTHON_VERSION) itself.

# the GPU machine with the studio in Docker, shared by every studio (~/Home Assistant/standards/gpu-studio.md):
# ~/.config/gpu-studio/host.mk with GPU_HOST = user@192.168.1.21; this repository's exceptions go to
# Makefile.local (not in git)
-include $(HOME)/.config/gpu-studio/host.mk
-include Makefile.local
GPU_DIR ?= home-assistant-assist-router-trainer
UI_PORT ?= 8790
DEMO_PORT ?= 8791
DOCS_PORT ?= 9791
# the Python of .venv: the one Home Assistant of the router's test requirements needs (HA 2026.2: 3.13)
PYTHON_VERSION ?= 3.13
NEED_HOST = @test -n "$(GPU_HOST)" || { echo "GPU_HOST is not set: put GPU_HOST = user@machine in ~/.config/gpu-studio/host.mk (or make <target> GPU_HOST=…)"; exit 1; }
# a folder for the studio's data on that machine (empty: docker/data next to the repository)
STUDIO_DATA ?=
RSYNC_CODE := rsync -az --delete --exclude .git --exclude '.venv*' --exclude __pycache__ --exclude .pytest_cache \
  --exclude .ruff_cache --exclude backup --exclude 'workspace*' --exclude tools --exclude site \
  --exclude docker/data --exclude docker/config --exclude docker/.env --exclude Makefile.local

NAME ?=
DATASET ?=
MODEL ?= e4b
MODELS ?= e4b e2b
RUN ?=
FROM ?= $(HOME)/assist-router-trainer/trainer/workspace

VENV := .venv
DEMO_IMAGE ?= router-trainer-demo
DOCS_IMAGE ?= router-trainer-docs
# the Assist Router repository next to this one goes into the demo image when it is there (else its tag from GitHub)
ROUTER_NEXT := $(wildcard ../home-assistant-assist-router/custom_components)
DOCKER_READY = command -v docker >/dev/null 2>&1 || { echo "Docker is not installed: install and start Docker Desktop (https://www.docker.com/products/docker-desktop/) | Brak Dockera: zainstaluj i uruchom Docker Desktop"; exit 1; }; \
  docker info >/dev/null 2>&1 || { echo "Docker is not running: start Docker Desktop | Docker nie działa: uruchom Docker Desktop"; exit 1; }
UV := $(shell command -v uv 2>/dev/null || { test -x $(HOME)/.local/bin/uv && echo $(HOME)/.local/bin/uv; })
NEED_UV = @test -n "$(UV)" || { echo "uv is not installed (development only): curl -LsSf https://astral.sh/uv/install.sh | sh  (or brew install uv) | Brak uv (tylko do pracy nad kodem): curl -LsSf https://astral.sh/uv/install.sh | sh  (albo brew install uv)"; exit 1; }
COMPOSE := docker compose -f docker/compose.yaml
IN := $(COMPOSE) exec studio router-trainer
HELP_LANG ?= $(if $(filter pl%,$(LANG)),pl,en)
DATA_STEPS := snapshot freeze router control answers build
BROWSER_TESTS := tests/test_studio_browser.py

.DEFAULT_GOAL := help
.PHONY: help demo demo-clean docs docs-serve doctor \
        install deploy login logs status docker-up docker-down docker-logs docker-shell migrate migrate-finish \
        setup demo-local test test-browser test-docker test-all lint format docs-build screenshots icons clean \
        fetch router smoke testgen data train resume export evaluate

##@ 1. Start (only Docker Desktop) | 1. Start (wystarczy Docker Desktop)

help: ## This list | Ta lista
	@awk -v lang=$(HELP_LANG) 'BEGIN { FS = ":.*## " } \
	  /^##@ / { split(substr($$0, 5), t, " \\| "); printf "\n\033[1m%s\033[0m\n", (lang == "pl" && t[2] != "") ? t[2] : t[1]; next } \
	  /^[a-zA-Z0-9_-]+:.*## / { split($$2, d, " \\| "); printf "  \033[36m%-15s\033[0m %s\n", $$1, (lang == "pl" && d[2] != "") ? d[2] : d[1] }' \
	  $(MAKEFILE_LIST)
	@echo
	@if [ "$(HELP_LANG)" = "pl" ]; then \
	  echo "Maszyna: GPU_HOST=$(if $(GPU_HOST),$(GPU_HOST),(brak - ~/.config/gpu-studio/host.mk))"; \
	  echo "Z Maca: make install, potem wszystko w studiu (przycisk ?), login: make login."; \
	else \
	  echo "Machine: GPU_HOST=$(if $(GPU_HOST),$(GPU_HOST),(none - ~/.config/gpu-studio/host.mk))"; \
	  echo "From the Mac: make install - then everything in the studio (? button), login: make login."; \
	fi

demo: ## Try it: the studio on a made-up home in Docker, only Docker Desktop needed (http://localhost:8791, demo/demo) | Wypróbuj: studio na wymyślonym domu w Dockerze, wystarczy Docker Desktop (http://localhost:8791, demo/demo)
	@$(DOCKER_READY)
	docker build -f docker/Dockerfile --target demo $(if $(ROUTER_NEXT),--build-context router=$(ROUTER_NEXT)) -t $(DEMO_IMAGE) .
	docker run --rm --init $(if $(shell test -t 0 && echo tty),-it,-i) -p 127.0.0.1:$(DEMO_PORT):$(DEMO_PORT) \
	  -e DEMO_URL=http://localhost:$(DEMO_PORT)/ $(DEMO_IMAGE) python scripts/studio_demo.py --host 0.0.0.0 --port $(DEMO_PORT)

demo-clean: ## Remove the demo image (make demo builds it again) | Usuń obraz demo (make demo zbuduje go od nowa)
	@$(DOCKER_READY)
	-docker image rm $(DEMO_IMAGE)

docs: docs-build ## Build the guide in Docker and open it | Zbuduj przewodnik w Dockerze i go otwórz
	@open site/$(if $(filter pl,$(HELP_LANG)),pl/,)index.html 2>/dev/null || xdg-open site/$(if $(filter pl,$(HELP_LANG)),pl/,)index.html

docs-serve: ## The guide with live reload, in Docker (http://localhost:9791) | Przewodnik z odświeżaniem na żywo, w Dockerze (http://localhost:9791)
	@$(DOCKER_READY)
	docker build -f docker/Dockerfile --target docs -t $(DOCS_IMAGE) .
	docker run --rm --init $(if $(shell test -t 0 && echo tty),-it,-i) -p 127.0.0.1:$(DOCS_PORT):9791 \
	  -e SITE_URL=http://127.0.0.1:$(DOCS_PORT)/ -v "$(CURDIR)/docs:/src/docs" -v "$(CURDIR)/mkdocs.yml:/src/mkdocs.yml:ro" -v "$(CURDIR)/CHANGELOG.md:/src/CHANGELOG.md:ro" \
	  $(DOCS_IMAGE)

doctor: ## Check this computer and the GPU machine (Docker, Chrome, uv, GPU_HOST, ssh, GPU in the container); installs nothing | Sprawdź ten komputer i maszynę z GPU (Docker, Chrome, uv, GPU_HOST, ssh, GPU w kontenerze); nic nie instaluje
	@GPU_HOST="$(GPU_HOST)" GPU_DIR="$(GPU_DIR)" UI_PORT="$(UI_PORT)" ./scripts/doctor.sh

##@ 2. GPU machine (from the Mac: GPU_HOST; docker-* and migrate* on the machine) | 2. Maszyna z GPU (z Maca: GPU_HOST; docker-* i migrate* na maszynie)

install: ## First install on GPU_HOST: code, checks, login, autostart, build, start (STUDIO_DATA=folder) | Pierwsza instalacja na GPU_HOST: kod, sprawdzenie, login, autostart, budowa, start (STUDIO_DATA=folder)
	$(NEED_HOST)
	$(RSYNC_CODE) ./ $(GPU_HOST):$(GPU_DIR)/
	ssh -t $(GPU_HOST) 'cd $(GPU_DIR) && $(if $(STUDIO_DATA),STUDIO_DATA=$(STUDIO_DATA) )./docker/install-ubuntu.sh'

deploy: ## Every update: send this repository to GPU_HOST and rebuild the studio there | Każda aktualizacja: wyślij repozytorium na GPU_HOST i przebuduj tam studio
	$(NEED_HOST)
	$(RSYNC_CODE) ./ $(GPU_HOST):$(GPU_DIR)/
	ssh $(GPU_HOST) 'cd $(GPU_DIR) && { test -f docker/config/env || { echo "first time: make install"; exit 1; }; } && $(COMPOSE) up -d --build'

login: ## The studio's user and password (kept on GPU_HOST in docker/config/env) | Użytkownik i hasło studia (zapisane na GPU_HOST w docker/config/env)
	$(NEED_HOST)
	ssh $(GPU_HOST) 'cd $(GPU_DIR) && ./docker/install-ubuntu.sh --show-login'

logs: ## The studio's log on GPU_HOST (Ctrl+C ends) | Dziennik studia na GPU_HOST (Ctrl+C kończy)
	$(NEED_HOST)
	ssh -t $(GPU_HOST) 'cd $(GPU_DIR) && $(COMPOSE) logs -f --tail 200'

status: ## Does the studio answer: health, version, the card in the container | Czy studio odpowiada: stan, wersja, karta w kontenerze
	$(NEED_HOST)
	ssh $(GPU_HOST) 'cd $(GPU_DIR) && curl -fsS http://127.0.0.1:$(UI_PORT)/api/health; echo; $(COMPOSE) ps --format "{{.Service}} {{.State}} {{.Status}}"; $(COMPOSE) exec -T studio nvidia-smi --query-gpu=name,driver_version,memory.used,memory.total,temperature.gpu --format=csv,noheader'

docker-up: ## Build and start the studio (first time: docker/install-ubuntu.sh) | Zbuduj i uruchom studio (za pierwszym razem: docker/install-ubuntu.sh)
	$(COMPOSE) up -d --build

docker-down: ## Stop the studio (a running job stops too; data stays) | Zatrzymaj studio (trwające zadanie też; dane zostają)
	$(COMPOSE) down

docker-logs: ## The studio's log (Ctrl+C ends) | Dziennik studia (Ctrl+C kończy)
	$(COMPOSE) logs -f --tail 200

docker-shell: ## A shell in the studio's container | Powłoka w kontenerze studia
	$(COMPOSE) exec studio bash

migrate: ## Copy the old workspace into docker/data/ (FROM=…) | Skopiuj stary workspace do docker/data/ (FROM=…)
	@./docker/migrate.sh "$(FROM)"

migrate-finish: ## Switch the old panel service off (after checking the new one) | Wyłącz starą usługę panelu (po sprawdzeniu nowego)
	-systemctl --user disable --now router-trainer.service
	@echo "Old service switched off; its unit and settings stay in ~/.config (delete them by hand)."

##@ 3. Development (uv brings Python itself: PYTHON_VERSION) | 3. Rozwój (uv sam pobiera Pythona: PYTHON_VERSION)

$(VENV)/bin/router-trainer:
	$(NEED_UV)
	@echo "==> Python $(PYTHON_VERSION) environment in $(VENV)"
	@PATH="$(dir $(UV)):$$PATH" PYTHON_VERSION=$(PYTHON_VERSION) ./scripts/setup.sh --app-only
	@touch $@

# mkdocs in .venv: the tests build the guide strictly without Docker (make test never builds images)
$(VENV)/bin/mkdocs: requirements_docs.txt | $(VENV)/bin/router-trainer
	@"$(UV)" pip install --python $(VENV)/bin/python -q -r requirements_docs.txt
	@touch $@

# the guide for the studio's /docs/ in the tests, built with that mkdocs
site/pl/index.html: $(VENV)/bin/mkdocs mkdocs.yml CHANGELOG.md dev/docs_site.py $(filter-out docs/changelog%,$(wildcard docs/*.md))
	@$(VENV)/bin/mkdocs build --strict --quiet

setup: $(VENV)/bin/router-trainer $(VENV)/bin/mkdocs ## Python environment through uv (.venv, PYTHON_VERSION) for the tests, demo-local and screenshots | Środowisko Pythona przez uv (.venv, PYTHON_VERSION) do testów, demo-local i zrzutów

demo-local: setup ## The demo without Docker, from .venv (as test-browser and screenshots use it) | Demo bez Dockera, z .venv (tak jak używają go test-browser i screenshots)
	$(VENV)/bin/python scripts/studio_demo.py --port $(DEMO_PORT)

test: setup site/pl/index.html ## Tests without a browser and without building images (no GPU, Ollama or Home Assistant) | Testy bez przeglądarki i bez budowy obrazów (bez GPU, Ollamy i Home Assistanta)
	$(VENV)/bin/python -m pytest -q -m "not docker" --ignore=$(BROWSER_TESTS)

test-browser: setup site/pl/index.html ## The studio in Google Chrome (Playwright, on the demo) | Studio w Google Chrome (Playwright, na demo)
	$(VENV)/bin/python -m pytest -q -m "not docker" $(BROWSER_TESTS)

test-docker: setup ## Tests that build images: the demo image (HTTP, login, no container left) and the guide in Docker | Testy, które budują obrazy: obraz demo (HTTP, login, po zatrzymaniu bez kontenera) i przewodnik w Dockerze
	@$(DOCKER_READY)
	$(VENV)/bin/python -m pytest -q -m docker

test-all: lint test test-browser test-docker ## lint + test + test-browser + test-docker | lint + test + test-browser + test-docker

lint: setup ## Ruff: lint and format check | Ruff: błędy i formatowanie
	$(VENV)/bin/ruff check . && $(VENV)/bin/ruff format --check .

format: setup ## Ruff: fix what it can and format the code | Ruff: popraw, co się da, i sformatuj kod
	$(VENV)/bin/ruff check --fix . && $(VENV)/bin/ruff format .

docs-build: ## Build the guide into site/ in Docker (as the image and the documentation site do) | Zbuduj przewodnik do site/ w Dockerze (tak jak obraz i strona dokumentacji)
	@$(DOCKER_READY)
	rm -rf site
	docker build -f docker/Dockerfile --target docs-site --output type=local,dest=site .
	@chmod -R u+rwX,go+rX site  # --output makes site/ 700: the web server of docs-hub must read it
	@test -f site/index.html && test -f site/pl/index.html

screenshots: setup ## Studio screenshots for the guide, both languages (made-up home, Google Chrome) | Zrzuty studia do przewodnika, oba języki (wymyślony dom, Google Chrome)
	$(VENV)/bin/python scripts/studio_demo.py --shots

icons: setup ## Icons of the studio again, after adding an mdi: icon (MDI=path/to/@mdi/js/mdi.js) | Ikony studia od nowa po dodaniu ikony mdi: (MDI=ścieżka do @mdi/js/mdi.js)
	@test -n "$(MDI)" || { echo "usage: make icons MDI=path/to/mdi.js (npm @mdi/js 7.4.47)"; exit 1; }
	$(VENV)/bin/python -m router_trainer.studio.make_icons "$(MDI)"

clean: ## Remove .venv, the built guide and caches (the workspace and docker/data stay) | Usuń .venv, zbudowany przewodnik i pamięć podręczną (workspace i docker/data zostają)
	find . -name __pycache__ -type d -prune -not -path "./.venv*" -not -path "./docker/data/*" -exec rm -r {} +
	rm -rf .venv .pytest_cache .ruff_cache site

##@ 4. Without the studio (in the container, on the machine) | 4. Bez studia (w kontenerze, na maszynie)

fetch: ## Inputs from Home Assistant (Assist Router export) | Pliki z Home Assistanta (eksport Assist Routera)
	$(IN) fetch

router: ## Router code of the version Home Assistant runs | Kod routera w wersji z Home Assistanta
	$(IN) router

smoke: ## Quick check of the whole road on a small copy (MODEL=e2b) | Szybka próba całej drogi na małej kopii (MODEL=e2b)
	$(IN) smoke --model $(if $(filter command line,$(origin MODEL)),$(MODEL),e2b)

testgen: ## New test from the home and the question log (NAME=…) | Nowy test z domu i dziennika pytań (NAME=…)
	@test -n "$(NAME)" || { echo "usage: make testgen NAME=test1"; exit 1; }
	$(IN) testgen --name $(NAME)

data: ## Training data: snapshot, freeze, generate, build (DATASET=…) | Dane treningowe: snapshot, freeze, generowanie, build (DATASET=…)
	@test -n "$(DATASET)" || { echo "usage: make data DATASET=d1"; exit 1; }
	$(IN) pipeline --steps $(DATA_STEPS) --dataset $(DATASET)

train: ## Train, export and evaluate (DATASET=… MODELS="e4b e2b") | Trening, eksport i ocena (DATASET=… MODELS="e4b e2b")
	@test -n "$(DATASET)" || { echo "usage: make train DATASET=d1 [MODELS=e2b]"; exit 1; }
	$(IN) pipeline --steps train export evaluate --dataset $(DATASET) --models $(MODELS)

resume: ## Continue a stopped training from its checkpoint (DATASET=… MODEL=…) | Wznów przerwany trening od punktu kontrolnego (DATASET=… MODEL=…)
	@test -n "$(DATASET)" || { echo "usage: make resume DATASET=d1 MODEL=e4b [RUN=…]"; exit 1; }
	$(IN) train --dataset $(DATASET) --model $(MODEL) $(if $(RUN),--run $(RUN)) --resume

export: ## GGUF and upload to the home Ollama (RUN=…) | GGUF i wysłanie do domowej Ollamy (RUN=…)
	@test -n "$(RUN)" || { echo "usage: make export RUN=d1-e4b"; exit 1; }
	$(IN) export --run $(RUN)

evaluate: ## Test: trained model vs base model (RUN=…) | Test: douczony model kontra bazowy (RUN=…)
	@test -n "$(RUN)" || { echo "usage: make evaluate RUN=d1-e4b"; exit 1; }
	$(IN) evaluate --run $(RUN)

