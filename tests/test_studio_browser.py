"""The studio in Google Chrome (Playwright), on the made-up home of scripts/studio_demo.py: the login, every
view without page errors, a setting changed in a form → draft → undo/redo → save with its changes → history,
the YAML on the side, the look, the language and the guide. Skipped without Playwright or Chrome."""

from __future__ import annotations

from pathlib import Path
import re
import sys
import threading
import time

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
playwright = pytest.importorskip("playwright.sync_api")

VIEWS = ["overview", "auto", "ha", "router", "tests", "test/test1", "generate", "datasets", "dataset/demo", "train", "live",
         "jobs", "runs", "run/demo-e4b", "compare", "try", "settings", "settings/ollama", "settings/teacher", "settings/generate",
         "settings/test", "settings/holdout", "settings/dataset", "settings/export", "settings/evaluate",
         "settings/home", "settings/models", "settings/models/e4b", "power", "machine", "account"]  # fmt: skip


@pytest.fixture(scope="module")
def studio(tmp_path_factory):
    import studio_demo

    server, port = studio_demo.start_studio(tmp_path_factory.mktemp("studio"))
    studio_url.server = server
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


# the tour starts by itself the first time; the tests of other things open the studio as seen before
TOUR_SEEN = "try { localStorage.setItem('router-trainer-studio-tour', 'done') } catch (e) {}"


class studio_url:  # the running demo server, for tests that steer the studio itself
    server = None


@pytest.fixture
def page(studio):
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception as err:  # no Google Chrome on this computer
            pytest.skip(f"Chrome: {err}")
        context = browser.new_context(viewport={"width": 1500, "height": 900})
        context.add_init_script(TOUR_SEEN)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto(f"{studio}/login")
        page.fill("input[name=user]", "demo")
        page.fill("input[name=password]", "demo")
        page.click("button[type=submit]")
        page.wait_for_selector("[data-tree]")
        page.errors = errors
        yield page
        assert errors == []
        browser.close()


def test_wrong_password_is_said(studio) -> None:
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception as err:
            pytest.skip(f"Chrome: {err}")
        page = browser.new_page()
        page.goto(f"{studio}/")
        assert page.url.endswith("/login")
        page.fill("input[name=user]", "demo")
        page.fill("input[name=password]", "nope")
        page.click("button[type=submit]")
        page.wait_for_function("document.getElementById('error').textContent.length > 0")
        browser.close()


def test_every_view_draws(page) -> None:
    for node in VIEWS:
        page.evaluate(f"location.hash = '#/{node}'")
        page.wait_for_selector(f"[data-view='{node}'] > *")
        assert "Error" not in page.locator(".view-host").inner_text()[:40], node
    page.click("[data-node='train']")
    page.wait_for_selector("[data-chip='e4b']", state="attached")
    assert page.locator("[data-chip]").count() == 2  # both models


def test_a_setting_goes_to_the_draft_and_is_saved_with_its_history(page) -> None:
    page.evaluate("location.hash = '#/settings/models/e4b'")
    field = page.locator("[data-setting='models.e4b.epochs']")
    field.fill("2")
    page.wait_for_selector("[data-draft-state=draft]")
    assert "epochs: 2" in page.locator("[data-side-yaml-text]").input_value()
    page.evaluate("document.activeElement.blur()")  # not in a field: the editor's undo
    page.keyboard.press("Control+z")
    page.wait_for_selector("[data-draft-state=clean]")
    page.keyboard.press("Control+Shift+z")
    page.wait_for_selector("[data-draft-state=draft]")
    page.click("[data-save]")
    page.wait_for_selector("dialog[data-dialog=save] .change.changed")
    assert "models/e4b" in page.locator("[data-changes]").inner_text()
    page.fill("[data-save-note]", "two epochs")
    page.click("[data-save-confirm]")
    page.wait_for_selector("[data-notice=ok]")
    page.wait_for_selector("[data-draft-state=clean]")
    page.click("[data-history]")
    page.wait_for_selector("[data-version]")
    assert "two epochs" in page.locator("[data-version]").first.inner_text()
    page.click("[data-version]")
    page.wait_for_selector("[data-restore]")
    page.click("[data-restore]")
    page.wait_for_selector("[data-draft-state=draft]")  # the old version is the draft
    page.click("[data-discard]")
    page.click("[data-ask-ok]")
    page.wait_for_selector("[data-draft-state=clean]")


