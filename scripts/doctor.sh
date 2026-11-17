#!/usr/bin/env bash
# `make doctor`: what this computer and the GPU machine have, for every make target. Only checks, installs
# nothing and needs no Python environment (gpu-studio.md section 2).
#   GPU_HOST=user@machine GPU_DIR=folder UI_PORT=8790 ./scripts/doctor.sh
set -uo pipefail
cd "$(dirname "$0")/.."
GPU_DIR="${GPU_DIR:-home-assistant-assist-router-trainer}"
UI_PORT="${UI_PORT:-8790}"
COMPOSE="docker compose -f docker/compose.yaml"
missing=0
ok() { printf '  OK    %s\n' "$1"; }
no() { printf '  --    %s\n        %s\n' "$1" "$2"; }

echo "This computer | Ten komputer"
if ! command -v docker >/dev/null 2>&1; then
  no "Docker" "install and start Docker Desktop (https://www.docker.com/products/docker-desktop/) | zainstaluj i uruchom Docker Desktop"
  missing=1
elif ! docker info >/dev/null 2>&1; then
  no "Docker" "Docker is not running: start Docker Desktop | Docker nie działa: uruchom Docker Desktop"
  missing=1
else
  ok "Docker $(docker version --format '{{.Server.Version}}' 2>/dev/null) - make demo, make docs, make docs-serve"
fi
if [ -d "/Applications/Google Chrome.app" ] || command -v google-chrome >/dev/null 2>&1; then
  ok "Google Chrome - make test-browser, make screenshots"
else
  no "Google Chrome (only make test-browser, make screenshots)" "https://www.google.com/chrome/ | tylko do testów w przeglądarce i zrzutów"
fi
if command -v uv >/dev/null 2>&1 || [ -x "$HOME/.local/bin/uv" ]; then
  ok "uv - make setup, make test (development)"
else
  no "uv (only development: make setup, make test)" "curl -LsSf https://astral.sh/uv/install.sh | sh   (or: brew install uv) | tylko do pracy nad kodem"
fi

echo
echo "GPU machine | Maszyna z GPU"
if [ -z "${GPU_HOST:-}" ]; then
  no "GPU_HOST" "put GPU_HOST = user@machine in ~/.config/gpu-studio/host.mk | zapisz GPU_HOST w ~/.config/gpu-studio/host.mk"
  if $COMPOSE ps -q studio 2>/dev/null | grep -q .; then
    echo; echo "The studio's container here | Kontener studia tutaj"
    run_here=1
  else
    exit "$missing"
  fi
elif ! ssh -o BatchMode=yes -o ConnectTimeout=3 "$GPU_HOST" true 2>/dev/null; then
  no "ssh $GPU_HOST" "the machine is off or ssh needs a key (ssh-copy-id $GPU_HOST) | maszyna wyłączona albo ssh bez klucza"
  exit "$missing"
else
  ok "ssh $GPU_HOST"
  run_here=0
fi

# the studio's container: GPU, Unsloth, the trainer's Ollama (the old `make doctor` on the machine)
checks="curl -fsS -m 3 http://127.0.0.1:$UI_PORT/api/health >/dev/null && echo '  OK    studio answers on port $UI_PORT' || echo '  --    studio does not answer: make deploy / make logs';
$COMPOSE exec -T studio nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader | sed 's/^/  OK    GPU: /';
$COMPOSE exec -T studio /opt/venv-train/bin/python -c \"import torch, unsloth; print('  OK    torch', torch.__version__, 'cuda', torch.cuda.is_available())\" 2>/dev/null || echo '  --    torch/unsloth in the container';
$COMPOSE exec -T studio /opt/tools/ollama/bin/ollama --version 2>/dev/null | sed 's/^/  OK    /'"
if [ "$run_here" = 1 ]; then
  bash -c "$checks"
else
  ssh -o BatchMode=yes -o ConnectTimeout=3 "$GPU_HOST" \
    "cd $GPU_DIR 2>/dev/null || { echo '  --    no ~/$GPU_DIR on the machine: make install'; exit 0; }; $checks"
fi
exit "$missing"
