"""`make help` lists every target in English and Polish, and the Makefile follows the GPU studio standard
(~/Home Assistant/standards/gpu-studio.md, section 2)."""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")
# gpu-studio.md section 2: the table's groups in their order, with the targets of a GPU application
GROUPS = [
    ("1. Start", ["help", "demo", "demo-clean", "docs", "docs-serve", "doctor"]),
    ("2. GPU machine", ["install", "deploy", "login", "logs", "status", "docker-up", "docker-down", "docker-logs",
                        "docker-shell", "migrate", "migrate-finish"]),
    ("3. Development", ["setup", "demo-local", "test", "test-browser", "test-docker", "test-all", "lint", "format",
                        "docs-build", "screenshots", "icons", "clean"]),
]  # fmt: skip
STANDARD_TARGETS = {target for _, targets in GROUPS for target in targets}
OLD_NAMES = {
    "ui",
    "ui-remote",
    "studio",
    "studio-demo",
    "studio-docker",
    "studio-icons",
    "show-login",
    "shell",
    "dev",
}


def described() -> dict[str, str]:
    return dict(re.findall(r"^([a-z0-9-]+):.*?## (.+)$", MAKEFILE, re.M))


def test_every_target_is_described_in_both_languages():
    phony = set(
        re.search(r"^\.PHONY: (.+?)(?<!\\)$", MAKEFILE, re.M | re.S)
        .group(1)
        .replace("\\\n", " ")
        .split()
    )
    assert phony == set(described())
    for target, text in described().items():
        english, _, polish = text.partition(" | ")
        assert english and polish, target


def test_the_studio_standard_targets_are_all_here():
    assert STANDARD_TARGETS - set(described()) == set()
    assert not OLD_NAMES & set(described())  # no aliases or old names


def _groups() -> list[tuple[str, list[str]]]:
    found = []
    for line in MAKEFILE.splitlines():
        if line.startswith("##@ "):
            found.append((line[4:].split(" | ")[0], []))
        elif found and (match := re.match(r"^([a-z0-9-]+):.*## ", line)):
            found[-1][1].append(match.group(1))
    return found


def test_the_groups_come_in_the_standards_order_with_their_targets():
    groups = _groups()
    assert len(groups) >= len(GROUPS)
    for (found, _), (name, _) in zip(groups, GROUPS, strict=False):
        assert found.startswith(name), (found, name)
    for (_, found), (name, targets) in zip(groups, GROUPS, strict=False):
        assert set(targets) <= set(found), name
        assert [t for t in found if t in targets] == targets, name  # the table's order
    # the trainer's own targets (data, train, ...) come after the table's groups
    assert {"fetch", "data", "train", "export", "evaluate"} <= set(groups[3][1])


def _prerequisites(target: str, seen: set[str] | None = None) -> set[str]:
    seen = set() if seen is None else seen
    line = re.search(rf"^{re.escape(target)}:([^#\n]*)", MAKEFILE, re.M)
    for name in line.group(1).split() if line else []:
        if name not in seen:
            seen.add(name)
            _prerequisites(name, seen)
    return seen


@pytest.mark.parametrize("target", GROUPS[0][1] + GROUPS[1][1])
def test_start_and_machine_targets_need_no_python_environment(target):
    """Group 1 and 2 need only Docker Desktop (and git, make, ssh, rsync of macOS)."""
    needed = _prerequisites(target) | {target}
    assert "setup" not in needed and not any(".venv" in name or "VENV" in name for name in needed)
    for name in needed:
        recipe = _recipe(name) if re.search(rf"^{re.escape(name)}:.*##", MAKEFILE, re.M) else ""
        assert "$(VENV)" not in recipe and "uv " not in recipe, name


def test_the_python_of_the_development_environment_is_set_once_and_made_by_uv():
    assert re.search(r"^PYTHON_VERSION \?= 3\.\d+$", MAKEFILE, re.M)
    assert "PYTHON_VERSION=$(PYTHON_VERSION) ./scripts/setup.sh" in MAKEFILE
    assert 'uv venv --python "$PYTHON_VERSION"' in (ROOT / "scripts" / "setup.sh").read_text(
        encoding="utf-8"
    )
    assert "astral.sh/uv/install.sh" in MAKEFILE  # without uv: how to install it


