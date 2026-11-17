"""Trained model -> Ollama: GGUF on the GPU box, a quick local check, upload to the home Ollama.

1. The merged weights are converted to GGUF with llama.cpp's converter (tools/llama.cpp,
   run in .venv-train). Ollama's own safetensors import needs MLX; GGUF works everywhere.
2. The trainer's Ollama creates the model with Gemma 4's renderer and parser and answers a few
   dev questions (never test questions).
3. The same GGUF goes to the home Ollama (the client uploads the file; nothing is converted
   there) as ``<export.name>:<run>``, after checking that it fits next to the loaded models.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from .config import TOOLS, TRAIN_PYTHON, ollama_name
from .context import Context
from .generate.common import read_jsonl, stage
from .teacher import OLLAMA_DIR, http, local_url, ollama_env, start_local

MODELFILE_HEADER = "RENDERER gemma4\nPARSER gemma4\nPARAMETER temperature 0\n"
JETSON_MEMORY_GB = 64
JETSON_RESERVE_GB = 12  # Frigate, Speaker ID, Piper … next to Ollama


def run_params(run: Path) -> dict[str, Any]:
    return json.loads((run / "params.json").read_text(encoding="utf-8"))


def convert(run: Path, quantization: str) -> Path:
    merged = run / "merged"
    if not merged.exists():
        raise FileNotFoundError(f"{merged} missing - train the model first")
    target = run / "gguf" / f"model-{quantization}.gguf"
    if target.exists() and target.stat().st_mtime > merged.stat().st_mtime:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    converter = TOOLS / "llama.cpp" / "convert_hf_to_gguf.py"
    python = TRAIN_PYTHON if TRAIN_PYTHON.exists() else Path(sys.executable)
    stage(f"gguf ({quantization})")
    subprocess.run(
        [
            str(python),
            str(converter),
            str(merged),
            "--outtype",
            quantization,
            "--outfile",
            str(target),
        ],
        check=True,
    )
    return target


def create(host: str, name: str, modelfile: Path, models_dir: Path) -> None:
    binary = OLLAMA_DIR / "bin" / "ollama"
    print(f"$ ollama create {name} (OLLAMA_HOST={host})", flush=True)
    subprocess.run(
        [str(binary), "create", name, "-f", str(modelfile)],
        env=ollama_env(host, models_dir),
        check=True,
    )


def fits(url: str, size_gb: float) -> tuple[bool, str]:
    """Will a model of ``size_gb`` fit next to the models loaded in the home Ollama?"""
    loaded = http(url, "/api/ps", timeout=10).get("models", [])
    used = sum(m.get("size", 0) for m in loaded) / 1e9
    names = ", ".join(f"{m['name']} {m.get('size', 0) / 1e9:.1f} GB" for m in loaded) or "none"
    free = JETSON_MEMORY_GB - JETSON_RESERVE_GB - used
    return size_gb * 1.3 < free, f"loaded: {names}; about {free:.0f} GB left for the test"


def smoke_questions(ctx: Context, dataset: Path) -> list[dict[str, Any]]:
    """A few dev chats (router and control) - never test questions."""
    rows = list(read_jsonl(dataset / "dev.jsonl"))
    router = [r for r in rows if r["role"] == "router"][:3]
    control = [r for r in rows if r["role"] == "control"][:2]
    return router + control


def export(ctx: Context, run_name: str, upload: bool = True) -> str:
    run = ctx.ws.run(run_name)
    params = run_params(run)
    name = ollama_name(ctx.settings, params["model_key"], run_name)
    gguf = convert(run, ctx.settings["export"]["quantization"])
    modelfile = run / "Modelfile"
    modelfile.write_text(f"FROM {gguf}\n{MODELFILE_HEADER}", encoding="utf-8")
    models_dir = ctx.ws.root / "ollama-models"

    stage("local check")
    url = start_local(ctx.settings, ctx.ws.root)
    port = ctx.settings["ollama"]["local_port"]
    create(f"127.0.0.1:{port}", name, modelfile, models_dir)
    home_data = ctx.home_data()
    for row in smoke_questions(ctx, Path(params["dataset"])):
        schema = (
            ctx.integ.router_schema(ctx.config)
            if row["role"] == "router"
            else ctx.integ.control_schema(home_data)
        )
        started = time.time()
        reply = http(
            local_url(ctx.settings),
            "/api/chat",
            {
                "model": name,
                "stream": False,
                "think": False,
                "format": schema,
                "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 160},
                "messages": row["messages"][:-1],
            },
        )
        got = " ".join(reply["message"]["content"].split())
        expected = row["messages"][-1]["content"]
        mark = "OK" if json.loads(got) == json.loads(expected) else "--"
        print(f"  {mark} [{time.time() - started:4.1f}s] {row['text']} -> {got}", flush=True)
    http(url, "/api/generate", {"model": name, "keep_alive": 0}, timeout=60)

    if upload:
        stage("upload")
        jetson = ctx.settings["ollama"]["jetson"]
        ok, note = fits(jetson, gguf.stat().st_size / 1e9)
        print(f"home Ollama: {note}", flush=True)
        if not ok:
            print(
                "!! the model may not fit in memory during the test - unload big models first "
                "(evaluate.unload_first in trainer.yaml)",
                flush=True,
            )
        create(jetson.removeprefix("http://"), name, modelfile, models_dir)
    (run / "export.json").write_text(
        json.dumps({"name": name, "gguf": str(gguf), "uploaded": upload}, indent=1),
        encoding="utf-8",
    )
    print(f"== model {name} ready", flush=True)
    return name
