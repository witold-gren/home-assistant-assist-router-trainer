"""The frozen test: no training sentence equal or nearly equal to a test sentence."""

from __future__ import annotations

from router_trainer import holdout
from tests.conftest import TESTS


def test_normalize_drops_case_accents_and_punctuation() -> None:
    assert holdout.normalize("  Włącz ŚWIATŁO, w kuchni! ") == "wlacz swiatlo w kuchni"


def test_test_sentences_cover_every_section() -> None:
    sentences = holdout.test_sentences(TESTS)
    assert "Włącz światło w kuchni" in sentences  # router
    assert "Zgaś lampkę w salonie" in sentences  # control
    assert "Ile pieniędzy ma Kuba?" in sentences  # given data
    assert "Co jest w piątek?" in sentences  # HA data
    assert "Kim był Kopernik?" in sentences  # Wikipedia question
    assert "Mikołaj Kopernik" in sentences  # Wikipedia phrase


def test_exact_after_normalization_is_dropped() -> None:
    frozen = holdout.Holdout(holdout.test_sentences(TESTS))
    assert frozen.match("wlacz swiatlo w kuchni") == "Włącz światło w kuchni"


def test_near_duplicates_are_dropped() -> None:
    frozen = holdout.Holdout(["Czy Kuba ma w tym tygodniu sprawdzian z matematyki?"])
    # one word inflected differently: same stems
    assert frozen.match("Czy Kuba ma w tym tygodniu sprawdziany z matematyki")
    # a typo: close by character trigrams
    assert frozen.match("Czy Kuba ma w tym tygodniu sprawdzian z matematyy?")


def test_different_sentences_are_kept() -> None:
    frozen = holdout.Holdout(["Włącz światło w kuchni"])
    assert frozen.match("Zapal lampkę przy kanapie w salonie") is None
    assert frozen.match("Jaka będzie jutro pogoda?") is None
    assert frozen.match("") is None


def test_split_lists_what_was_dropped() -> None:
    frozen = holdout.Holdout(["Włącz światło w kuchni"])
    kept, rejected = frozen.split(["włącz światło w kuchni", "Kim był Chopin?"])
    assert kept == ["Kim był Chopin?"]
    assert rejected == [("włącz światło w kuchni", "Włącz światło w kuchni")]


def test_freeze_and_load(tmp_path) -> None:
    settings = {"holdout": {"word_similarity": 0.7, "char_similarity": 0.9}}
    out = tmp_path / "holdout" / "holdout.json"
    frozen = holdout.freeze(TESTS, settings, out)
    loaded = holdout.load(out)
    assert loaded.sentences == frozen.sentences
    assert loaded.word_similarity == 0.7
    assert loaded.match("Co Ola ma jutro") == "Co Ola ma jutro?"


def test_load_without_freeze_says_what_to_do(tmp_path) -> None:
    try:
        holdout.load(tmp_path / "missing.json")
    except FileNotFoundError as err:
        assert "freeze" in str(err)
    else:
        raise AssertionError("expected FileNotFoundError")
