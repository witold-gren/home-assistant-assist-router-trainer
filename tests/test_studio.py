"""The trainer studio: the login, the HTTP server (one /api/call), the draft and history of trainer.yaml,
switching the machine off after a job, the page's texts and icons, and the Docker files."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import threading
import urllib.error
import urllib.request

import pytest
import yaml

from router_trainer.config import init_workspace
from router_trainer.studio import auth as auth_module, server as studio_server
from router_trainer.ui.texts import TEXTS

REPO = Path(__file__).resolve().parents[1]
WWW = REPO / "router_trainer" / "studio" / "www"


# --- the login -----------------------------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def test_credentials() -> None:
    assert auth_module.parse_credentials("admin:pa:ss") == ("admin", "pa:ss")
    for bad in ("", "admin", ":x", "admin:"):
        with pytest.raises(ValueError, match="ROUTER_TRAINER_UI_AUTH"):
            auth_module.parse_credentials(bad)


def test_login_cookie_expiry_and_pause(tmp_path) -> None:
    clock = Clock()
    auth = auth_module.Auth(("admin", "secret"), tmp_path, clock=clock)
    cookie = auth.login("1.2.3.4", "admin", "secret")
    assert (
        auth.check(cookie) == "admin"
        and auth.check("admin|1|x") is None
        and auth.check(None) is None
    )
    assert "HttpOnly" in auth.set_cookie(cookie) and "Max-Age=0" in auth.clear_cookie()
    assert oct((tmp_path / auth_module.SECRET_FILE).stat().st_mode)[-3:] == "600"
    clock.now += auth_module.SESSION_SECONDS + 1
    assert auth.check(cookie) is None  # expired
    for _ in range(auth_module.MAX_FAILURES):
        with pytest.raises(auth_module.LoginRefused):
            auth.login("5.6.7.8", "admin", "wrong")
    with pytest.raises(auth_module.LoginRefused) as err:
        auth.login("5.6.7.8", "admin", "secret")  # paused, even with the right password
    assert err.value.retry_after > 0
    assert auth.login("1.2.3.4", "admin", "secret")  # another address is not paused
    # a new password logs everybody out
    other = auth_module.Auth(("admin", "new"), tmp_path, clock=clock)
    assert other.check(auth.login("1.2.3.4", "admin", "secret")) is None


def test_trusted_networks_are_read_and_recognised(tmp_path) -> None:
    networks = auth_module.parse_networks(" 192.168.1.0/24, 10.8.0.1/24;fd00::/8 ")
    assert [str(n) for n in networks] == ["192.168.1.0/24", "10.8.0.0/24", "fd00::/8"]
    assert auth_module.parse_networks("") == () and auth_module.parse_networks(None) == ()
    with pytest.raises(ValueError, match="STUDIO_TRUSTED_NETWORKS"):
        auth_module.parse_networks("192.168.1.0/24,home")
    auth = auth_module.Auth(("admin", "secret"), tmp_path, trusted_networks=networks)
    assert auth.trusted("192.168.1.5") and auth.trusted("10.8.0.200") and auth.trusted("fd00::1")
    assert auth.trusted("::ffff:192.168.1.5")  # IPv4 on a dual-stack socket
    assert not auth.trusted("192.168.2.5") and not auth.trusted("::ffff:192.168.2.5")
    assert not auth.trusted("not an address") and not auth.trusted("")
    nobody = auth_module.Auth(("admin", "secret"), tmp_path)
    assert not nobody.trusted("192.168.1.5") and not nobody.trusted("127.0.0.1")


# --- the HTTP server ------------------------------------------------------------------------------------


@pytest.fixture
def studio(tmp_path):
    ws = init_workspace(tmp_path / "ws")
    server = studio_server.make_server(ws, ("admin", "secret"), port=0, verbose=False,
                                       secret_folder=tmp_path / "config")  # fmt: skip
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield server, base
    server.shutdown()
    server.server_close()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request(base, path, data=None, cookie=None):
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    body = None if data is None else json.dumps(data).encode()
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(urllib.request.Request(base + path, data=body, headers=headers)) as answer:
            return answer.status, answer.headers, answer.read()
    except urllib.error.HTTPError as err:
        return err.code, err.headers, err.read()


def login(base) -> str:
    status, headers, _ = request(base, "/api/login", {"user": "admin", "password": "secret"})
    assert status == 200
    return headers["Set-Cookie"].split(";")[0]


def call(url, cookie, **message):
    status, _, body = request(url, "/api/call", message, cookie)
    return status, json.loads(body)


def test_only_health_and_login_without_a_cookie(studio) -> None:
    _, base = studio
    status, _, body = request(base, "/api/health")
    assert status == 200 and json.loads(body)["ok"]
    assert request(base, "/login")[0] == 200 and request(base, "/favicon.svg")[0] == 200
    status, headers, _ = request(base, "/")
    assert status == 303 and headers["Location"] == "/login"
    for path in ("/api/call", "/docs/pl/"):
        assert request(base, path, {} if path == "/api/call" else None)[0] == 401
    status, _, body = request(base, "/api/login", {"user": "admin", "password": "nope"})
    assert status == 401 and "retry_after" in json.loads(body)


@pytest.fixture
def trusted_studio(tmp_path):
    ws = init_workspace(tmp_path / "ws")
    server = studio_server.make_server(ws, ("admin", "secret"), port=0, verbose=False,
                                       secret_folder=tmp_path / "config",
                                       trusted_networks=auth_module.parse_networks("127.0.0.0/8"))  # fmt: skip
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_a_trusted_network_needs_no_login(trusted_studio) -> None:
    _, base = trusted_studio
    status, headers, _ = request(base, "/login")
    assert status == 303 and headers["Location"] == "/"
    assert request(base, "/")[0] == 200 and request(base, "/docs/pl/")[0] == 200
    status, body = call(base, None, type="state")
    assert status == 200 and body["studio"]["user"] == "admin" and body["studio"]["trusted"] is True


def test_without_a_trusted_network_a_faked_header_does_not_help(studio) -> None:
    _, base = studio
    for header in ("X-Forwarded-For", "X-Real-IP", "Forwarded"):
        value = "for=127.0.0.1" if header == "Forwarded" else "127.0.0.1"
        answer = urllib.request.Request(base + "/api/call", data=b'{"type": "state"}',
                                        headers={"Content-Type": "application/json", header: value})  # fmt: skip
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(answer)
        assert err.value.code == 401
    status, body = call(base, login(base), type="state")
    assert status == 200 and body["studio"]["trusted"] is False


def test_a_faked_header_does_not_make_an_untrusted_address_trusted(tmp_path) -> None:
    ws = init_workspace(tmp_path / "ws")
    server = studio_server.make_server(ws, ("admin", "secret"), port=0, verbose=False,
                                       secret_folder=tmp_path / "config",
                                       trusted_networks=auth_module.parse_networks("192.168.1.0/24"))  # fmt: skip
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        answer = urllib.request.Request(base + "/api/call", data=b'{"type": "state"}',
                                        headers={"Content-Type": "application/json",
                                                 "X-Forwarded-For": "192.168.1.5"})  # fmt: skip
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(answer)
        assert err.value.code == 401
        assert request(base, "/login")[0] == 200
    finally:
        server.shutdown()
        server.server_close()


def test_pages_files_and_the_guide_behind_the_login(studio) -> None:
    _, base = studio
    cookie = login(base)
    status, headers, page = request(base, "/", cookie=cookie)
    assert status == 200 and b"<router-trainer-studio>" in page
    assert headers["X-Frame-Options"] == "DENY" and headers["Cache-Control"] == "no-store"
    status, headers, _ = request(base, "/static/app.js", cookie=cookie)
    assert status == 200 and headers["Content-Type"].startswith("text/javascript")
    assert request(base, "/static/../server.py", cookie=cookie)[0] == 404
    assert request(base, "/static/%2e%2e/server.py", cookie=cookie)[0] == 404
    # the guide (MkDocs site/: English at the top, Polish in pl/), as the "?" opens it
    if not (REPO / "site" / "pl" / "index.html").is_file():
        pytest.skip("the guide is not built: make docs-build (make test does it first)")
    for path, text in (
        ("/docs/pl/", "Trener Assist Routera"),
        ("/docs/en/", "Assist Router trainer"),
        ("/docs/pl/faq/", "FAQ"),
        ("/docs/en/faq", "FAQ"),
        ("/docs/", "Assist Router trainer"),
    ):
        status, _, guide = request(base, path, cookie=cookie)
        assert status == 200 and text.encode() in guide, path
    status, headers, _ = request(base, "/docs/assets/screens/pl/studio-overview.png", cookie=cookie)
    assert status == 200 and headers["Content-Type"] == "image/png"
    assert request(base, "/docs/../server.py", cookie=cookie)[0] == 404
    # the guide's absolute links (site_url, e.g. the language switch) lead back to /docs/
    status, headers, _ = request(
        base, "/home-assistant-assist-router-trainer/pl/faq/", cookie=cookie
    )
    assert status == 302 and headers["Location"] == "/docs/pl/faq/"
    site_url = re.search(
        r'^site_url: !ENV \[SITE_URL, "(\S+)"\]$',
        (REPO / "mkdocs.yml").read_text(encoding="utf-8"),
        re.M,
    ).group(1)
    assert site_url.endswith(studio_server.SITE_PREFIX)
    assert request(base, "/api/logout", {}, cookie)[1]["Set-Cookie"].find("Max-Age=0") > 0


def test_state_and_unknown_calls(studio) -> None:
    _, base = studio
    cookie = login(base)
    status, state = call(base, cookie, type="state", language="pl")
    assert status == 200 and state["language"] == "pl" and state["studio"]["user"] == "admin"
    assert state["help"]["guide"].startswith("\n<h3") and "inputs" in state["help"]
    assert state["studio"]["power_off_delay"] == studio_server.POWER_OFF_DELAY
    assert {"ha", "inputs", "router", "machine", "status", "progress", "log"} <= set(state)
    status, answer = call(base, cookie, type="nope")
    assert status == 400 and "unknown call" in answer["error"]
    status, answer = call(base, cookie, type="action", action="start", kind="rm")
    assert status == 400


def test_draft_save_conflict_and_history(studio) -> None:
    _, base = studio
    cookie = login(base)
    _, loaded = call(base, cookie, type="settings/get")
    assert loaded["exists"] and loaded["draft"] is None and loaded["defaults"]["models"]
    text = loaded["text"] + "\nholdout: {word_similarity: 0.7}\n"
    call(base, cookie, type="draft/save", text=text, base=loaded["hash"])
    _, again = call(base, cookie, type="settings/get")
    assert again["draft"]["text"] == text and again["draft"]["outdated"] is False
    status, answer = call(base, cookie, type="settings/save", text="dataset: {dev_fraction: 9}\n",
                          base=loaded["hash"])  # fmt: skip
    assert status == 400 and "dev_fraction" in answer["error"]
    status, answer = call(
        base, cookie, type="settings/save", text=text, base=loaded["hash"], note="test"
    )
    assert status == 200 and answer["ok"]
    # a draft begun before that save: 409, then "Save anyway"
    status, answer = call(
        base, cookie, type="settings/save", text=loaded["text"], base=loaded["hash"]
    )
    assert status == 409 and answer["conflict"] is True
    status, _ = call(
        base, cookie, type="settings/save", text=loaded["text"], base=loaded["hash"], force=True
    )
    assert status == 200
    _, history = call(base, cookie, type="history/list")
    assert [v["user"] for v in history["versions"]] == ["admin", "admin"]
    assert history["versions"][1]["note"] == "test"
    _, old = call(base, cookie, type="history/get", id=history["versions"][0]["id"])
    assert old["text"] == text
    call(base, cookie, type="history/restore", id=history["versions"][0]["id"])
    _, after = call(base, cookie, type="settings/get")
    assert after["draft"]["text"] == text and after["text"] == loaded["text"]  # only the draft
    call(base, cookie, type="draft/discard")
    assert call(base, cookie, type="settings/get")[1]["draft"] is None


# --- switching the machine off after a job ----------------------------------------------------------------


def test_machine_goes_off_after_a_job_unless_cancelled_or_stopped(tmp_path, monkeypatch) -> None:
    from router_trainer import power

    from .test_power import connect

    clock = Clock()
    studio = studio_server.Studio(init_workspace(tmp_path / "ws"), clock=clock)
    with pytest.raises(ValueError, match="switch and power sensor"):
        studio.set_power_off(after_training=True)
    connect(studio.ws, monkeypatch)
    power.save_power(studio.ws, power.PowerSettings("switch.maszyna_gpu", "sensor.plug_power"))
    switched = []
    monkeypatch.setattr(studio.panel, "switch_machine", lambda on: switched.append(on))

    def job(running: bool, state: str = "ok") -> None:
        studio.panel.status = {
            "job": {"running": running, "state": "running" if running else state}
        }
        studio.tick()

    studio.set_power_off(after_training=True)
    job(True)
    job(False)  # the job ended: the countdown starts
    assert studio.power_off["at"] == clock.now + studio_server.POWER_OFF_DELAY
    clock.now += studio_server.POWER_OFF_DELAY - 1
    studio.tick()
    assert switched == []
    clock.now += 2
    job(True)  # an evaluation started meanwhile: wait for it
    assert switched == []
    job(False)
    clock.now += studio_server.POWER_OFF_DELAY + 1
    studio.tick()
    assert switched == [False] and studio.power_off == {"after_training": False, "at": None}
    # Stop never switches the machine off; cancel stops the countdown
    studio.set_power_off(after_training=True)
    job(True)
    job(False, "stopped")
    assert studio.power_off["at"] is None
    job(True)
    job(False)
    assert studio.set_power_off(cancel=True) == {"after_training": False, "at": None}
    clock.now += 10_000
    studio.tick()
    assert switched == [False]


# --- the page: texts, icons, files --------------------------------------------------------------------------


def _strings(language: str) -> set[str]:
    text = (WWW / "i18n.js").read_text(encoding="utf-8")
    block = text[text.index(f"  {language}: {{") :]
    block = block[: block.index("\n  },")]
    return set(re.findall(r"^\s{4}([a-z0-9_]+):", block, re.M))


def test_every_text_of_the_page_exists_in_both_languages() -> None:
    en, pl = _strings("en"), _strings("pl")
    assert en == pl
    known = en | set(TEXTS["en"])
    used = set()
    for file in [WWW / "app.js", WWW / "outline.js", *(WWW / "views").glob("*.js")]:
        source = file.read_text(encoding="utf-8")
        used |= set(re.findall(r'\bt\("([a-z0-9_]+)"', source)) | set(
            re.findall(r'_t\("([a-z0-9_]+)"', source)
        )
        used |= set(re.findall(r'"(h_[a-z0-9_]+)"', source))
    assert sorted(used - known) == []


def test_every_icon_is_in_the_icon_file() -> None:
    from router_trainer.studio import make_icons

    table = (WWW / "vendor" / "mdi.js").read_text(encoding="utf-8")
    missing = [icon for icon in make_icons.used_icons() if f'"{icon}"' not in table]
    assert missing == []


def test_the_page_links_its_files() -> None:
    page = (WWW / "index.html").read_text(encoding="utf-8")
    assert "/static/studio.css" in page and "/static/main.js" in page and "/favicon.svg" in page
    login_page = (WWW / "login.html").read_text(encoding="utf-8")
    assert "ROUTER_TRAINER_UI_AUTH" in login_page and "wakeword" not in login_page
    assert "router-trainer-studio" in (WWW / "studio.css").read_text(encoding="utf-8")


# --- Docker ---------------------------------------------------------------------------------------------


def test_compose_starts_with_the_machine_and_has_the_gpu() -> None:
    compose = yaml.safe_load((REPO / "docker" / "compose.yaml").read_text(encoding="utf-8"))
    service = compose["services"]["studio"]
    assert service["restart"] == "unless-stopped" and service["env_file"] == "./config/env"
    devices = service["deploy"]["resources"]["reservations"]["devices"]
    assert devices[0]["driver"] == "nvidia" and "gpu" in devices[0]["capabilities"]
    assert any(volume.endswith(":/data") for volume in service["volumes"])
    dockerfile = (REPO / "docker" / "Dockerfile").read_text(encoding="utf-8")
    assert (
        "--deps-only" in dockerfile and "HEALTHCHECK" in dockerfile and "USER trainer" in dockerfile
    )
    assert '"router-trainer", "studio"' in dockerfile
    ignored = (REPO / ".dockerignore").read_text(encoding="utf-8").split()
    assert {"docker/config", "docker/data", "docker/.env", "workspace*"} <= set(ignored)


def test_the_image_follows_the_studio_standard() -> None:
    """gpu-studio.md section 3: user and healthcheck in compose, torch pinned for the driver, the guide as its
    own stage built strictly, an import self-test after the environments and after the code."""
    service = yaml.safe_load((REPO / "docker" / "compose.yaml").read_text(encoding="utf-8"))[
        "services"
    ]["studio"]
    assert service["user"] == "${UID:-1000}:${GID:-1000}" and service["shm_size"]
    assert "/api/health" in " ".join(service["healthcheck"]["test"])
    dockerfile = (REPO / "docker" / "Dockerfile").read_text(encoding="utf-8")
    assert "AS docs" in dockerfile and "mkdocs build --strict" in dockerfile
    assert "COPY --from=docs" in dockerfile and "/app/site" in dockerfile
    assert (
        'TORCH_SPEC="torch==2.14.1"' in dockerfile
        and "torch==2.14.1" in service["build"]["args"]["TORCH_SPEC"]
    )
    assert dockerfile.count("self-test") >= 2
    setup = (REPO / "scripts" / "setup.sh").read_text(encoding="utf-8")
    assert "TORCH_SPEC-torch==2.14.1" in setup and '"$UNSLOTH_SPEC" $TORCH_SPEC' in setup
    ignored = (REPO / ".dockerignore").read_text(encoding="utf-8").split()
    assert "docs" not in ignored and "mkdocs.yml" not in ignored and "site" in ignored


def test_install_script_switches_the_old_panel_service_off() -> None:
    script = (REPO / "docker" / "install-ubuntu.sh").read_text(encoding="utf-8")
    assert "systemctl --user disable --now router-trainer.service" in script
    assert script.index("router-trainer.service") < script.index("up -d --build")


def test_install_script_shows_the_login(tmp_path) -> None:
    script = REPO / "docker" / "install-ubuntu.sh"
    assert subprocess.run(["bash", "-n", str(script)], check=False).returncode == 0
    copy = tmp_path / "install-ubuntu.sh"
    copy.write_text(script.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "env").write_text("ROUTER_TRAINER_UI_AUTH=admin:pa:ss\n")
    out = subprocess.run(
        ["bash", str(copy), "--show-login"], capture_output=True, text=True, check=True
    )
    assert out.stdout.split("\n")[:2] == ["user: admin", "password: pa:ss"]