def test_the_tests_never_build_images_and_test_docker_does():
    assert '-m "not docker"' in _recipe("test") and '-m "not docker"' in _recipe("test-browser")
    assert "-m docker" in _recipe("test-docker")
    assert re.search(r"^test-all: lint test test-browser test-docker ##", MAKEFILE, re.M)
    assert "ruff check . && $(VENV)/bin/ruff format --check ." in _recipe("lint")
    assert "ruff check --fix . && $(VENV)/bin/ruff format ." in _recipe("format")
    assert (
        "docker"
        in (ROOT / "pyproject.toml")
        .read_text(encoding="utf-8")
        .split("markers", 1)[1]
        .split("]", 1)[0]
    )


def test_the_guide_is_built_and_served_in_docker():
    build = _recipe("docs-build")
    assert "docker build" in build and "--target docs-site" in build and "dest=site" in build
    assert "chmod -R u+rwX,go+rX site" in build  # readable by the web server of docs-hub
    serve = _recipe("docs-serve")
    assert "--target docs" in serve and "docker run --rm --init" in serve
    assert "-p 127.0.0.1:$(DOCS_PORT):9791" in serve and re.search(
        r"^DOCS_PORT \?= 9791$", MAKEFILE, re.M
    )
    assert (
        "-e SITE_URL=http://127.0.0.1:$(DOCS_PORT)/" in serve
    )  # the guide at the root, /pl/... too
    assert "$(CURDIR)/docs:/src/docs" in serve and "mkdocs.yml:/src/mkdocs.yml" in serve
    assert re.search(r"^docs: docs-build ##", MAKEFILE, re.M)


def test_the_machine_address_comes_from_the_shared_file():
    assert "-include $(HOME)/.config/gpu-studio/host.mk" in MAKEFILE
    assert MAKEFILE.index("gpu-studio/host.mk") < MAKEFILE.index("-include Makefile.local")
    assert not re.search(r"^GPU_HOST\s*\??=", MAKEFILE, re.M)  # no address in the repository
    assert re.search(r"^GPU_DIR \?= home-assistant-assist-router-trainer$", MAKEFILE, re.M)
    assert re.search(r"^UI_PORT \?= 8790$", MAKEFILE, re.M)
    assert re.search(r"^DEMO_PORT \?= 8791$", MAKEFILE, re.M)  # the demo = the studio's port + 1


def test_the_code_sent_to_the_machine_leaves_its_data_and_secrets():
    rsync = re.search(r"^RSYNC_CODE := (.+?)(?<!\\)$", MAKEFILE, re.M | re.S).group(1)
    for kept in (
        "docker/data",
        "docker/config",
        "docker/.env",
        "Makefile.local",
        "backup",
        "'workspace*'",
    ):
        assert f"--exclude {kept}" in rsync, kept


def test_the_browser_tests_are_their_own_target():
    assert "--ignore=$(BROWSER_TESTS)" in MAKEFILE
    assert (ROOT / re.search(r"^BROWSER_TESTS := (\S+)$", MAKEFILE, re.M).group(1)).exists()


@pytest.mark.skipif(not shutil.which("make"), reason="make not installed")
@pytest.mark.parametrize(
    "lang, expected",
    [("en", "1. Start (only Docker Desktop)"), ("pl", "1. Start (wystarczy Docker Desktop)")],
)
def test_make_help(lang, expected):
    result = subprocess.run(["make", "-s", "help", f"HELP_LANG={lang}"], cwd=ROOT, capture_output=True, text=True,
                            check=True)  # fmt: skip
    text = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    assert expected in text
    assert "  demo " in text and "  login " in text


