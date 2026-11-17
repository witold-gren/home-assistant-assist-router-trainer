#!/usr/bin/env bash
# `make migrate FROM=...`: the workspace of the old setup (panel as a systemd service in
# ~/assist-router-trainer/trainer/workspace) copied into docker/data/workspace for the container:
# tests, datasets, runs, the trainer's Ollama models, the HA connection and token. The old folder
# is not changed. trainer.yaml gets `router_repo: auto` (the router version of Home Assistant).
set -euo pipefail
cd "$(dirname "$0")/.."

FROM="${1:-$HOME/assist-router-trainer/trainer/workspace}"
TO=docker/data/workspace
[ -f "$FROM/trainer.yaml" ] || { echo "no workspace in $FROM (FROM=...)"; exit 1; }
if [ -f "$TO/trainer.yaml" ] && [ "${FORCE:-0}" != 1 ]; then
  echo "$TO already has a workspace - FORCE=1 make migrate to copy over it"; exit 1
fi
mkdir -p "$TO"
echo "==> copying $FROM -> $TO (the old one stays as it is)"
rsync -a --info=progress2 --exclude 'jobs/current.json' "$FROM/" "$TO/"

python3 - "$TO" <<'PY'
import json, re, sys
from pathlib import Path

ws = Path(sys.argv[1])
config = ws / "trainer.yaml"
text = config.read_text(encoding="utf-8")
text = re.sub(r"^router_repo:.*$", "router_repo: auto", text, flags=re.M)
config.write_text(text, encoding="utf-8")
ha = ws / "home_assistant.json"
if ha.exists():
    data = json.loads(ha.read_text(encoding="utf-8"))
    token = Path(str(data.get("token_file", "ha_token"))).expanduser()
    if token.is_absolute() and token.is_file():
        # a token outside the old workspace (~/.ha_token): the container sees only data/
        (ws / "ha_token").write_text(token.read_text(encoding="utf-8"), encoding="utf-8")
        (ws / "ha_token").chmod(0o600)
        data["token_file"] = "ha_token"
        ha.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
print("trainer.yaml: router_repo: auto; HA connection:", "kept" if ha.exists() else "none")
PY
echo "Done. Next: make up, open the panel, \"Fetch from Home Assistant\"; then make migrate-finish"
