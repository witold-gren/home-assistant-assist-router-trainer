# Assist Router trainer studio: the editor and everything training needs, for Ubuntu with an NVIDIA GPU.
#
#   docker compose -f docker/compose.yaml up -d --build      (docker/install-ubuntu.sh does it all)
#
# Layers, from the slowest to the quickest to rebuild (~/Home Assistant/standards/gpu-studio.md, section 3):
#   docs  the guide (MkDocs, its own stage: mkdocs build --strict -> /app/site), served by the studio at /docs/
#   1. system packages, the user, uv
#   2. the environments (scripts/setup.sh --deps-only): Home Assistant + the router's test
#      requirements (/opt/venv), Unsloth with torch pinned for the driver (/opt/venv-train), the trainer's
#      Ollama and llama.cpp
#   3. the trainer's code (a code change rebuilds only this)
# Every stage ends with an import self-test.

# --- the guide (the studio's "?" opens it at /docs/, also without the internet) ---------------------
FROM python:3.12-slim-bookworm AS docs
ENV NO_MKDOCS_2_WARNING=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY requirements_docs.txt ./
RUN pip install --no-cache-dir -q -r requirements_docs.txt
COPY mkdocs.yml CHANGELOG.md ./
COPY dev/docs_site.py dev/docs_site.py
COPY docs docs
RUN NO_MKDOCS_2_WARNING=1 mkdocs build --strict --quiet --site-dir /site \
    && test -f /site/index.html && test -f /site/pl/index.html
# `make docs-serve` runs this stage with docs/, mkdocs.yml and CHANGELOG.md mounted (live reload)
EXPOSE 9791
CMD ["mkdocs", "serve", "--dev-addr", "0.0.0.0:9791"]

# --- only the built guide: `make docs-build` = docker build --target docs-site --output type=local,dest=site
FROM scratch AS docs-site
COPY --from=docs /site /

# --- the Assist Router code for the demo (its custom_components): the public tag; `make demo` replaces this
#     stage with the repository next to this one when it is there
#     (docker build --build-context router=../home-assistant-assist-router/custom_components - that folder,
#     not the repository, whose own .dockerignore keeps only its editor demo)
FROM alpine:3.20 AS router-git
ARG ROUTER_REF=v0.1.7
RUN apk add --no-cache git \
    && git clone -q --depth 1 --branch "$ROUTER_REF" \
        https://github.com/witold-gren/home-assistant-assist-router.git /src
FROM scratch AS router
COPY --from=router-git /src/custom_components/ /

# --- the demo (`make demo`, gpu-studio.md section 8b): the studio on a made-up home with a pretend GPU and
#     Home Assistant, login demo/demo. No CUDA and no training libraries: builds on arm64 (a Mac) and amd64.
FROM python:3.13-slim-bookworm AS demo
ENV PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN pip install --no-cache-dir -q "pyyaml>=6" "aiohttp>=3.9" "hassil>=3" home-assistant-intents \
    && useradd -m -u 1000 demo
# where the trainer looks for the router next to itself (router_source.SIBLING)
COPY --from=router / /home-assistant-assist-router/custom_components
WORKDIR /app
COPY pyproject.toml README.md ./
COPY router_trainer router_trainer
COPY scripts scripts
COPY --from=docs /site /app/site
RUN pip install --no-cache-dir -q --no-deps -e /app \
    # self-test: the studio, the made-up home and the guide are where the demo looks for them
    && python -c "import sys; sys.path[:0] = ['scripts']; import studio_demo, router_trainer.studio.server as s; assert (s.DOCS / 'pl' / 'index.html').is_file()"
USER demo
EXPOSE 8791
CMD ["python", "scripts/studio_demo.py", "--host", "0.0.0.0", "--port", "8791"]

# --- the studio ---------------------------------------------------------------------------------------
FROM ubuntu:24.04