def test_each_role_chooses_its_teacher(page) -> None:
    page.evaluate("location.hash = '#/settings/teacher'")
    page.select_option("[data-teacher-provider=writer]", "claude")
    page.wait_for_selector("[data-setting='teacher.writer.effort']")  # Claude only
    page.select_option("[data-teacher-provider=judge]", "manual")
    page.wait_for_selector("[data-handoff-export=judge]")  # judging by hand: export / import
    assert page.locator("[data-handoff-export=writer]").count() == 0  # the writer is not manual
    assert page.locator("[data-teacher-key=claude]").get_attribute("type") == "password"
    side = page.locator("[data-side-yaml-text]").input_value()
    assert "provider: claude" in side and "provider: manual" in side
    page.click("[data-discard]")
    page.click("[data-ask-ok]")
    page.wait_for_selector("[data-draft-state=clean]")


def test_the_yaml_on_the_side_changes_the_form(page) -> None:
    page.evaluate("location.hash = '#/settings/holdout'")
    side = page.locator("[data-side-yaml-text]")
    side.fill("word_similarity: 0.7\nchar_similarity: 0.85\n")
    page.wait_for_selector("[data-draft-state=draft]")
    assert page.locator("[data-setting='holdout.word_similarity']").input_value() == "0.7"
    side.fill("word_similarity: [")
    page.wait_for_selector("[data-side-yaml] .field-error")
    page.click("[data-discard]")
    page.click("[data-ask-ok]")
    page.wait_for_selector("[data-draft-state=clean]")


def test_a_trusted_network_opens_without_the_login_and_without_log_out(studio) -> None:
    import ipaddress

    auth = studio_url.server.auth
    auth.trusted_networks = (ipaddress.ip_network("127.0.0.0/8"),)
    try:
        with playwright.sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="chrome")
            except Exception as err:
                pytest.skip(f"Chrome: {err}")
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            page.add_init_script(TOUR_SEEN)
            errors = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            page.goto(f"{studio}/login")
            page.wait_for_selector("[data-tree]")
            assert not page.url.endswith("/login")
            page.click("[data-menu]")
            assert "STUDIO_TRUSTED_NETWORKS" in page.inner_text("[data-who]")
            assert page.locator("[data-logout]").count() == 0
            page.goto(f"{studio}/#/account")
            page.wait_for_selector("[data-trusted]")
            assert page.locator("[data-logout-view]").count() == 0
            assert errors == []
            browser.close()
    finally:
        auth.trusted_networks = ()


def test_look_language_and_guide(page) -> None:
    before = page.get_attribute("[data-theme-button]", "data-theme-button")
    page.click("[data-theme-button]")
    assert page.get_attribute("[data-theme-button]", "data-theme-button") != before
    page.click("[data-settings]")
    page.click("[data-gear-language=pl]")
    page.wait_for_function("document.documentElement.lang === 'pl'")
    page.keyboard.press("Escape")
    assert "Przegląd" in page.locator("[data-tree]").inner_text()
    # "?" in the top bar: the guide (MkDocs) in the studio's language, in a new tab
    assert page.get_attribute("[data-docs]", "target") == "_blank"
    with page.context.expect_page() as opened:
        page.click("[data-docs]")
    guide = opened.value
    guide.wait_for_load_state()
    assert guide.url.endswith("/docs/pl/") and "Trener Assist Routera" in guide.title()
    guide.close()


