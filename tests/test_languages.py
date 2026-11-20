"""Language packs: a new language is a module with the names of pl.py; Home Assistant's language
is used when router.yaml does not choose one."""

from __future__ import annotations

import json
import re
import shutil

import pytest

from router_trainer import cli, context, languages
from tests.conftest import needs_router


def test_every_pack_has_every_name_of_the_reference() -> None:
    for code in languages.available():
        assert languages.missing(code) == [], code
        assert languages.problems(languages.FOLDER / code) == [], code


def test_a_new_pack_is_told_what_it_lacks(tmp_path, capsys) -> None:
    folder = tmp_path / "xx"
    shutil.copytree(languages.FOLDER / "pl", folder)
    texts = (folder / "texts.yaml").read_text(encoding="utf-8")
    texts = re.sub(r"(?m)^SENTENCES_KEY: .*\n", "", texts)
    texts = texts.replace("Pokoje w domu: {areas}", "Místnosti: {mistnosti}")
    (folder / "texts.yaml").write_text(texts, encoding="utf-8")
    found = languages.problems(folder)
    assert "missing: SENTENCES_KEY" in found
    assert "texts.yaml HINT_ROOMS: fields ['mistnosti'], expected ['areas']" in found
    assert any(p.startswith("a prompt does not fill in") for p in found)
    assert cli.main(["languages", "--check", str(folder)]) == 1
    assert "SENTENCES_KEY" in capsys.readouterr().out
    assert cli.main(["languages", "--check", "pl"]) == 0
    assert "complete" in capsys.readouterr().out
    (folder / "words.yaml").write_text("A: [", encoding="utf-8")
    assert languages.problems(folder)[0].startswith("the pack does not load")


def test_a_pack_folder_is_data_and_grammar(tmp_path) -> None:
    folder = tmp_path / "xx"
    shutil.copytree(languages.FOLDER / "pl", folder)
    with (folder / "texts.yaml").open("a", encoding="utf-8") as texts:
        texts.write("\nHINT_ROOMS: ' Místnosti: {areas}.'\nSENTENCES_KEY: vety\n")
    pack = languages.load_pack(folder)
    assert pack.hint_rooms("kuchyň") == " Místnosti: kuchyň."
    assert '{"vety": [...]}' in pack.command_prompt(["x"], 2, "s")


def test_an_unknown_pack_is_refused() -> None:
    with pytest.raises(ValueError, match="no trainer language pack"):
        languages.get("xx")


@needs_router
def test_the_language_of_home_assistant_is_used(tmp_path, integ) -> None:
    from router_trainer.config import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "inputs").mkdir()
    assert context.use_home_language(ws) is False  # nothing fetched yet
    (tmp_path / "inputs" / "ha_export.json").write_text(json.dumps({"language": "pl-PL"}))
    assert context.use_home_language(ws) is True and integ.lang.CODE == "pl"
    (tmp_path / "inputs" / "ha_export.json").write_text(json.dumps({"language": "cs"}))
    assert context.use_home_language(ws) is False  # no pack: the current one stays
    assert integ.lang.CODE == "pl"


def test_the_packs_are_installed_with_the_package() -> None:
    """pip (the Docker image) copies only listed data files - the packs' YAML must be listed."""
    from pathlib import Path
    import tomllib

    data = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text("utf-8"))
    listed = data["tool"]["setuptools"]["package-data"]["router_trainer"]
    assert "languages/*/*.yaml" in listed and "languages/*/grammar.py" in listed
