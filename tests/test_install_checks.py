"""docker/install-ubuntu.sh on a pretend machine: PATH holds only the ordinary tools and fakes of nvidia-smi,
docker, systemctl and df. Every missing piece (driver, a driver too old for the image's CUDA, Docker, compose,
access, the NVIDIA toolkit) stops it before anything is written, with the command that fixes it."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "docker" / "install-ubuntu.sh"
TOOLS = [
    *("bash", "sh", "sed", "grep", "head", "tail", "mkdir", "chmod", "cat", "id"),
    *("dirname", "awk", "env", "rm", "mv", "python3", "printf"),
]

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")

FAKES = {
    "nvidia-smi": """
case "$*" in
  *driver_version*) [ -n "$FAKE_DRIVER" ] && echo "$FAKE_DRIVER" || { echo "NVIDIA-SMI has failed" >&2; exit 9; } ;;
  *) echo "NVIDIA GeForce RTX 4090, 24564 MiB" ;;
esac
""",
    "docker": """
echo "docker $*" >> "$FAKE_LOG"
case "$1" in
  compose) case "$*" in *" version"*) [ -z "$FAKE_NO_COMPOSE" ] || exit 1 ;;
    *" exec "*) echo "NVIDIA GeForce RTX 4090, 24564 MiB" ;; esac ;;
  info) [ -z "$FAKE_NO_ACCESS" ] || exit 1
    case "$*" in *Runtimes*) echo "{\\"runc\\":{}$FAKE_RUNTIMES}" ;; esac ;;