ARG UID=1000
ARG GID=1000
# the Assist Router code baked in (the studio fetches the version Home Assistant runs anyway)
ARG ROUTER_REF=v0.1.7
ARG OLLAMA_VERSION=0.34.1
ARG UNSLOTH_SPEC=unsloth
# the torch that runs on the machine (driver 580 = CUDA 13.0); unpinned, pip takes a newer CUDA that does not
ARG TORCH_SPEC="torch==2.14.1"
ARG LLAMA_CPP_REF=

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    HOME=/home/trainer \
    PATH=/home/trainer/.local/bin:/opt/venv/bin:$PATH \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/tmp/uv-cache \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility

# Ubuntu 24.04 has a user 1000 (ubuntu): it goes, so the trainer's user gets the machine's UID
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git zstd build-essential procps tini rsync \
    && rm -rf /var/lib/apt/lists/* \
    && (userdel -r ubuntu 2>/dev/null || true) \
    && groupadd -g "$GID" trainer && useradd -m -u "$UID" -g "$GID" -s /bin/bash trainer \
    && mkdir -p /opt/python /opt/venv /opt/venv-train /opt/tools /opt/assist-router /app /data \
    && chown -R trainer:trainer /opt /app /data

USER trainer
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. environments - depend only on the router's requirements and setup.sh
WORKDIR /app
RUN git clone -q --depth 1 --branch "$ROUTER_REF" \
        https://github.com/witold-gren/home-assistant-assist-router.git /opt/assist-router \
    && cp /opt/assist-router/requirements_test.txt /opt/router-requirements.txt
COPY --chown=trainer:trainer scripts/setup.sh scripts/setup.sh
RUN ROUTER_REPO=/opt/assist-router VENV_DIR=/opt/venv TRAIN_VENV_DIR=/opt/venv-train \
    TOOLS_DIR=/opt/tools ENV_FILE=/opt/environment.txt OLLAMA_VERSION="$OLLAMA_VERSION" \
    UNSLOTH_SPEC="$UNSLOTH_SPEC" TORCH_SPEC="$TORCH_SPEC" LLAMA_CPP_REF="$LLAMA_CPP_REF" \
    ./scripts/setup.sh --deps-only \
    && rm -rf /tmp/uv-cache \
    # self-test: both environments import (Unsloth itself needs a GPU - make doctor checks it on the machine)
    && /opt/venv/bin/python -c "import homeassistant, hassil, yaml, aiohttp" \
    && /opt/venv-train/bin/python -c "import torch, transformers, peft, trl, gguf; print('torch', torch.__version__)" \
    && /opt/tools/ollama/bin/ollama --version

# 3. the trainer's code, installed in place (docs/ and the studio are found next to it)
COPY --chown=trainer:trainer . /app
COPY --from=docs --chown=trainer:trainer /site /app/site
RUN uv pip install --python /opt/venv/bin/python --no-deps -e /app \
    && uv pip install --python /opt/venv-train/bin/python --no-deps -e /app \
    && rm -rf /tmp/uv-cache \
    # self-test: the studio, the CLI and the guide are where the server looks for them
    && /opt/venv/bin/python -c "import router_trainer.cli, router_trainer.studio.server as s; assert (s.DOCS / 'pl' / 'index.html').is_file(), s.DOCS" 

ENV ROUTER_TRAINER_WORKSPACE=/data/workspace \
    ROUTER_TRAINER_TOOLS=/opt/tools \
    ROUTER_TRAINER_TRAIN_PYTHON=/opt/venv-train/bin/python \
    ROUTER_TRAINER_IMAGE_REQUIREMENTS=/opt/router-requirements.txt \
    ROUTER_TRAINER_IN_CONTAINER=1 \
    HF_HOME=/data/huggingface

EXPOSE 8790
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8790/api/health', timeout=4)"
ENTRYPOINT ["/usr/bin/tini", "--", "/app/docker/entrypoint.sh"]
CMD ["router-trainer", "studio", "--host", "0.0.0.0", "--port", "8790"]