def test_the_gear_opens_a_small_window_with_the_look_and_language(page) -> None:
    """⚙ opens a window under itself (not the middle view): the theme and the language work at once and the
    window stays open; Esc, a click beside it and ⚙ again close it; ☰ and ⚙ close each other."""
    url = page.url
    page.click("[data-settings]")
    box = page.locator("[data-gear-box]")
    box.wait_for()
    gear = page.locator("[data-settings]").bounding_box()
    shown = box.bounding_box()
    assert shown["y"] >= gear["y"] + gear["height"] - 1  # under the button
    assert abs((shown["x"] + shown["width"]) - (gear["x"] + gear["width"])) < 2  # its right edge
    assert page.url == url and not page.locator("dialog[open]").count()
    page.click("[data-gear-theme=dark]")
    page.wait_for_function("document.documentElement.dataset.theme === 'dark'")
    assert page.get_attribute("[data-gear-theme=dark]", "aria-pressed") == "true"
    page.click("[data-gear-theme=light]")
    page.wait_for_function("document.documentElement.dataset.theme === 'light'")
    page.click("[data-gear-language=en]")
    page.wait_for_function("document.documentElement.lang === 'en'")
    assert box.is_visible() and page.url == url  # still open, the view did not change
    page.keyboard.press("Escape")
    box.wait_for(state="detached")
    page.click("[data-settings]")
    box.wait_for()
    page.mouse.click(5, page.viewport_size["height"] - 5)  # beside it
    box.wait_for(state="detached")
    page.click("[data-settings]")
    box.wait_for()
    page.click("[data-settings]")  # ⚙ again
    box.wait_for(state="detached")
    page.click("[data-settings]")
    page.click("[data-menu]")  # ☰ closes ⚙
    page.wait_for_selector("[data-menu-pop]")
    assert not box.count()
    page.keyboard.press("Escape")
    page.wait_for_selector("[data-menu-pop]", state="detached")
    page.click("[data-menu]")
    page.mouse.click(5, page.viewport_size["height"] - 5)
    page.wait_for_selector("[data-menu-pop]", state="detached")
    page.click("[data-settings]")
    page.click("[data-gear-all]")  # the whole look and language: its view in the tree
    page.wait_for_selector("[data-look-theme]")
    assert not box.count() and page.url.endswith("#/look")
    page.click("[data-look-theme=dark]")
    page.wait_for_function("document.documentElement.dataset.theme === 'dark'")
    assert page.get_attribute("[data-look-theme=dark]", "class") == "on"
    page.click("[data-settings]")
    page.click("[data-gear-theme=auto]")
    page.keyboard.press("Escape")


def test_the_top_bar_follows_the_standard(page) -> None:
    """gpu-studio.md section 5: ☰, icon and name; the job chip (stage, %, time left); the machine chip (GPU %,
    temperature, memory) and switch-off; the draft; the look, YAML, ?, ⚙, History, Save - in this order."""
    page.wait_for_selector("[data-job-pill]")
    assert re.search(
        r"\d+%", page.inner_text("[data-job-pill]")
    )  # the demo's training: step 510 of 806
    page.wait_for_function(
        "/GPU \\d+%/.test(document.querySelector('[data-machine]')?.textContent || '')"
    )
    # ☰ and ⚙ sit in a .menu-wrap with their windows: the button inside stands for it
    order = page.evaluate("""() => [...document.querySelector('header.top').children]
      .map((n) => n.classList.contains('menu-wrap') ? n.querySelector('button') : n)
      .map((n) => Object.keys(n.dataset)[0] || n.className.split(' ')[0] || n.tagName.toLowerCase())""")
    wanted = ["menu", "app-icon", "h1", "jobPill", "machine", "powerOff", "draftState", "undo", "redo",
              "themeButton", "yaml", "docs", "settings", "history", "save"]  # fmt: skip
    found = [item for item in order if item in wanted]
    assert found == wanted, order


def test_done_steps_are_marked(page) -> None:
    page.wait_for_selector("[data-done='ha']")  # fetched from HA in the demo
    page.wait_for_selector("[data-done='generate']", state="attached")  # a dataset exists


def test_card_help_is_a_popup_not_the_guide(page) -> None:
    """gpu-studio.md section 5, "Help": only the top bar's "?" opens the guide; a card's "?" opens a small popup
    (title, a few sentences, a quiet link to its anchor) that ✕, Esc, a click beside it and its "?" close."""
    page.evaluate("location.hash = '#/generate'")
    page.wait_for_selector("[data-view='generate'] > *")
    button = page.locator("[data-view='generate'] [data-help]").first
    pages = len(page.context.pages)
    button.click()
    popup = page.locator("[data-help-pop]")
    popup.wait_for()
    assert len(page.context.pages) == pages and page.url.endswith(
        "#/generate"
    )  # no new tab, no navigation
    assert popup.locator("strong").inner_text() and len(popup.locator("p").inner_text()) > 40
    link = popup.locator("[data-guide-link]")
    assert (
        link.get_attribute("href") == "/docs/en/steps/#dataset"
        and link.get_attribute("target") == "_blank"
    )
    page.keyboard.press("Escape")
    popup.wait_for(state="detached")
    button.click()
    popup.wait_for()
    page.mouse.click(700, 850)  # beside it
    popup.wait_for(state="detached")
    button.click()
    popup.wait_for()
    button.click()  # its "?" again
    popup.wait_for(state="detached")
    button.click()
    page.click("[data-help-close]")
    popup.wait_for(state="detached")
    assert page.locator("[data-help-pop]").count() == 0


