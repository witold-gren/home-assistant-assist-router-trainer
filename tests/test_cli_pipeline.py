"""Command line, runs, training helpers and the test comparison."""

from __future__ import annotations

import json

import pytest

from router_trainer import cli, evaluate, pipeline, train
from router_trainer.config import init_workspace
from tests.conftest import needs_router


def test_overrides_parse_yaml_values() -> None:
    assert cli._overrides(["epochs=2", "learning_rate=0.0002", "load_in_4bit=false"]) == {
        "epochs": 2, "learning_rate": 0.0002, "load_in_4bit": False,
    }  # fmt: skip
    with pytest.raises(SystemExit):
        cli._overrides(["epochs"])


def test_init_and_status(tmp_path, capsys) -> None:
    assert cli.main(["--workspace", str(tmp_path / "ws"), "init"]) == 0
    assert (tmp_path / "ws" / "trainer.yaml").exists()
    capsys.readouterr()
    assert cli.main(["--workspace", str(tmp_path / "ws"), "status"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["models"] == ["e4b", "e2b"] and data["job"] is None


def test_names_are_checked(tmp_path) -> None:
    assert pipeline.check_name("oct27-e4b", "run") == "oct27-e4b"
    for bad in ("", "Oct", "a/b", "../x", "a" * 50):
        with pytest.raises(ValueError):
            pipeline.check_name(bad, "run")
    with pytest.raises(ValueError, match="unknown steps"):
        pipeline.run(init_workspace(tmp_path / "ws"), ["fly"], "x", [])


def test_prepare_run_keeps_params_and_applies_overrides(tmp_path) -> None:
    ws = init_workspace(tmp_path / "ws")
    with pytest.raises(FileNotFoundError):
        pipeline.prepare_run(ws, "oct27", "e2b", "oct27-e2b")
    (ws.dataset("oct27")).mkdir(parents=True)
    (ws.dataset("oct27") / "train.jsonl").write_text("")
    folder = pipeline.prepare_run(ws, "oct27", "e2b", "oct27-e2b", {"epochs": 2})
    params = json.loads((folder / "params.json").read_text())
    assert params["model"]["epochs"] == 2 and params["model"]["base"] == "unsloth/gemma-4-E2B-it"
    params["marker"] = 1
    (folder / "params.json").write_text(json.dumps(params))
    pipeline.prepare_run(ws, "oct27", "e2b", "oct27-e2b")  # Resume: params kept
    assert json.loads((folder / "params.json").read_text())["marker"] == 1


def test_last_checkpoint(tmp_path) -> None:
    for step in (90, 1000, 200):
        (tmp_path / f"checkpoint-{step}").mkdir()
    assert train.last_checkpoint(tmp_path).name == "checkpoint-1000"
    assert train.last_checkpoint(tmp_path / "none") is None


class GemmaLikeTokenizer:
    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=False):
        text = "<bos>" + "".join(f"<|turn>{m['role']}\n{m['content']}<turn|>\n" for m in messages)
        return text + ("<|turn>model\n" if add_generation_prompt else "")


def test_turn_markers() -> None:
    assert train.turn_markers(GemmaLikeTokenizer()) == ("<|turn>user\n", "<|turn>model\n")


def test_compare_lists_fixed_and_broken_cases() -> None:
    results = {
        "ft": {"router": {"score": 2, "total": 3, "avg_s": 0.5, "errors": ["c -> x (expected y)"]},
               "control": {"score": 1, "total": 1, "avg_s": 2, "details": [{"case": "a", "problems": []}]}},
        "base": {"router": {"score": 1, "total": 3, "avg_s": 0.6,
                            "errors": ["a -> x (expected y)", "b -> z (expected y)"]},
                 "control": {"score": 0, "total": 1, "avg_s": 3, "details": [{"case": "a", "problems": ["x"]}]}},
    }  # fmt: skip
    report = evaluate.compare(results, "ft", "base")
    router = report["parts"]["router"]
    assert (router["trained"], router["base"]) == (2, 1)
    assert router["fixed"] == ["a", "b"] and router["broken"] == ["c"]
    assert report["parts"]["control"]["fixed"] == ["a"]
    assert "answers" not in report["parts"]


@needs_router
def test_eval_cases_use_the_integrations_household(ctx) -> None:
    run = ctx.ws.run("r")
    run.mkdir(parents=True)
    import yaml

    cases = yaml.safe_load(evaluate.eval_cases(ctx, run).read_text())
    assert cases["control"]["household"] == ctx.config.household
    assert ctx.tests()["control"]["household"] == "inny opis domu"  # the test file is unchanged


def test_job_arguments_take_the_options_off() -> None:
    raw = ["--kind", "train", "--title", "train e4b", "--", "pipeline", "--steps", "train"]
    assert cli.job_arguments(raw) == ("train", "train e4b", ["pipeline", "--steps", "train"])
    assert cli.job_arguments(["--", "export", "--run", "x"]) == (
        "job",
        "export --run x",
        ["export", "--run", "x"],
    )


def test_job_start_command_matches_the_cli(tmp_path) -> None:
    from router_trainer.ui.backend import LocalBackend

    backend = LocalBackend(init_workspace(tmp_path / "ws"))
    command = backend.cli("job", "start", "--kind", "data", "--title", "data x", "--", "freeze")
    words = command[command.index("router_trainer.cli") + 1 :]
    parsed = cli.build_parser().parse_args(words)
    assert cli.job_arguments(parsed.args) == ("data", "data x", ["freeze"])


def test_supported_drops_unknown_options(capsys) -> None:
    class Config:
        def __init__(self, learning_rate=0.1, warmup_steps=0):
            pass

    assert train.supported(Config, {"learning_rate": 1, "warmup_ratio": 0.03}) == {
        "learning_rate": 1
    }
    assert "warmup_ratio" in capsys.readouterr().out


def test_smoke_workspace_is_small_and_separate(tmp_path) -> None:
    import yaml

    from router_trainer import smoke

    ws = init_workspace(tmp_path / "workspace")
    (ws.root / "inputs").mkdir()
    (ws.root / "inputs" / "model_test.yaml").write_text("router: []\n")
    (ws.root / "ha_token").write_text("t")
    (ws.root / "ollama-models" / "blobs").mkdir(parents=True)
    (ws.root / "ollama-models" / "blobs" / "b").write_text("x")
    copy = smoke.prepare(ws)
    assert copy.root.name == "workspace-smoke"
    settings = yaml.safe_load(copy.config_file.read_text())
    assert settings["generate"]["control"]["labels"] == 6
    assert settings["test"]["control"] == 4  # a small generated test
    assert (copy.root / "ha_token").read_text() == "t"
    blob = copy.root / "ollama-models" / "blobs" / "b"
    assert (
        blob.stat().st_ino == (ws.root / "ollama-models" / "blobs" / "b").stat().st_ino
    )  # a hard link
    assert not (ws.root / "tests").exists()  # the real workspace is untouched


def test_smoke_runs_every_step_with_a_generated_test(tmp_path, monkeypatch) -> None:
    from router_trainer import smoke

    calls = []
    monkeypatch.setattr(smoke.pipeline, "run", lambda ws, steps, *a, **k: calls.append(steps) or 1)
    assert smoke.run(init_workspace(tmp_path / "workspace")) == 1
    assert calls[0][0] == "testgen" and calls[0][-1] == "evaluate"