esac
""",
    # Docker starts with the machine; the old panel service is not there
    "systemctl": 'case "$*" in *docker*) exit 0 ;; esac; exit 1\n',
    "df": 'echo "Filesystem 1K-blocks Used Available"; echo "/dev/x 1 1 ${FAKE_FREE_KB:-524288000}"\n',
    "hostname": "echo 10.0.0.2\n",
}


def fake_machine(tmp_path: Path, missing: tuple[str, ...] = ()) -> Path:
    docker = tmp_path / "repo" / "docker"
    docker.mkdir(parents=True)
    shutil.copy(SCRIPT, docker / SCRIPT.name)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in TOOLS:
        found = shutil.which(tool)
        if found:
            (bin_dir / tool).symlink_to(found)
    for name, body in FAKES.items():
        if name not in missing:
            fake = bin_dir / name
            fake.write_text("#!/bin/sh\n" + body)
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    (tmp_path / "home").mkdir()
    (tmp_path / "docker.log").touch()
    return docker


def run(tmp_path: Path, *args: str, **env: str):
    base = {
        "PATH": str(tmp_path / "bin"),
        "HOME": str(tmp_path / "home"),
        "FAKE_LOG": str(tmp_path / "docker.log"),
        "FAKE_DRIVER": "580.178.04",
        "FAKE_RUNTIMES": ',"nvidia":{}',
        "LANG": "C",
    }  # no USER: set -u must not stop the script before its message
    out = subprocess.run(
        [str(tmp_path / "bin" / "bash"), str(tmp_path / "repo" / "docker" / SCRIPT.name), *args],
        capture_output=True,
        text=True,
        env={**base, **env},
        timeout=60,
    )
    return out, (tmp_path / "docker.log").read_text()


@pytest.mark.parametrize(
    ("missing", "env", "message"),
    [
        (("nvidia-smi",), {}, "sudo ubuntu-drivers install"),
        ((), {"FAKE_DRIVER": ""}, "nvidia-smi does not see the card"),
        ((), {"FAKE_DRIVER": "550.163.01"}, "NVIDIA driver 550.163.01 is too old"),
        (("docker",), {}, "Docker is missing"),
        ((), {"FAKE_NO_COMPOSE": "1"}, "sudo apt install docker-compose-plugin"),
        (
            (),
            {"FAKE_NO_ACCESS": "1"},
            f"sudo usermod -aG docker {os.popen('id -un').read().strip()}",
        ),
        ((), {"FAKE_RUNTIMES": ""}, "the NVIDIA Container Toolkit is missing"),
    ],
    ids=[
        "no-driver",
        "driver-not-loaded",
        "old-driver",
        "no-docker",
        "no-compose",
        "no-access",
        "no-toolkit",
    ],
)
def test_a_missing_piece_stops_before_anything_is_written(tmp_path, missing, env, message) -> None:
    docker = fake_machine(tmp_path, missing)
    out, log = run(tmp_path, **env)
    assert out.returncode == 1, out.stdout + out.stderr
    assert message in out.stderr
    assert not (docker / "config").exists() and not (docker / ".env").exists()
    assert "up -d --build" not in log


def test_a_complete_machine_installs_and_starts(tmp_path) -> None:
    docker = fake_machine(tmp_path)
    out, log = run(tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "NVIDIA driver 580.178.04" in out.stdout
    assert "up -d --build" in log
    env_file = docker / "config" / "env"
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert stat.S_IMODE((docker / "config").stat().st_mode) == 0o700
    user, _, password = (
        env_file.read_text().strip().removeprefix("ROUTER_TRAINER_UI_AUTH=").partition(":")
    )
    assert user == "admin" and password and password not in out.stdout
    assert f"UID={os.getuid()}" in (docker / ".env").read_text()
    assert "NVIDIA GeForce RTX 4090" in out.stdout


def test_a_newer_driver_is_fine_and_little_space_only_warns(tmp_path) -> None:
    fake_machine(tmp_path)
    out, _ = run(tmp_path, FAKE_DRIVER="590.10", FAKE_FREE_KB=str(20 * 1048576))
    assert out.returncode == 0, out.stdout + out.stderr
    assert "warning: only 20 GB free" in out.stdout


def test_running_it_again_keeps_the_password_and_the_router_version(tmp_path) -> None:
    docker = fake_machine(tmp_path)
    run(tmp_path)
    env_file = docker / "config" / "env"
    first = env_file.read_text()
    (docker / ".env").write_text((docker / ".env").read_text() + "ROUTER_REF=v0.1.8\n")
    out, _ = run(tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr
    assert env_file.read_text() == first and "login written" not in out.stdout
    assert "ROUTER_REF=v0.1.8" in (docker / ".env").read_text()


def test_trusted_networks_are_written_changed_and_removed(tmp_path) -> None:
    docker = fake_machine(tmp_path)
    env_file = docker / "config" / "env"
    out, _ = run(tmp_path, STUDIO_TRUSTED_NETWORKS="192.168.1.0/24")
    assert out.returncode == 0, out.stdout + out.stderr
    assert "STUDIO_TRUSTED_NETWORKS=192.168.1.0/24\n" in env_file.read_text()
    assert "no login from: 192.168.1.0/24" in out.stdout
    password = env_file.read_text().splitlines()[0]
    out, _ = run(tmp_path, STUDIO_TRUSTED_NETWORKS="192.168.1.0/24,10.0.0.0/24")
    lines = env_file.read_text().splitlines()
    assert lines == [password, "STUDIO_TRUSTED_NETWORKS=192.168.1.0/24,10.0.0.0/24"]
    out, _ = run(tmp_path)  # not given: kept as it is
    assert env_file.read_text().splitlines() == lines
    out, _ = run(tmp_path, STUDIO_TRUSTED_NETWORKS="")  # given empty: the login from everywhere
    assert out.returncode == 0 and env_file.read_text().splitlines() == [password]
    assert "no login from: nowhere (login always)" in out.stdout
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600


def test_make_install_passes_the_trusted_networks_on() -> None:
    def dry(*args: str) -> str:
        return subprocess.run(["make", "-n", "install", "GPU_HOST=gpu", *args], cwd=SCRIPT.parents[1],
                              capture_output=True, text=True, check=True).stdout  # fmt: skip

    assert 'STUDIO_TRUSTED_NETWORKS="192.168.1.0/24" ./docker/install-ubuntu.sh' in dry(
        "STUDIO_TRUSTED_NETWORKS=192.168.1.0/24"
    )
    assert 'STUDIO_TRUSTED_NETWORKS="" ./docker/install-ubuntu.sh' in dry(
        "STUDIO_TRUSTED_NETWORKS="
    )
    assert "STUDIO_TRUSTED_NETWORKS" not in dry()


def test_compose_builds_the_studio_stage_by_name() -> None:
    """Without build.target compose builds the LAST stage of the Dockerfile; the demo stage there would start
    a healthy-looking demo instead of the studio."""
    import yaml

    compose = yaml.safe_load((REPO / "docker" / "compose.yaml").read_text(encoding="utf-8"))
    target = compose["services"]["studio"]["build"]["target"]
    stages = [
        line.split(" AS ")[-1].strip()
        for line in (REPO / "docker" / "Dockerfile").read_text(encoding="utf-8").splitlines()
        if line.startswith("FROM ") and " AS " in line
    ]
    assert target == "app" and target in stages
    assert {"demo", "docs"} <= set(stages)


def test_the_studio_runs_in_the_machines_time_zone() -> None:
    """gpu-studio.md section 3: without /etc/localtime the container runs in UTC and the dates of files, logs and
    jobs are 1-2 hours off Home Assistant's."""
    import yaml

    compose = yaml.safe_load((REPO / "docker" / "compose.yaml").read_text(encoding="utf-8"))
    assert "/etc/localtime:/etc/localtime:ro" in compose["services"]["studio"]["volumes"]