def test_switching_off_counts_down_in_the_top_bar_and_can_be_cancelled(page) -> None:
    studio = studio_url.server.studio
    studio.power_off = {"after_training": True, "at": time.time() + 95}
    try:
        page.wait_for_selector("[data-power-countdown-top]", timeout=10000)
        assert re.search(r"1:3\d", page.inner_text("[data-power-countdown-top]"))
        page.click("[data-power-cancel-top]")
        page.wait_for_selector("[data-power-countdown-top]", state="detached", timeout=10000)
        assert studio.power_off == {"after_training": False, "at": None}
    finally:
        studio.power_off = {"after_training": False, "at": None}


def test_a_job_starts_and_its_progress_shows(page) -> None:
    """The start card: switching off after the job, what Resume would train; the live chart full screen; the
    job history with a whole log."""
    page.evaluate("location.hash = '#/train'")
    page.wait_for_selector("[data-power-after-start]")
    page.wait_for_selector("[data-resume-notes]")
    page.evaluate("location.hash = '#/live'")
    page.wait_for_selector("[data-loss-chart]")
    page.hover("[data-loss-chart]")
    page.wait_for_selector("[data-chart-tip]:not([hidden])")
    assert "loss" in page.inner_text("[data-chart-tip]")
    page.click("[data-chart-full]")
    big = page.locator("[data-loss-chart=big]")
    big.wait_for()
    box = big.bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.3, box["y"] + 50)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.6, box["y"] + 50, steps=5)
    page.mouse.up()
    page.wait_for_selector("[data-chart-reset]")  # zoomed in
    box = page.locator("[data-loss-chart=big]").bounding_box()
    page.mouse.click(box["x"] + box["width"] * 0.5, box["y"] + 50)
    page.wait_for_function(
        "document.querySelector('[data-chart-overlay] [data-chart-pin]')?.textContent.length > 0"
    )
    page.click("[data-chart-close]")
    page.evaluate("location.hash = '#/jobs'")
    page.wait_for_selector("[data-job-row]")
    page.click("[data-job-history-open]")
    page.wait_for_selector("[data-job-history-log]:not([hidden])")
    assert "==> " in page.inner_text("[data-job-history-log]")


def test_a_form_changes_only_its_value_in_the_file(page) -> None:
    """Comments and their alignment stay: only the number changes (one line in the save dialog)."""
    page.evaluate("location.hash = '#/settings/models/e4b'")
    page.locator("[data-setting='models.e4b.lora_r']").fill("32")
    page.wait_for_selector("[data-draft-state=draft]")
    page.click("[data-save]")
    page.wait_for_selector("dialog[data-dialog=save] [data-diff]")
    removed = page.locator("[data-diff] .removed").all_inner_texts()
    added = page.locator("[data-diff] .added").all_inner_texts()
    assert len(removed) == 1 and len(added) == 1 and "lora_r: 32" in added[0]
    page.click("dialog[data-dialog=save] [data-close]")
    page.click("[data-discard]")
    page.click("[data-ask-ok]")
    page.wait_for_selector("[data-draft-state=clean]")


# --- the app never freezes (gpu-studio.md section 9a) -------------------------------------------------------


