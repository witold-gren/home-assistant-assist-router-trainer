#!/usr/bin/env bash
# Install (or update) the Assist Router trainer studio on an Ubuntu machine with an NVIDIA GPU.
#
#   docker/install-ubuntu.sh               check, write the login on the first run, build and start
#   docker/install-ubuntu.sh --show-login  print the login (user and password) from config/env
#   docker/install-ubuntu.sh --remove      stop and remove the container (data and config stay)
#
# Afterwards the studio starts with the machine: http://<machine>:8790/
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$HERE/config"
ENV_FILE="$CONFIG/env"
COMPOSE=(docker compose -f "$HERE/compose.yaml")
MIN_DRIVER=580

say() { printf '==> %s\n' "$*"; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

case "${1:-}" in
  --show-login)
    [ -f "$ENV_FILE" ] || fail "no $ENV_FILE yet - run docker/install-ubuntu.sh first"
    sed -n 's/^ROUTER_TRAINER_UI_AUTH=\([^:]*\):\(.*\)$/user: \1\npassword: \2/p' "$ENV_FILE"
    exit 0 ;;
  --remove)
    "${COMPOSE[@]}" down
    say "removed; $HERE/data and $CONFIG are kept"
    exit 0 ;;
  "") ;;
  *) sed -n '2,8p' "$0"; exit 1 ;;
esac

say "checking the machine"
command -v docker >/dev/null || fail "Docker is missing: https://docs.docker.com/engine/install/ubuntu/"
docker compose version >/dev/null 2>&1 || fail "the Docker Compose plugin is missing: sudo apt install docker-compose-plugin"
docker info >/dev/null 2>&1 || fail "this user cannot use Docker: sudo usermod -aG docker $(id -un) (then log in again)"
command -v nvidia-smi >/dev/null || fail "the NVIDIA driver is missing - install it first: sudo ubuntu-drivers install (then reboot)"
driver=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n 1 || true)
[ -n "$driver" ] || fail "nvidia-smi does not see the card - reboot after installing the driver: sudo reboot"
# the torch of the image (TORCH_SPEC, torch 2.14.1) is built for CUDA 13.0, which needs driver 580 or newer
[ "${driver%%.*}" -ge "$MIN_DRIVER" ] 2>/dev/null \
  || fail "NVIDIA driver $driver is too old for the image's CUDA 13.0 (needs $MIN_DRIVER or newer): sudo ubuntu-drivers install"
say "NVIDIA driver $driver"
docker info --format '{{json .Runtimes}}' | grep -q nvidia \
  || fail "the NVIDIA Container Toolkit is missing: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html (then: sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker)"
free_gb=$(df -Pk "$HERE" | awk 'NR == 2 { print int($4 / 1048576) }')
[ "$free_gb" -ge 200 ] || say "warning: only ${free_gb} GB free here - the image (~25 GB), base models, checkpoints and the teacher models need ~200 GB"

umask 077
# another folder of the machine can be used instead of docker/data (kept in docker/.env):
#   STUDIO_DATA=/mnt/big/router-trainer docker/install-ubuntu.sh
STUDIO_DATA="${STUDIO_DATA:-$HERE/data}"
mkdir -p "$CONFIG" "$STUDIO_DATA"
chmod 700 "$CONFIG"
if [ ! -f "$ENV_FILE" ]; then
  password=$(python3 -c "import secrets; print(secrets.token_urlsafe(18))")
  printf 'ROUTER_TRAINER_UI_AUTH=admin:%s\n' "$password" > "$ENV_FILE"
  say "login written to $ENV_FILE (show it: docker/install-ubuntu.sh --show-login)"
fi
chmod 600 "$ENV_FILE"
# ROUTER_REF set by hand in docker/.env (the router version baked into the image) is kept
router_ref=$(sed -n 's/^ROUTER_REF=//p' "$HERE/.env" 2>/dev/null || true)
printf 'UID=%s\nGID=%s\nSTUDIO_DATA=%s\n' "$(id -u)" "$(id -g)" "$STUDIO_DATA" > "$HERE/.env"
[ -z "$router_ref" ] || printf 'ROUTER_REF=%s\n' "$router_ref" >> "$HERE/.env"

if ! systemctl is-enabled --quiet docker 2>/dev/null; then
  say "starting Docker with the machine (sudo)"
  sudo systemctl enable --now docker
fi

# the panel before Docker (a systemd user service on the same port) goes, its files stay
if systemctl --user is-enabled --quiet router-trainer.service 2>/dev/null \
   || systemctl --user is-active --quiet router-trainer.service 2>/dev/null; then
  say "switching off the old panel service (router-trainer.service; its unit stays in ~/.config/systemd/user)"
  systemctl --user disable --now router-trainer.service || true
fi

say "building and starting (the first build downloads PyTorch, CUDA, Unsloth and Home Assistant, ~20 GB)"
"${COMPOSE[@]}" up -d --build
say "GPU in the container:"
"${COMPOSE[@]}" exec -T studio nvidia-smi --query-gpu=name,memory.total --format=csv,noheader \
  || say "warning: the container does not see the GPU - see the FAQ (no GPU in the container)"
say "ready: http://$(hostname -I 2>/dev/null | awk '{print $1}'):${STUDIO_PORT:-8790}/  (user and password: --show-login)"
