"""Command line: ``router-trainer <command>`` (the panel runs the same commands as jobs)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import yaml

from . import pipeline
from .config import DEFAULT_WORKSPACE, Workspace, init_workspace, load_settings


def _overrides(values: list[str]) -> dict[str, Any]:
    """``--set lr=0.0002 epochs=2`` -> model setting overrides (YAML values)."""
    out = {}
    for item in values or []:
        key, sep, value = item.partition("=")
        if not sep:
            raise SystemExit(f"--set {item}: use key=value")
        out[key.strip()] = yaml.safe_load(value)
    return out


def job_arguments(raw: list[str]) -> tuple[str, str, list[str]]:
    """``[--kind K] [--title T] [--] command…`` of ``job start`` (argparse's REMAINDER also
    swallows the options, so they are taken off here)."""
    kind, title, rest = "job", "", list(raw)
    while rest[:1] in (["--kind"], ["--title"]) and len(rest) > 1:
        option, value = rest[0], rest[1]
        rest = rest[2:]
        if option == "--kind":
            kind = value
        else:
            title = value
    if rest[:1] == ["--"]:
        rest = rest[1:]
    return kind, title or " ".join(rest), rest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="router-trainer", description=__doc__)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the workspace with trainer.yaml")
    sub.add_parser("snapshot", help="home snapshot from Home Assistant")
    sub.add_parser("freeze", help="freeze the test (sentences never used for training)")
    testgen = sub.add_parser("testgen", help="generate a test from the home and the question log")
    testgen.add_argument("--name", required=True)
    tests = sub.add_parser("tests", help="tests of the workspace; --active NAME picks one (JSON)")
    tests.add_argument("--active")
    review = sub.add_parser("review", help="cases of a test (JSON); --case ID --reject/--keep")
    review.add_argument("--name", required=True)
    review.add_argument("--case")
    review.add_argument("--reject", action="store_true")
    review.add_argument("--keep", action="store_true")
    gen = sub.add_parser("generate", help="generate training data")
    gen.add_argument("--roles", nargs="*", default=["router", "control", "answers"])
    build = sub.add_parser("build", help="build a dataset from the generated data")
    build.add_argument("--dataset", required=True)

    train = sub.add_parser("train", help="train one model on a dataset")
    train.add_argument("--dataset", required=True)
    train.add_argument("--model", required=True)
    train.add_argument("--run", help="run name (default <dataset>-<model>)")
    train.add_argument("--resume", action="store_true")
    train.add_argument("--set", nargs="*", default=[], help="model setting overrides key=value")

    export = sub.add_parser("export", help="GGUF, local check, upload to the home Ollama")
    export.add_argument("--run", required=True)
    export.add_argument("--no-upload", action="store_true")
    evaluate = sub.add_parser("evaluate", help="frozen test: trained model vs base model")
    evaluate.add_argument("--run", required=True)
    evaluate.add_argument("--no-base", action="store_true")

    pipe = sub.add_parser("pipeline", help="several steps as one job")
    pipe.add_argument("--steps", nargs="+", required=True, choices=pipeline.STEPS)
    pipe.add_argument("--dataset", required=True)
    pipe.add_argument("--models", nargs="*", default=[])
    pipe.add_argument("--resume", action="store_true")
    pipe.add_argument("--no-upload", action="store_true")
    pipe.add_argument("--no-base", action="store_true")
    pipe.add_argument("--set", nargs="*", default=[])

    job = sub.add_parser("job", help="background job: start <command…> | stop")
    job.add_argument("action", choices=["start", "stop"])
    job.add_argument("args", nargs=argparse.REMAINDER, help="[--kind K] [--title T] -- command…")

    status = sub.add_parser("status", help="workspace state as JSON (for the panel)")
    status.add_argument("--offset", type=int, default=0, help="log bytes already read")

    tryit = sub.add_parser("try", help="one sentence on several models (JSON)")
    tryit.add_argument("--text", required=True)
    tryit.add_argument("--models", nargs="+", required=True)

    sub.add_parser("fetch", help="inputs from Home Assistant (Assist Router export) into inputs/")
    handoff = sub.add_parser(
        "handoff", help="the teacher by hand: export tasks for any AI chat, import the answers"
    )
    handoff.add_argument("action", choices=["export", "import"])
    handoff.add_argument("role", choices=["writer", "judge"])
    handoff.add_argument("file", nargs="?", help="import: the answers (JSON lines or table)")
    handoff.add_argument("--out", help="export: the folder (default workspace/handoff/…)")
    handoff.add_argument("--per-topic", type=int, help="export writer: sentences per topic")
    lang = sub.add_parser(
        "language", help="a new language: a translated, checked draft of both packs (new | check)"
    )
    lang.add_argument("action", choices=["new", "check"])
    lang.add_argument("code", help="the language code, e.g. cs")
    lang.add_argument("--home", action="store_true", help="use the names of the home in HA")
    lang.add_argument("--answers", help="answers of a manual writer (tasks.jsonl answered)")
    lang.add_argument("--router-repo", help="the Assist Router repository (default: the trainer's)")
    teacher_cmd = sub.add_parser("teacher", help="the teacher of each role: check, API keys")
    teacher_cmd.add_argument("action", choices=["check", "keys"])
    teacher_cmd.add_argument("role", nargs="?", default="writer")
    language = sub.add_parser(
        "languages",
        help="language packs of the trainer; --check CODE|FOLDER lists what a pack lacks",
    )
    language.add_argument("--check", metavar="CODE|FOLDER")
    triggers = sub.add_parser(
        "triggers", help="sentence triggers of the automations with their topics (for overrides)"
    )
    triggers.add_argument("--json", action="store_true", help="JSON instead of a table")
    router = sub.add_parser("router", help="router code of the version HA runs (JSON)")
    router.add_argument("--version", help="another version than the one in Home Assistant")

    auto = sub.add_parser(
        "auto", help="automatic training: from Home Assistant to a compared model, one job"
    )
    auto.add_argument("--dataset", required=True)
    auto.add_argument("--models", nargs="+", required=True)
    auto.add_argument("--test", choices=["ha", "new"], default="ha")
    auto.add_argument("--no-upload", action="store_true")
    auto.add_argument(
        "--roles",
        nargs="+",
        choices=["router", "control", "answers"],
        default=["router", "control", "answers"],
        help="what the model will do (router only: no commands and answers are generated)",
    )
    model = sub.add_parser(
        "router-model", help="Assist Router's router model in Home Assistant (JSON)"
    )
    model.add_argument("--use", help="a model of the home Ollama to use as the router model")
    model.add_argument("--restore", action="store_true", help="the model used before --use")

    smoke = sub.add_parser("smoke", help="quick check of the whole road (own workspace)")
    smoke.add_argument("--model", default="e2b")
    smoke.add_argument(
        "--keep", action="store_true", help="keep the smoke model in the home Ollama"
    )

    studio = sub.add_parser(
        "studio", help="the trainer studio in the browser (login from ROUTER_TRAINER_UI_AUTH)"
    )
    studio.add_argument("--host", default="127.0.0.1")
    studio.add_argument("--port", type=int, default=8790)

    ui = sub.add_parser("ui", help="the same as studio (the old name)")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8790)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ws = Workspace(args.workspace)
    command = args.command
    if command == "init":
        ws = init_workspace(ws.root)
        print(f"workspace {ws.root} - edit {ws.config_file}")
        return 0
    if command == "status":
        from .status import status

        print(json.dumps(status(ws, args.offset), ensure_ascii=False))
        return 0
    if command == "job":
        from .jobs import JobManager

        manager = JobManager(ws.root)
        if args.action == "stop":
            print(json.dumps({"stopped": manager.stop()}))
            return 0
        kind, title, job_args = job_arguments(args.args)
        if not job_args:
            raise SystemExit("job start: give the command after --")
        state = manager.start(kind, title, job_args)
        print(json.dumps(state.as_dict()))
        return 0
    if command == "smoke":
        from . import smoke

        return smoke.run(ws, args.model, args.keep)
    if command == "fetch":
        from . import ha_inputs

        print(json.dumps(ha_inputs.fetch_all(ws), ensure_ascii=False, indent=2))
        return 0
    if command == "router":
        from . import ha_inputs, router_source

        version = args.version or (ha_inputs.last(ws) or {}).get("version")
        if not version:
            raise SystemExit("fetch from Home Assistant first (router-trainer fetch) or --version")
        router_source.fetch(ws.root, version)
        settings = load_settings(ws)
        print(json.dumps(router_source.state(ws.root, settings["router_repo_setting"], version)))
        return 0
    if command == "auto":
        from . import auto

        return auto.run(
            ws, args.dataset, args.models, args.test, not args.no_upload, tuple(args.roles)
        )
    if command == "router-model":
        from . import assist_router_model, ha_client

        client = ha_client.Client(ha_client.load_connection(ws), ws)
        if args.use:
            result = assist_router_model.use(client, ws, args.use)
        elif args.restore:
            result = assist_router_model.restore(client, ws)
        else:
            result = assist_router_model.current(client)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if command == "studio":
        from .studio.server import serve as serve_studio

        serve_studio(ws.root, args.host, args.port)
        return 0
    if command == "ui":  # the old name of the panel: the studio now
        from .studio.server import serve as serve_studio

        serve_studio(ws.root, args.host, args.port)
        return 0
    if command == "try":
        from . import context
        from .try_text import try_text

        print(json.dumps(try_text(context.make(ws), args.text, args.models), ensure_ascii=False))
        return 0
    if command == "testgen":
        return pipeline.run(ws, ["testgen"], pipeline.check_name(args.name, "test"), [])
    if command in ("tests", "review"):
        from .testset import store

        settings = load_settings(ws)
        if command == "tests":
            if args.active:
                store.set_active(ws, args.active)
            print(json.dumps(store.listing(ws, settings), ensure_ascii=False))
            return 0
        try:
            if args.case and (args.reject or args.keep):
                store.set_rejected(ws, args.name, args.case, args.reject)
            cases = store.review_list(ws, settings, args.name)
        except FileNotFoundError:
            # a fresh workspace: no test from Home Assistant fetched yet (or the test was removed)
            print(
                f"error: test '{args.name}' has no file yet - fetch from Home Assistant (step 1) "
                "or generate the test first",
                file=sys.stderr,
            )
            return 1
        print(json.dumps(cases, ensure_ascii=False))
        return 0
    if command == "language":
        from . import language_tool
        from .config import router_repo

        repo = Path(args.router_repo) if args.router_repo else router_repo(load_settings(ws))
        if args.action == "new":
            answers = Path(args.answers) if args.answers else None
            result: Any = language_tool.new(ws, args.code, repo, args.home, answers)
            print(json.dumps(result, ensure_ascii=False, indent=1))
            return 0
        found = language_tool.check(ws, args.code, repo)
        for part, problems in found.items():
            print(f"{part}: " + ("ready" if not problems else f"{len(problems)} problems"))
            for problem in problems:
                print(f"  - {problem}")
        return 1 if any(found.values()) else 0
    if command == "teacher":
        from . import teacher as teacher_module

        if args.action == "keys":
            result: Any = {p: teacher_module.has_key(ws.root, p) for p in teacher_module.KEY_ENV}
        else:
            result = teacher_module.check(load_settings(ws), ws.root, args.role)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if command == "handoff":
        from . import handoff as handoff_module

        ctx = context.make(ws)
        if args.action == "export":
            out = Path(args.out) if args.out else None
            result = handoff_module.export(ctx, args.role, out, args.per_topic)
        else:
            if not args.file:
                raise SystemExit("handoff import: the file with the answers")
            result = handoff_module.import_answers(ctx, args.role, Path(args.file))
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0
    if command == "languages":
        from . import languages

        if args.check:
            folder = Path(args.check)
            folder = folder if folder.is_dir() else languages.FOLDER / args.check
            lacking = languages.problems(folder.resolve())
            print("\n".join(lacking) if lacking else f"{folder.name}: complete")
            return 1 if lacking else 0
        print(" ".join(languages.available()))
        return 0
    if command == "triggers":
        from .generate import router as router_gen

        rows = router_gen.trigger_report(context.make(ws))
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        else:
            for row in rows:
                mark = "" if row["known_topic"] else "  !! not in router.yaml"
                print(f"{row['key']:40} {row['topic'] or '-':20} {row['how']:9} "
                      f"{row['alias'][:40]}{mark}")  # fmt: skip
        return 0
    if command == "snapshot":
        return pipeline.run(ws, ["snapshot"], "none", [])
    if command == "freeze":
        return pipeline.run(ws, ["freeze"], "none", [])
    if command == "generate":
        return pipeline.run(ws, list(args.roles), "none", [])
    if command == "build":
        return pipeline.run(ws, ["build"], args.dataset, [])
    if command == "train":
        name = pipeline.check_name(args.run or pipeline.run_name(args.dataset, args.model), "run")
        pipeline.prepare_run(ws, args.dataset, args.model, name, _overrides(args.set))
        return pipeline.train(ws, name, args.resume)
    if command == "export":
        from . import context, export as export_module

        export_module.export(context.make(ws), args.run, upload=not args.no_upload)
        return 0
    if command == "evaluate":
        from . import context, evaluate as evaluate_module

        evaluate_module.evaluate(context.make(ws), args.run, with_base=not args.no_base)
        return 0
    if command == "pipeline":
        return pipeline.run(
            ws,
            args.steps,
            args.dataset,
            args.models,
            resume=args.resume,
            upload=not args.no_upload,
            with_base=not args.no_base,
            overrides=_overrides(args.set),
        )
    return 2


if __name__ == "__main__":
    sys.exit(main())