def steer_state(delay: float = 0.0, hang: float = 0.0, kind: str = "state"):
    """Make the demo's answers of one call type slow (or hang), counting how many run at once."""
    studio = studio_url.server.studio
    real = type(studio).call.__get__(studio)
    seen = {"now": 0, "most": 0, "calls": 0, "texts": []}
    lock = threading.Lock()

    def call(message, user="", trusted=False):
        if message.get("type") != kind:
            return real(message, user, trusted)
        with lock:
            seen["now"] += 1
            seen["calls"] += 1
            seen["texts"].append(message.get("text"))
            seen["most"] = max(seen["most"], seen["now"])
        try:
            time.sleep(delay or hang)
            return real(message, user, trusted)
        finally:
            with lock:
                seen["now"] -= 1

    studio.call = call
    return seen


@pytest.fixture
def restore_studio():
    yield
    studio_url.server.studio.__dict__.pop("call", None)


def test_a_slow_studio_is_asked_one_state_at_a_time(page, restore_studio) -> None:
    seen = steer_state(delay=3.0)
    page.click("[data-node='live']")  # views and actions ask for the state too
    page.click("[data-node='overview']")
    page.wait_for_timeout(9000)
    assert seen["calls"] >= 2 and seen["most"] == 1, seen


def test_a_tab_in_the_background_does_not_ask(page) -> None:
    states = []
    page.on(
        "request",
        lambda r: (
            states.append(r)
            if r.url.endswith("/api/call") and '"state"' in (r.post_data or "")
            else None
        ),
    )
    page.evaluate("""() => {
      Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
      document.dispatchEvent(new Event("visibilitychange"));
    }""")
    page.wait_for_timeout(2500)  # a request already sent may still end
    states.clear()
    page.wait_for_timeout(5000)
    assert states == []
    page.evaluate("""() => {
      Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
      document.dispatchEvent(new Event("visibilitychange"));
    }""")
    page.wait_for_timeout(1000)
    assert states  # asked again at once when shown


def test_a_request_without_an_answer_ends_with_a_message(page, restore_studio) -> None:
    page.evaluate("window.__studioCallTimeoutMs = 1500")
    steer_state(hang=6.0)
    page.wait_for_selector("[data-error-notice]", timeout=15000)
    assert "did not answer within 2 s" in page.inner_text("[data-error-notice]")
    page.evaluate("window.__studioCallTimeoutMs = 0")
    studio_url.server.studio.__dict__.pop("call", None)
    page.wait_for_selector(
        "[data-error-notice]", state="detached", timeout=15000
    )  # and it comes back


def test_every_view_draws_without_long_tasks(studio) -> None:
    """All views on the demo's big data (a test of 618 cases, a long training log) without a task over 500 ms."""
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception as err:
            pytest.skip(f"Chrome: {err}")
        page = browser.new_context(viewport={"width": 1500, "height": 900}).new_page()
        page.add_init_script(TOUR_SEEN)
        page.add_init_script("""
          window.__longTasks = [];
          new PerformanceObserver((list) => { for (const e of list.getEntries()) window.__longTasks.push(e.duration); })
            .observe({ type: "longtask", buffered: true });
        """)
        page.goto(f"{studio}/login")
        page.fill("input[name=user]", "demo")
        page.fill("input[name=password]", "demo")
        page.click("button[type=submit]")
        page.wait_for_selector("[data-tree]")
        for node in VIEWS:
            page.evaluate(f"location.hash = '#/{node}'")
            page.wait_for_selector(f"[data-view='{node}'] > *")
        page.evaluate("location.hash = '#/test/test1'")
        page.wait_for_selector(
            "[data-review-more]", state="attached"
        )  # a page of the 618 cases, not all
        assert page.locator("[data-case]").count() == 150
        page.wait_for_timeout(1500)
        longest = max(page.evaluate("window.__longTasks") or [0])
        browser.close()
    assert longest < 500, f"a task of {longest:.0f} ms"


def test_a_slow_draft_save_is_one_at_a_time_and_keeps_the_last_change(page, restore_studio) -> None:
    """The draft is saved after a pause in typing; with a server slower than that pause the saves must not
    run in parallel (answers in the wrong order kept an older draft) and the last one has the last change."""
    page.evaluate("location.hash = '#/settings/models/e4b'")
    field = page.locator("[data-setting='models.e4b.lora_r']")
    field.wait_for()
    seen = steer_state(delay=1.5, kind="draft/save")
    for value in ("17", "18", "19", "20"):
        field.fill(value)
        page.wait_for_timeout(900)
    page.wait_for_function(
        "!document.querySelector('[data-draft-state]')?.textContent.includes('…')", timeout=15000
    )
    page.wait_for_timeout(2500)
    assert seen["most"] == 1, seen["most"]
    assert 1 <= seen["calls"] < 4, seen["calls"]
    assert "lora_r: 20" in seen["texts"][-1]
    studio_url.server.studio.__dict__.pop("call", None)
    page.click("[data-discard]")
    page.click("[data-ask-ok]")
    page.wait_for_selector("[data-draft-state=clean]")


