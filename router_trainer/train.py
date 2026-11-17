"""Fine-tune one model with LoRA / QLoRA (Unsloth + TRL) on a dataset from ``build``.

Runs in the training environment (.venv-train, scripts/setup.sh): it only reads the chats
of the dataset, so it needs neither Home Assistant nor the integration. The loss is computed
on the model's answers only. Metrics go to the log as ``@@metric {...}`` lines (the panel
draws them). Stop (Ctrl+C / SIGINT) saves a checkpoint at the current step and ends with
code 130; ``--resume`` continues from the last checkpoint.

    .venv-train/bin/python -m router_trainer.train --run workspace/runs/<name>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import signal
import sys
import time
from typing import Any

METRIC = "@@metric"
INFO = "@@info"
STOPPED = 130
DEV_LIMIT = 300  # dev examples evaluated (eval loss)


def emit(tag: str, data: dict[str, Any]) -> None:
    print(f"{tag} {json.dumps(data, ensure_ascii=False)}", flush=True)


def read_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def turn_markers(tokenizer: Any) -> tuple[str, str]:
    """Start of the user and of the model turn in the chat template (Gemma 4:
    ``<|turn>user`` / ``<|turn>model``), found by rendering a probe message."""
    messages = [{"role": "user", "content": "@@@"}]
    with_prompt = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    without = tokenizer.apply_chat_template(messages, tokenize=False)
    response_part = with_prompt[len(without) :] if with_prompt.startswith(without) else None
    before_user = without.split("@@@")[0]
    instruction_part = before_user.split("\n")[-2] + "\n" if "\n" in before_user else before_user
    if not response_part:
        raise SystemExit("chat template turn markers not found")
    return instruction_part.removeprefix("<bos>"), response_part


def last_checkpoint(folder: Path) -> Path | None:
    checkpoints = sorted(
        (p for p in folder.glob("checkpoint-*") if p.is_dir()),
        key=lambda p: int(p.name.split("-")[-1]),
    )
    return checkpoints[-1] if checkpoints else None


def supported(cls: Any, options: dict[str, Any]) -> dict[str, Any]:
    """Only the options this TRL / Transformers version knows (names change between versions);
    the others are reported in the log instead of failing the training."""
    import inspect

    known = inspect.signature(cls.__init__).parameters
    unknown = sorted(set(options) - set(known))
    if unknown:
        print(f"!! {cls.__name__} does not know {', '.join(unknown)} - skipped", flush=True)
    return {k: v for k, v in options.items() if k in known}


def check_gpu_free(min_gb: float) -> None:
    import torch

    if not torch.cuda.is_available():
        raise SystemExit("no CUDA GPU - training needs an NVIDIA card")
    free, total = torch.cuda.mem_get_info()
    if free / 1e9 < min_gb:
        raise SystemExit(
            f"only {free / 1e9:.1f} of {total / 1e9:.1f} GB free on the GPU - unload other "
            "models (the teacher in the trainer's Ollama is unloaded by `router-trainer train`)"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Fine-tune one model (Unsloth)")
    parser.add_argument("--run", type=Path, required=True, help="run folder with params.json")
    parser.add_argument("--resume", action="store_true", help="continue from the last checkpoint")
    args = parser.parse_args()
    run: Path = args.run.resolve()
    params = json.loads((run / "params.json").read_text(encoding="utf-8"))
    model_cfg = params["model"]
    check_gpu_free(float(params.get("min_free_gb", 14)))

    # Unsloth before transformers / trl (it patches them)
    from datasets import Dataset
    from transformers import TrainerCallback
    from trl import SFTConfig, SFTTrainer
    from unsloth import FastModel
    from unsloth.chat_templates import train_on_responses_only

    stop_requested = {"value": False}

    def on_signal(signum: int, frame: Any) -> None:
        stop_requested["value"] = True
        print("== stop requested: saving a checkpoint at this step", flush=True)

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    max_len = int(model_cfg["max_seq_length"])
    model, tokenizer = FastModel.from_pretrained(
        model_cfg["base"],
        max_seq_length=max_len,
        load_in_4bit=bool(model_cfg.get("load_in_4bit", False)),
        full_finetuning=False,
    )
    model = FastModel.get_peft_model(
        model,
        finetune_vision_layers=False,
        finetune_language_layers=True,
        finetune_attention_modules=True,
        finetune_mlp_modules=True,
        r=int(model_cfg["lora_r"]),
        lora_alpha=int(model_cfg["lora_alpha"]),
        lora_dropout=0,
        bias="none",
        random_state=int(params.get("seed", 42)),
    )
    # Gemma 4 is multimodal: FastModel returns a processor, its tokenizer counts text
    text_tokenizer = getattr(tokenizer, "tokenizer", tokenizer)

    def render(rows: list[dict[str, Any]]) -> tuple[Dataset, int]:
        texts, skipped = [], 0
        for row in rows:
            text = tokenizer.apply_chat_template(row["messages"], tokenize=False)
            text = text.removeprefix("<bos>")  # the tokenizer adds BOS itself
            if len(text_tokenizer(text)["input_ids"]) > max_len:
                skipped += 1
                continue
            texts.append(text)
        return Dataset.from_dict({"text": texts}), skipped

    dataset = Path(params["dataset"])
    train, skipped_train = render(read_rows(dataset / "train.jsonl"))
    dev, skipped_dev = render(read_rows(dataset / "dev.jsonl")[:DEV_LIMIT])
    emit(
        INFO,
        {
            "train": len(train),
            "dev": len(dev),
            "skipped_too_long": skipped_train + skipped_dev,
            "base": model_cfg["base"],
            "max_seq_length": max_len,
        },
    )

    class Metrics(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kwargs):
            data = {
                "step": state.global_step,
                "max_steps": state.max_steps,
                "epoch": round(state.epoch or 0, 3),
            }
            for key in ("loss", "eval_loss", "learning_rate", "grad_norm"):
                if logs and key in logs:
                    data[key] = logs[key]
            if len(data) > 3:
                emit(METRIC, data)

        def on_step_end(self, args, state, control, **kwargs):
            if stop_requested["value"]:
                control.should_save = True
                control.should_training_stop = True
            return control

    checkpoints = run / "checkpoints"
    steps_per_epoch = -(
        -len(train) // (int(model_cfg["batch_size"]) * int(model_cfg["grad_accum"]))
    )
    total_steps = max(1, int(steps_per_epoch * float(model_cfg["epochs"])))
    options = {
        "dataset_text_field": "text",
        "max_length": max_len,
        "per_device_train_batch_size": int(model_cfg["batch_size"]),
        "gradient_accumulation_steps": int(model_cfg["grad_accum"]),
        "num_train_epochs": float(model_cfg["epochs"]),
        "learning_rate": float(model_cfg["learning_rate"]),
        "warmup_steps": max(1, round(total_steps * 0.03)),  # 3 % of the steps
        "lr_scheduler_type": "cosine",
        "logging_steps": 10,
        "eval_strategy": "steps",
        "eval_steps": int(params.get("eval_steps", 100)),
        "save_strategy": "steps",
        "save_steps": int(params.get("save_steps", 100)),
        "save_total_limit": 2,
        "bf16": True,
        "optim": "adamw_8bit",
        "seed": int(params.get("seed", 42)),
        "output_dir": str(checkpoints),
        "report_to": "none",
    }
    config = SFTConfig(**supported(SFTConfig, options))
    trainer_args = {
        "model": model,
        "train_dataset": train,
        "eval_dataset": dev,
        "args": config,
        "callbacks": [Metrics()],
    }
    try:
        trainer = SFTTrainer(processing_class=tokenizer, **trainer_args)
    except TypeError:  # older TRL
        trainer = SFTTrainer(tokenizer=tokenizer, **trainer_args)
    instruction_part, response_part = turn_markers(tokenizer)
    trainer = train_on_responses_only(
        trainer, instruction_part=instruction_part, response_part=response_part
    )

    resume = last_checkpoint(checkpoints) if args.resume else None
    if resume:
        print(f"== resuming from {resume.name}", flush=True)
    started = time.time()
    stats = trainer.train(resume_from_checkpoint=str(resume) if resume else None)
    minutes = (time.time() - started) / 60
    if stop_requested["value"]:
        print(
            f"== stopped at step {trainer.state.global_step} - Resume continues from here",
            flush=True,
        )
        sys.exit(STOPPED)

    print("== saving the LoRA adapter and the merged model", flush=True)
    model.save_pretrained(str(run / "lora"))
    tokenizer.save_pretrained(str(run / "lora"))
    model.save_pretrained_merged(str(run / "merged"), tokenizer, save_method="merged_16bit")
    info = {
        "base": model_cfg["base"],
        "dataset": str(dataset),
        "examples": len(train),
        "skipped_too_long": skipped_train,
        "minutes": round(minutes, 1),
        "loss": stats.training_loss,
        "steps": trainer.state.global_step,
        "model": model_cfg,
        "finished": time.strftime("%Y-%m-%d %H:%M"),
    }
    (run / "train_info.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    emit(INFO, {"done": True, "minutes": info["minutes"], "loss": info["loss"]})
    print(f"== training done in {minutes:.1f} min, loss {stats.training_loss:.4f}", flush=True)


if __name__ == "__main__":
    main()
