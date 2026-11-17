"""The demo (and so the guide's pictures) shows the paths of the container, never this computer's: no home
folder, no temporary folder, no router repository next to this one (gpu-studio.md: pictures carry no paths)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "scripts")]

import studio_demo  # noqa: E402

LOCAL = re.compile(r"/(?:Users|home|var|private|tmp)/")


def test_the_demo_shows_no_path_of_this_computer(tmp_path, monkeypatch) -> None:
    # the demo swaps the Home Assistant client and PATH for the whole process: put them back afterwards
    client = studio_demo.panel_server.ha_client
    monkeypatch.setattr(client, "Client", client.Client)
    monkeypatch.setenv("PATH", os.environ["PATH"])
    server, _ = studio_demo.start_studio(tmp_path)
    studio = server.studio
    try:
        answers = [
            studio.call(message, "demo")
            for message in (
                {"type": "state", "language": "en"},
                {"type": "settings/get"},
                {"type": "history/list"},
                {"type": "jobs/history"},
            )
        ]
        jobs = answers[-1]["jobs"]
        assert jobs and all(job["log"].startswith("/data/") for job in jobs if job.get("log"))
        log = studio.call({"type": "jobs/log", "log": jobs[0]["log"]}, "demo")["text"]
        assert log  # a log asked for by its shown path still opens
        text = json.dumps(answers, ensure_ascii=False) + log
        assert not LOCAL.search(text), LOCAL.search(text).group(0)
        assert answers[0]["router"]["path"].startswith("/data/workspace/router/v")
    finally:
        server.shutdown()
        server.server_close()