def test_the_columns_fold_and_stay_folded(page, studio) -> None:
    """gpu-studio.md section 5, "Folding the columns": ‹ / › buttons and Ctrl/⌘+B, Ctrl/⌘+Alt+B; the middle gets
    wider; a narrow bar with its unfold button stays; the state survives a reload, the width comes back."""
    middle = lambda: page.locator("main.middle").bounding_box()["width"]  # noqa: E731
    page.wait_for_selector("[data-tree]")
    tree_width = page.locator("[data-tree]").bounding_box()["width"]
    before = middle()
    assert "Ctrl/⌘+B" in page.get_attribute("[data-fold-col=left]", "title")
    page.click("[data-tree] [data-fold-col=left]")
    bar = page.locator("[data-folded=left]")
    bar.wait_for()
    assert bar.bounding_box()["width"] < 40 and middle() > before + 100
    assert (
        page.locator("[data-splitter=left].off").count() == 1
    )  # a folded column's splitter does not drag
    page.evaluate("document.activeElement.blur()")
    page.keyboard.press("Control+b")
    page.wait_for_selector("[data-tree]")
    assert (
        abs(page.locator("[data-tree]").bounding_box()["width"] - tree_width) < 2
    )  # its width came back
    page.keyboard.press("Control+Alt+b")
    page.wait_for_selector("[data-folded=right]")
    assert middle() > before + 100
    page.reload()
    page.wait_for_selector("[data-tree]")
    page.wait_for_selector("[data-folded=right]")  # remembered
    page.click("[data-folded=right] [data-fold-col=right]")
    page.wait_for_selector("[data-side]")
    assert page.locator("[data-folded]").count() == 0


def test_a_narrow_window_starts_with_the_right_column_folded(studio) -> None:
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception as err:
            pytest.skip(f"Chrome: {err}")
        page = browser.new_context(viewport={"width": 820, "height": 900}).new_page()
        page.add_init_script(TOUR_SEEN)
        page.goto(f"{studio}/login")
        page.fill("input[name=user]", "demo")
        page.fill("input[name=password]", "demo")
        page.click("button[type=submit]")
        page.wait_for_selector("[data-tree]")
        page.wait_for_selector("[data-folded=right]")
        browser.close()


def test_automatic_training_has_one_start_and_waits_for_a_result(page) -> None:
    page.evaluate("location.hash = '#/auto'")
    page.wait_for_selector("[data-auto-start]")
    assert page.locator("[data-auto-name]").input_value().startswith("home-")
    page.click("[data-auto-test] [data-value='new']")
    assert page.get_attribute("[data-auto-test] [data-value='new']", "aria-pressed") == "true"
    page.wait_for_selector("[data-router-model]")
    assert page.locator("[data-auto-result]").count() == 0  # no automatic run yet
    page.evaluate("location.hash = '#/train'")
    page.wait_for_selector("[data-view='train'] > *")
    page.wait_for_timeout(500)
    assert page.evaluate("location.hash") == "#/train"  # the summary arriving does not pull it back


# --- the tour and the lessons (gpu-studio.md section 5a) ----------------------------------------------------


def _fresh_page(studio, p, width=1500):
    """A browser that never saw the studio: the tour starts by itself."""
    try:
        browser = p.chromium.launch(channel="chrome")
    except Exception as err:  # no Google Chrome on this computer
        pytest.skip(f"Chrome: {err}")
    page = browser.new_context(viewport={"width": width, "height": 900}).new_page()
    page.goto(f"{studio}/login")
    page.fill("input[name=user]", "demo")
    page.fill("input[name=password]", "demo")
    page.click("button[type=submit]")
    page.wait_for_selector("[data-tree]")
    return browser, page


