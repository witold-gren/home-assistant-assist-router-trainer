#!/usr/bin/env bash
# Start of the container: the workspace on the data volume, the router code it starts with, then the
# command (the studio by default). A job that was running when the container stopped is shown as
# failed; training resumes from its last checkpoint ("Resume" in the studio).
set -euo pipefail
mkdir -p /data/workspace /data/huggingface
router-trainer init >/dev/null
# the router code used until "Fetch the router version of Home Assistant": the one of the image
if [ ! -f /data/workspace/router/current ] && [ -d /opt/assist-router/custom_components ]; then
  tag="v$(python -c 'import json; print(json.load(open("/opt/assist-router/custom_components/assist_router/manifest.json"))["version"])')"
  mkdir -p /data/workspace/router
  [ -d "/data/workspace/router/$tag" ] || cp -a /opt/assist-router "/data/workspace/router/$tag"
  echo "$tag" > /data/workspace/router/current
fi
exec "$@"
