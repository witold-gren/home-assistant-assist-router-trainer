"""`make demo` in Docker (gpu-studio.md section 8b): the demo image builds, answers over HTTP, takes the demo
login and leaves no container behind when it stops; the guide builds in Docker. Skipped without Docker."""

from __future__ import annotations

import http.cookiejar
import json
from pathlib import Path
import shutil
import socket
import subprocess
import time
import urllib.request

import pytest

pytestmark = pytest.mark.docker

ROOT = Path(__file__).resolve().parent.parent
IMAGE = "router-trainer-demo-test"
ROUTER_NEXT = ROOT.parent / "home-assistant-assist-router" / "custom_components"


def docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    return (
        subprocess.run(["docker", "info"], capture_output=True, timeout=30, check=False).returncode
        == 0
    )


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def demo_image():
    if not docker_ready():
        pytest.skip("Docker is not installed or not running")
    context = ["--build-context", f"router={ROUTER_NEXT}"] if ROUTER_NEXT.is_dir() else []
    build = subprocess.run(
        ["docker", "build", "-q", "-f", "docker/Dockerfile", "--target", "demo", *context, "-t", IMAGE, "."],
        cwd=ROOT, capture_output=True, text=True, timeout=1200, check=False,
    )  # fmt: skip
    assert build.returncode == 0, build.stderr[-3000:]
    yield IMAGE
    subprocess.run(["docker", "image", "rm", IMAGE], capture_output=True, timeout=60, check=False)


def call(opener, path: str, port: int, data: dict | None = None) -> dict:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with opener.open(request, timeout=10) as response:
        return json.loads(response.read())


def test_the_demo_image_answers_takes_the_demo_login_and_leaves_nothing(demo_image):
    port = free_port()
    name = f"router-trainer-demo-test-{port}"
    run = subprocess.run(
        ["docker", "run", "--rm", "--init", "-d", "--name", name, "-p", f"127.0.0.1:{port}:{port}", demo_image,
         "python", "scripts/studio_demo.py", "--host", "0.0.0.0", "--port", str(port)],
        capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    assert run.returncode == 0, run.stderr
    try:
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        for _ in range(60):
            try:
                with opener.open(f"http://127.0.0.1:{port}/login", timeout=2) as page:
                    assert page.status == 200
                    break
            except OSError:
                time.sleep(0.5)
        else:
            pytest.fail("the demo did not answer: " + subprocess.run(
                ["docker", "logs", name], capture_output=True, text=True, check=False).stdout)  # fmt: skip
        with pytest.raises(urllib.error.HTTPError):
            call(opener, "/api/login", port, {"user": "demo", "password": "wrong"})
        assert call(opener, "/api/login", port, {"user": "demo", "password": "demo"}) == {
            "ok": True
        }
        state = call(opener, "/api/call", port, {"type": "state", "language": "en"})
        assert state["studio"]["user"] == "demo"
        assert state["router"]["version"]  # the router code went into the image
        with opener.open(f"http://127.0.0.1:{port}/docs/pl/", timeout=10) as guide:
            assert guide.status == 200
    finally:
        # what Ctrl+C does in `make demo`: the container stops and --rm removes it
        subprocess.run(
            ["docker", "kill", "-s", "INT", name], capture_output=True, timeout=30, check=False
        )
        for _ in range(40):
            left = subprocess.run(
                ["docker", "ps", "-aq", "--filter", f"name=^{name}$"],
                capture_output=True, text=True, timeout=30, check=False,
            ).stdout.strip()  # fmt: skip
            if not left:
                break
            time.sleep(0.5)
    assert not left, "the container is still there after stopping"


def test_the_guide_builds_in_docker_as_make_docs_build_does(tmp_path):
    """make docs-build (and docs-hub): the docs stage of the Dockerfile, its site copied out."""
    if not docker_ready():
        pytest.skip("Docker is not installed or not running")
    out = tmp_path / "site"
    build = subprocess.run(
        ["docker", "build", "-q", "-f", "docker/Dockerfile", "--target", "docs-site",
         "--output", f"type=local,dest={out}", "."],
        cwd=ROOT, capture_output=True, text=True, timeout=1200, check=False,
    )  # fmt: skip
    assert build.returncode == 0, build.stderr[-3000:]
    assert (out / "index.html").is_file() and (out / "pl" / "index.html").is_file()
    assert (out / "pl" / "installation" / "index.html").is_file()