def test_the_tour_starts_by_itself_once_and_again_from_the_gear(studio) -> None:
    with playwright.sync_playwright() as p:
        browser, page = _fresh_page(studio, p)
        page.wait_for_selector("router-trainer-tour [data-tour-bubble='welcome']")
        page.click("router-trainer-tour [data-tour-next]")
        page.wait_for_selector("router-trainer-tour [data-tour-frame='tree']")
        assert "Ctrl/⌘+B" in page.locator("router-trainer-tour [data-tour-bubble]").inner_text()
        page.keyboard.press("ArrowRight")
        page.wait_for_selector("router-trainer-tour [data-tour-frame='middle']")
        page.keyboard.press("Escape")
        page.wait_for_selector("router-trainer-tour", state="detached")
        page.reload()
        page.wait_for_selector("[data-tree]")
        page.wait_for_timeout(500)
        assert page.locator("router-trainer-tour").count() == 0  # seen: not again by itself
        page.click("[data-settings]")
        page.click("[data-gear-tour]")
        page.wait_for_selector("router-trainer-tour [data-tour-bubble='welcome']")
        page.click("router-trainer-tour [data-tour-skip]")
        page.wait_for_selector("router-trainer-tour", state="detached")
        browser.close()


def test_every_tour_step_frames_its_part(page) -> None:
    page.click("[data-settings]")
    page.click("[data-gear-tour]")
    steps = page.evaluate("import('/static/tour.js').then((m) => m.TOUR_STEPS.map((s) => s.key))")
    shown = page.locator("router-trainer-tour [data-tour-count]").inner_text()
    count = int(re.search(r"(\d+)\D*$", shown)[1])
    assert count >= len(steps) - 1  # only a part not on the demo's screen may be left out
    for _ in range(count):
        bubble = page.locator("router-trainer-tour [data-tour-bubble]")
        key = bubble.get_attribute("data-tour-bubble")
        if key != "welcome":
            page.wait_for_selector(f"router-trainer-tour [data-tour-frame='{key}']")
        assert not bubble.inner_text().count("studio_tour_"), key  # every text is there
        page.click("router-trainer-tour [data-tour-next]")
    page.wait_for_selector("router-trainer-tour", state="detached")


@pytest.mark.parametrize("language", ["pl", "en"])
def test_every_lesson_step_finds_its_part_on_the_demo(page, language) -> None:
    if language == "pl":
        page.click("[data-settings]")
        page.click("[data-gear-language='pl']")
        page.keyboard.press("Escape")
    lessons = page.evaluate(
        "import('/static/lessons.js').then((m) => m.LESSONS.map((l) => [l.key, l.steps.map((s) => s.key)]))"
    )
    assert len(lessons) >= 17
    for key, steps in lessons:
        page.click("[data-settings]")
        page.click("[data-gear-lessons]")
        page.click(f"dialog[data-dialog=lessons] [data-lesson='{key}']")
        for step in steps:
            page.wait_for_selector(f"router-trainer-tour [data-tour-frame='{step}']", timeout=5000)
            text = page.locator("router-trainer-tour [data-tour-bubble]").inner_text()
            assert "lesson_" not in text, (key, step)
            assert not _bubble_covers_frame(page), (key, step)
            page.click("router-trainer-tour [data-tour-next]")
        page.wait_for_selector("router-trainer-tour", state="detached")
        page.keyboard.press("Escape")  # ⚙ a lesson left open
    page.click("[data-settings]")
    page.click("[data-gear-lessons]")
    assert page.locator("[data-lesson-done]").count() == len(
        lessons
    )  # each one gone through is marked


def _bubble_covers_frame(page) -> bool:
    """Whether the bubble stands over the framed part (a step framed "inside" a large part may)."""
    page.wait_for_timeout(450)  # the bubble and the frame move with a 0.25 s transition
    return page.evaluate("""() => {
      const tour = document.querySelector('router-trainer-tour');
      const lesson = tour.lesson, step = (lesson ? tour._steps : tour._steps)[tour._index];
      if (step.side === 'inside') return false;
      const f = tour.shadowRoot.querySelector('[data-tour-frame]')?.getBoundingClientRect();
      const b = tour.shadowRoot.querySelector('[data-tour-bubble]').getBoundingClientRect();
      if (!f) return false;
      // a frame as large as the window leaves no free side
      if (f.width > innerWidth - 400 && f.height > innerHeight - 300) return false;
      return b.left < f.right && b.right > f.left && b.top < f.bottom && b.bottom > f.top;
    }""")


