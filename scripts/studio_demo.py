#!/usr/bin/env python3
"""The trainer studio on a made-up home, for trying it and for the guide's screenshots.

The example home of the router (Tomek, Ania, Ola, Kuba - no real data), a pretend GPU (nvidia-smi), a
pretend Home Assistant for the machine's power and a training log in progress (scripts/demo_workspace.py
builds the workspace). Login demo/demo.

    make demo                                       # in Docker (docker/Dockerfile, target demo)
    make demo-local                                 # = .venv/bin/python scripts/studio_demo.py
    .venv/bin/python scripts/studio_demo.py --shots  # the guide's pictures, docs/assets/screens/<lang>/studio-*.png

Needs for --shots: pip install playwright and Google Chrome.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import demo_workspace as screenshots  # noqa: E402

from router_trainer import router_source  # noqa: E402
from router_trainer.studio import server as studio_server  # noqa: E402
from router_trainer.ui import server as panel_server  # noqa: E402

OUT = ROOT / "docs" / "assets" / "screens"
CREDENTIALS = ("demo", "demo")
# the nodes photographed for the guide: file name -> (node, what to do before the picture)
SHOTS = {
    "studio-overview": ("overview", None),
    "studio-ha": ("ha", None),
    "studio-router": ("router", None),
    "studio-tests": ("tests", None),
    "studio-review": ("test/test1", None),
    "studio-generate": ("generate", None),
    "studio-dataset": ("dataset/demo", None),
    "studio-train": ("train", None),
    "studio-live": ("live", None),
    "studio-runs": ("runs", None),
    "studio-compare": ("compare", None),
    "studio-settings": ("settings/models/e4b", None),
    "studio-generate-settings": ("settings/generate", None),
    "studio-power": ("power", None),
    "studio-save": ("settings/models/e4b", "save"),
    "studio-jobs": ("jobs", None),
    "studio-try": ("try", None),
    "studio-machine": ("machine", None),
    "studio-look": ("look", None),
    "studio-gear": ("overview", "gear"),
}


def _paths_as_in_the_container(studio, root: Path, version: str) -> None:
    """The demo shows the paths of the real container (/data/...), not this computer's temporary folder
    or the router repository next to this one: the guide's pictures carry no paths of a Mac."""
    router = router_source.resolve(studio.ws.root, "auto")
    pairs = [(str(Path(root).resolve()), "/data"), (str(root), "/data"),
             (str(router), f"/data/workspace/router/v{version}")]  # fmt: skip
    outward = sorted(pairs, key=lambda pair: -len(pair[0]))
    call = studio.call

    def swap(value, table):
        text = json.dumps(value, ensure_ascii=False)
        for old, new in table:
            text = text.replace(json.dumps(old)[1:-1], json.dumps(new)[1:-1])
        return json.loads(text)

    def shown(message: dict, user: str = "") -> object:
        inward = [(new, old) for old, new in pairs[:1]]  # a job's log asked for by its shown path
        return swap(call(swap(message, inward), user), outward)

    studio.call = shown


def start_studio(root: Path, port: int = 0, host: str = "127.0.0.1"):
    """The studio on a made-up workspace; returns (server, port)."""
    ws = screenshots.demo_workspace(root / "workspace")
    screenshots.fake_nvidia_smi(root)
    os.environ["PATH"] = f"{root}:{os.environ['PATH']}"
    # what came from Home Assistant last time: the same router version as the code in use
    version = router_source.version_of(router_source.resolve(ws.root, "auto")) or "0.1.8"
    (ws.root / "inputs").mkdir(parents=True, exist_ok=True)
    (ws.root / "inputs" / "ha_export.json").write_text(json.dumps({
        "version": version, "language": "pl", "fetched": time.time() - 3600,
        "files": {"router": "router.yaml", "tests": "model_test.yaml", "log": "unrecognized_commands.csv"},
        "log_rows": 214, "automations": 37, "custom_sentences": 3,
    }), encoding="utf-8")  # fmt: skip
    panel_server.ha_client.Client = lambda *args, **kwargs: screenshots.DemoHomeAssistant(None)
    server = studio_server.make_server(
        ws, CREDENTIALS, host=host, port=port, verbose=False, secret_folder=root / "config"
    )
    _paths_as_in_the_container(server.studio, root, version)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def shots(port: int, out: Path = OUT) -> list[Path]:
    from playwright.sync_api import sync_playwright

    made = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        for language in ("pl", "en"):
            context = browser.new_context(
                viewport={"width": 1500, "height": 920},
                device_scale_factor=2,
                color_scheme="dark",
                locale="pl-PL" if language == "pl" else "en-US",
            )
            page = context.new_page()
            page.add_init_script(
                f"localStorage.setItem('router-trainer-studio-lang', '{language}');"
                "localStorage.setItem('router-trainer-studio-theme', 'dark');"
            )
            page.goto(f"http://127.0.0.1:{port}/login")
            page.fill("input[name=user]", CREDENTIALS[0])
            page.fill("input[name=password]", CREDENTIALS[1])
            page.click("button[type=submit]")
            page.wait_for_selector("[data-tree]")
            # the machine's state is read in the background: the pictures show it, not "checking"
            page.wait_for_function(
                "(() => { const s = document.querySelector('router-trainer-studio')._state;"
                " return s && !s.checking && s.machine && s.machine.machine !== 'checking'; })()",
                timeout=30_000,
            )
            for name, (node, then) in SHOTS.items():
                page.evaluate(f"location.hash = '#/{node}'")
                page.wait_for_selector(f"[data-view='{node}'] > *")
                if then == "save":
                    page.fill("[data-setting='models.e4b.epochs']", "2")
                    page.click("[data-save]")
                    page.wait_for_selector("dialog[data-dialog=save]")
                if then == "gear":
                    page.click("[data-settings]")
                    page.wait_for_selector("[data-gear-box]")
                page.wait_for_timeout(600)
                target = out / language / f"{name}.png"
                target.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=target)
                made.append(target)
                if then == "gear":
                    page.keyboard.press("Escape")
                if then == "save":
                    page.click("dialog[data-dialog=save] [data-close]")
                    page.click("[data-discard]")
                    page.click("[data-ask-ok]")
            context.close()
        browser.close()
    return made


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--host", default="127.0.0.1", help="0.0.0.0 in the demo container")
    parser.add_argument("--shots", action="store_true", help="take the guide's pictures and exit")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="router-trainer-studio-") as tmp:
        server, port = start_studio(Path(tmp), 0 if args.shots else args.port, args.host)
        if args.shots:
            for path in shots(port):
                print(path.relative_to(ROOT))
            server.shutdown()
            return
        shown = os.environ.get("DEMO_URL") or f"http://127.0.0.1:{port}/"
        print(f"Trainer studio (demo): {shown}  login demo / demo  (Ctrl+C stops)", flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            server.shutdown()


if __name__ == "__main__":
    main()
