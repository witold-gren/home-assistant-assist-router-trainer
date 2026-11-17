"""The guide (MkDocs, docs/*.md in English and docs/*.pl.md in Polish) against gpu-studio.md section 8: the same
pages, anchors and screenshots in both languages; links and pictures exist; every button name in the text is a
real text of the studio; every card's "?" lands on an anchor; the parameter table holds the code's defaults."""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess

import pytest
import yaml

from router_trainer.studio import help as studio_help
from router_trainer.ui.texts import TEXTS

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
PAGES = sorted(
    p.name
    for p in DOCS.glob("*.md")
    if not p.name.endswith(".pl.md") and not p.name.startswith("changelog")
)
ANCHOR = re.compile(r"\{#([a-z0-9-]+)\}")
UI = re.compile(r'<span class="ui">(.+?)</span>')
PICTURE = re.compile(r"!\[[^\]]*\]\((assets/[^)]+)\)")
LINK = re.compile(r"\]\(([a-z-]+\.md)?(#[a-z0-9-]+)?\)")


def text(name: str, language: str) -> str:
    path = DOCS / (name if language == "en" else name.replace(".md", ".pl.md"))
    return path.read_text(encoding="utf-8")


def studio_texts(language: str) -> set[str]:
    source = (ROOT / "router_trainer" / "studio" / "www" / "i18n.js").read_text(encoding="utf-8")
    english, polish = source.split("\n  pl: {", 1)
    block = english if language == "en" else polish
    found = {
        m.replace('\\"', '"') for m in re.findall(r'^\s+\w+: "((?:[^"\\]|\\.)*)",?$', block, re.M)
    }
    return found | set(TEXTS[language].values())


def test_both_languages_have_the_same_pages_anchors_and_pictures() -> None:
    assert {"index.md", "installation.md", "screen.md", "steps.md", "good-practice.md", "home-assistant.md",
            "faq.md"} <= set(PAGES)  # fmt: skip
    for name in PAGES:
        english, polish = text(name, "en"), text(name, "pl")
        assert ANCHOR.findall(english) == ANCHOR.findall(polish), name
        assert [p.replace("/en/", "/") for p in PICTURE.findall(english)] == [
            p.replace("/pl/", "/") for p in PICTURE.findall(polish)
        ], name
        assert all("/pl/" not in p for p in PICTURE.findall(english)), name
        assert all("/en/" not in p for p in PICTURE.findall(polish)), name


@pytest.mark.parametrize("language", ["en", "pl"])
def test_pictures_and_links_exist(language) -> None:
    anchors = {name: set(ANCHOR.findall(text(name, "en"))) for name in PAGES}
    for name in PAGES:
        page = text(name, language)
        for picture in PICTURE.findall(page):
            assert (DOCS / picture).is_file(), f"{name}: {picture}"
        for target, anchor in LINK.findall(page):
            if target:
                assert target in anchors, f"{name}: {target}"
            if anchor:
                assert anchor[1:] in anchors[target or name], f"{name}: {target}{anchor}"


@pytest.mark.parametrize("language", ["en", "pl"])
def test_button_names_are_the_studios_own(language) -> None:
    known = studio_texts(language)
    for name in PAGES:
        for label in UI.findall(text(name, language)):
            assert label in known, f"{name} ({language}): {label!r} is not a text of the studio"


def test_every_card_help_lands_on_an_anchor() -> None:
    assert set(studio_help.LINKS) == set(studio_help.CARDS["en"])
    for card, target in studio_help.LINKS.items():
        page, _, anchor = target.partition("/#")
        assert anchor in ANCHOR.findall(text(f"{page}.md", "en")), card


def test_the_parameter_table_holds_the_codes_defaults() -> None:
    settings = yaml.safe_load(
        (ROOT / "router_trainer" / "trainer.example.yaml").read_text(encoding="utf-8")
    )
    for language in ("en", "pl"):
        page = text("good-practice.md", language)
        table = page.split("{#parameters}", 1)[1].split("\n## ", 1)[0]
        rows = re.findall(r"^\| `([a-z0-9_.]+)` \| ([^|]+) \|", table, re.M)
        assert len(rows) >= 30, language
        for path, default in rows:
            value = settings
            for part in path.split("."):
                value = value[part]
            assert str(value).lower() == default.strip().lower(), (
                f"{language}: {path} = {value}, table: {default}"
            )


@pytest.mark.skipif(
    not shutil.which("mkdocs", path=str(ROOT / ".venv" / "bin")),
    reason="make docs-build installs MkDocs",
)
def test_the_guide_builds_strictly(tmp_path) -> None:
    result = subprocess.run([str(ROOT / ".venv" / "bin" / "mkdocs"), "build", "--strict", "--quiet", "--site-dir",
                             str(tmp_path / "site")], cwd=ROOT, capture_output=True, text=True)  # fmt: skip
    assert result.returncode == 0, result.stderr[-2000:]
    assert (tmp_path / "site" / "index.html").is_file() and (
        tmp_path / "site" / "pl" / "faq" / "index.html"
    ).is_file()


TRY_ON_A_MAC = {
    "README.md": "## Try it on a Mac",
    "README.pl.md": "## Wypróbuj na Macu",
    "docs/installation.md": "## Try it on a Mac {#try-on-a-mac}",
    "docs/installation.pl.md": "## Wypróbuj na Macu {#try-on-a-mac}",
}


@pytest.mark.parametrize("name", sorted(TRY_ON_A_MAC))
def test_try_it_on_a_mac_is_short_and_matches_the_makefile(name) -> None:
    """gpu-studio.md section 8b: the same short section in both READMEs and both languages of the guide."""
    port = re.search(r"^DEMO_PORT \?= (\d+)$", (ROOT / "Makefile").read_text(), re.M).group(1)
    source = (ROOT / name).read_text(encoding="utf-8")
    heading = TRY_ON_A_MAC[name]
    assert heading + "\n" in source
    section = source.split(heading, 1)[1].split("\n## ", 1)[0]
    lines = [line for line in section.splitlines() if line.strip()]
    assert len(lines) <= 12
    for needed in (
        "make demo",
        f"http://localhost:{port}",
        "`demo` / `demo`",
        "Ctrl+C",
        "make test`",
        "make test-browser",
        "make docs`",
    ):
        assert needed in section, needed


def test_try_it_on_a_mac_stands_before_the_details() -> None:
    for name in ("README.md", "README.pl.md"):
        source = (ROOT / name).read_text(encoding="utf-8")
        headings = re.findall(r"^## (.+)$", source, re.M)
        assert headings[0] in ("Try it on a Mac", "Wypróbuj na Macu"), headings