def test_next_on_a_step_waiting_for_a_click_does_what_the_click_does(page) -> None:
    page.click("[data-settings]")
    page.click("[data-gear-lessons]")
    page.click("dialog[data-dialog=lessons] [data-lesson='look']")
    page.wait_for_selector("router-trainer-tour [data-tour-try]")
    page.click("router-trainer-tour [data-tour-next]")  # not ⚙ itself
    page.wait_for_selector("[data-gear-box]")
    page.wait_for_selector("router-trainer-tour [data-tour-frame='choices']")
    assert not _bubble_covers_frame(page)
    page.keyboard.press("Escape")


def test_a_lesson_moves_on_with_the_click_of_its_framed_button(page) -> None:
    page.click("[data-settings]")
    page.click("[data-gear-lessons]")
    page.click("dialog[data-dialog=lessons] [data-lesson='look']")
    page.wait_for_selector("router-trainer-tour [data-tour-try]")  # it waits for ⚙
    page.mouse.click(10, 450)  # the rest of the screen does nothing
    assert page.locator("router-trainer-tour [data-tour-frame='gear']").count() == 1
    page.click("[data-settings]")
    page.wait_for_selector("router-trainer-tour [data-tour-frame='choices']")
    page.click("router-trainer-tour [data-tour-next]")  # Next does not close ⚙
    page.wait_for_selector("router-trainer-tour [data-tour-frame='learn']")
    assert page.locator("[data-gear-box]").count() == 1
    page.click("router-trainer-tour [data-tour-next]")
    page.wait_for_selector("router-trainer-tour", state="detached")
    page.keyboard.press("Escape")
    page.click("[data-settings]")
    page.click("[data-gear-lessons]")
    assert page.locator("[data-lesson='look'] [data-lesson-done]").count() == 1


def test_the_help_of_a_card_shows_its_lesson(page) -> None:
    page.evaluate("location.hash = '#/ha'")
    page.click("[data-view='ha'] [data-help='inputs']")
    page.click("[data-help-lesson='connect']")
    page.wait_for_selector("router-trainer-tour [data-tour-frame='url']")
    page.fill("[data-ha-url]", "http://ha.example:8123")
    page.keyboard.press("ArrowLeft")  # typing in a framed field keeps its keys
    page.keyboard.press("Enter")
    assert page.locator("router-trainer-tour [data-tour-frame='url']").count() == 1
    page.keyboard.press("Escape")
    page.wait_for_selector("router-trainer-tour", state="detached")


def test_a_model_is_added_and_pairs_and_maps_go_to_the_draft(page) -> None:
    page.evaluate("location.hash = '#/settings/models'")
    page.fill("[data-model-name]", "e4b_r32")
    page.click("[data-model-add]")
    page.wait_for_selector(".field-error:not([hidden])")  # no base yet
    page.fill("[data-model-base]", "unsloth/gemma-4-E4B-it")
    page.click("[data-model-add]")
    page.wait_for_selector("[data-view='settings/models/e4b_r32']")
    assert (
        page.locator("[data-setting='models.e4b_r32.lora_r']").input_value() != ""
    )  # copied from the first
    page.evaluate("location.hash = '#/settings/generate'")
    page.fill(
        "[data-setting='generate.router.contrast.extra']", "czytania/wiadomosci, czytania/kalendarz"
    )
    page.evaluate("location.hash = '#/settings/home'")
    page.fill("[data-setting='topic_overrides']", "asystent_czytania: czytania")
    page.wait_for_function(
        "document.querySelector('router-trainer-studio')._current.includes('asystent_czytania')"
    )
    text = page.evaluate("document.querySelector('router-trainer-studio')._current")
    assert "e4b_r32:" in text and "unsloth/gemma-4-E4B-it" in text
    assert "czytania" in text.split("extra:", 1)[1].split("\n", 3)[1]
    page.click("[data-discard]")
    page.click("[data-ask-ok]")