@pytest.mark.skipif(not shutil.which("make"), reason="make not installed")
@pytest.mark.parametrize("target", ["install", "deploy", "login", "logs", "status"])
def test_without_a_machine_address_it_says_where_to_put_it(tmp_path, target):
    local = ROOT / "Makefile.local"
    if local.exists() and re.search(r"^GPU_HOST", local.read_text(encoding="utf-8"), re.M):
        pytest.skip("this computer's Makefile.local sets GPU_HOST")
    result = subprocess.run(
        ["make", "-s", target, f"HOME={tmp_path}"], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "~/.config/gpu-studio/host.mk" in result.stdout + result.stderr


def _recipe(target: str) -> str:
    return re.search(rf"^{target}:.*\n((?:\t.*\n|  .*\n)+)", MAKEFILE, re.M).group(1)


def test_make_demo_builds_the_demo_image_and_runs_it_in_docker():
    """gpu-studio.md section 8b: trying it needs only Docker Desktop."""
    recipe = _recipe("demo")
    assert "docker build" in recipe and "--target demo" in recipe
    assert "docker run --rm --init" in recipe
    assert "-p 127.0.0.1:$(DEMO_PORT):$(DEMO_PORT)" in recipe
    assert ".venv" not in recipe and "$(VENV)" not in recipe
    assert not re.search(r"^demo:.*\bsetup\b.*##", MAKEFILE, re.M)  # no Python environment first
    assert "DOCKER_READY" in recipe and "Docker Desktop" in MAKEFILE
    assert "docker image rm $(DEMO_IMAGE)" in _recipe("demo-clean")
    assert "studio_demo.py" in _recipe("demo-local")
    for target in ("test-browser", "screenshots"):
        assert "docker build" not in _recipe(target) and "docker run" not in _recipe(target)


def basic_tools(tmp_path: Path) -> Path:
    """A PATH with only the shell's basic tools, no docker and no uv. Not /usr/bin: on Linux docker lives
    there, and `make demo` would really start and never end (that hung the router's CI)."""
    folder = tmp_path / "bin"
    folder.mkdir(exist_ok=True)
    for name in ("bash", "sh", "env", "grep", "sed", "dirname", "cat", "cut", "rm"):
        found = shutil.which(name)
        if found:
            (folder / name).symlink_to(found)
    return folder


@pytest.mark.parametrize("target", ["demo", "docs", "docs-build", "docs-serve", "demo-clean"])
@pytest.mark.parametrize("missing", ["docker", "daemon"])
def test_without_docker_it_says_what_to_do(tmp_path, missing, target):
    if shutil.which("make") is None:
        pytest.skip("make is not installed")
    bin_dir = basic_tools(tmp_path)
    if missing == "daemon":
        fake = bin_dir / "docker"
        fake.write_text("#!/bin/sh\nexit 1\n")
        fake.chmod(0o755)
    result = subprocess.run(
        [shutil.which("make"), "-s", target], cwd=ROOT, capture_output=True, text=True, timeout=30,
        env={"PATH": str(bin_dir), "HOME": str(tmp_path)},
    )  # fmt: skip
    assert result.returncode != 0
    assert "Docker Desktop" in result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr


@pytest.mark.skipif(not shutil.which("make"), reason="make not installed")
def test_doctor_checks_without_installing_anything(tmp_path):
    """No Docker, no uv, no GPU_HOST: it lists what is missing with a hint, needs no .venv."""
    result = subprocess.run(
        [shutil.which("make"), "-s", "doctor", "GPU_HOST="], cwd=ROOT, capture_output=True, text=True,
        timeout=60, env={"PATH": str(basic_tools(tmp_path)), "HOME": str(tmp_path)},
    )  # fmt: skip
    out = result.stdout + result.stderr
    assert result.returncode != 0  # Docker is what group 1 needs
    assert "Docker Desktop" in out and "astral.sh/uv" in out and "gpu-studio/host.mk" in out
    assert "Traceback" not in out and not (tmp_path / ".local").exists()
    script = (ROOT / "scripts" / "doctor.sh").read_text(encoding="utf-8")
    assert "ssh -o BatchMode=yes -o ConnectTimeout=3" in script
    assert "install.sh | sh" not in script.replace(
        "curl -LsSf https://astral.sh/uv/install.sh | sh   (or", ""
    )
