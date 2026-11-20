#!/usr/bin/env bash
# Environments of the trainer (no sudo). The Docker image runs this script (docker/Dockerfile);
# it also works on a computer for development (`make setup` on the Mac uses --app-only).
#   .venv        Python 3.13 (PYTHON_VERSION) - data, export, test, panel; Home Assistant and the Assist Router
#                integration come from the router repository's test requirements
#   .venv-train  Python 3.12 - Unsloth (training) and llama.cpp's GGUF converter
#   tools/       the trainer's own Ollama (same version as the home one) and llama.cpp
#
#   ./scripts/setup.sh              everything (Linux + NVIDIA)
#   ./scripts/setup.sh --app-only   only .venv (the panel without a GPU, e.g. on a Mac)
#   ./scripts/setup.sh --deps-only  everything except the trainer package itself (image layer;
#                                   the code is installed later with `uv pip install -e . --no-deps`)
#
# ROUTER_REPO=...      the Assist Router repository (default: ../home-assistant-assist-router)
# VENV_DIR=... TRAIN_VENV_DIR=... TOOLS_DIR=...   where the environments and tools go
# OLLAMA_VERSION=... (default 0.34.1)   LLAMA_CPP_REF=... (default: newest)
# UNSLOTH_SPEC=...     pip spec of Unsloth (default: unsloth - newest)
# TORCH_SPEC=...       torch for the machine's driver (default torch==2.14.1: driver 580 = CUDA 13.0;
#                      unpinned, pip takes a newer CUDA that the driver cannot run). TORCH_SPEC= unpins.
# ENV_FILE=...         where the installed versions are written (default workspace/environment.txt)
set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-}"
OLLAMA_VERSION="${OLLAMA_VERSION:-0.34.1}"
LLAMA_CPP_REF="${LLAMA_CPP_REF:-}"
UNSLOTH_SPEC="${UNSLOTH_SPEC:-unsloth}"
TORCH_SPEC="${TORCH_SPEC-torch==2.14.1}"
VENV_DIR="${VENV_DIR:-.venv}"
TRAIN_VENV_DIR="${TRAIN_VENV_DIR:-.venv-train}"
TOOLS_DIR="${TOOLS_DIR:-tools}"
ENV_FILE="${ENV_FILE:-workspace/environment.txt}"
ROUTER_REPO="${ROUTER_REPO:-../home-assistant-assist-router}"
PYTHON_VERSION="${PYTHON_VERSION:-3.13}"  # of .venv: what Home Assistant of the router's test requirements needs
[ -f "$ROUTER_REPO/requirements_test.txt" ] || { echo "Assist Router repository not found: $ROUTER_REPO (set ROUTER_REPO)"; exit 1; }

if ! command -v uv >/dev/null && [ ! -x "$HOME/.local/bin/uv" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

# the trainer's own dependencies (pyproject.toml: pyyaml + extras data, dev)
OWN_DEPS=(pyyaml "hassil>=3" home-assistant-intents "aiohttp>=3.9" "anthropic>=2.10" "pytest>=8" "ruff>=0.6")

echo "==> $VENV_DIR (data, export, test, panel)"
uv venv --python "$PYTHON_VERSION" --allow-existing "$VENV_DIR"
uv pip install --python "$VENV_DIR/bin/python" -r "$ROUTER_REPO/requirements_test.txt"
if [ "$MODE" = "--deps-only" ]; then
  uv pip install --python "$VENV_DIR/bin/python" "${OWN_DEPS[@]}"
else
  uv pip install --python "$VENV_DIR/bin/python" -e ".[data,dev]"
  mkdir -p workspace
  "$VENV_DIR/bin/python" -m router_trainer.cli init
fi

if [ "$MODE" = "--app-only" ]; then
  echo "Done ($VENV_DIR only)."
  exit 0
fi

echo "==> $TRAIN_VENV_DIR (Unsloth)"
uv venv --python 3.12 --allow-existing "$TRAIN_VENV_DIR"
uv pip install --python "$TRAIN_VENV_DIR/bin/python" "$UNSLOTH_SPEC" $TORCH_SPEC pyyaml
if [ "$MODE" != "--deps-only" ]; then
  uv pip install --python "$TRAIN_VENV_DIR/bin/python" -e . --no-deps
fi

echo "==> $TOOLS_DIR/llama.cpp (GGUF converter)"
mkdir -p "$TOOLS_DIR"
if [ ! -d "$TOOLS_DIR/llama.cpp" ]; then
  git clone -q https://github.com/ggml-org/llama.cpp "$TOOLS_DIR/llama.cpp"
fi
if [ -n "$LLAMA_CPP_REF" ]; then
  git -C "$TOOLS_DIR/llama.cpp" fetch -q --tags origin && git -C "$TOOLS_DIR/llama.cpp" checkout -q "$LLAMA_CPP_REF"
fi
uv pip install --python "$TRAIN_VENV_DIR/bin/python" -e "$TOOLS_DIR/llama.cpp/gguf-py" sentencepiece protobuf

echo "==> $TOOLS_DIR/ollama $OLLAMA_VERSION"
if [ ! -x "$TOOLS_DIR/ollama/bin/ollama" ] || ! "$TOOLS_DIR/ollama/bin/ollama" --version 2>/dev/null | grep -q "$OLLAMA_VERSION"; then
  rm -rf "$TOOLS_DIR/ollama" && mkdir -p "$TOOLS_DIR/ollama"
  curl -fL "https://github.com/ollama/ollama/releases/download/v${OLLAMA_VERSION}/ollama-linux-amd64.tar.zst" -o "$TOOLS_DIR/ollama.tar.zst"
  tar --use-compress-program=unzstd -xf "$TOOLS_DIR/ollama.tar.zst" -C "$TOOLS_DIR/ollama" 2>/dev/null \
    || "$VENV_DIR/bin/python" -c "import sys,zstandard,tarfile; tarfile.open(fileobj=zstandard.ZstdDecompressor().stream_reader(open(sys.argv[1],'rb')), mode='r|').extractall(sys.argv[2])" "$TOOLS_DIR/ollama.tar.zst" "$TOOLS_DIR/ollama"
  rm -f "$TOOLS_DIR/ollama.tar.zst"
fi

echo "==> check"
if command -v nvidia-smi >/dev/null && nvidia-smi >/dev/null 2>&1; then
  "$TRAIN_VENV_DIR/bin/python" - <<'PY'
import torch, unsloth  # noqa: F401
print("torch", torch.__version__, "cuda", torch.cuda.is_available(),
      torch.cuda.get_device_name(0) if torch.cuda.is_available() else "-")
PY
else
  # docker build sees no GPU (Unsloth refuses to import without one): `make doctor` checks it
  "$TRAIN_VENV_DIR/bin/python" -c "import torch; print('torch', torch.__version__, '(no GPU here)')"
fi
mkdir -p "$(dirname "$ENV_FILE")"
{
  echo "# $(date '+%Y-%m-%d %H:%M') - versions of this setup"
  echo "ollama: $("$TOOLS_DIR/ollama/bin/ollama" --version 2>/dev/null | tail -1)"
  echo "llama.cpp: $(git -C "$TOOLS_DIR/llama.cpp" rev-parse --short HEAD)"
  echo "## $TRAIN_VENV_DIR"
  uv pip freeze --python "$TRAIN_VENV_DIR/bin/python"
} > "$ENV_FILE"
echo "Done. Versions: $ENV_FILE"
