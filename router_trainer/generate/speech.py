"""Router examples through real speech: the errors speech recognition makes, and the home's voices.

Typed noise (lower case, no accents, typos - ``common.noisy``) is not what reaches the router
by voice: Whisper writes whole other words („o kocie” -> „Okoczy”). Two sources bring that in,
both through the same Piper and Whisper Home Assistant uses (Wyoming, on the home server):

- ``asr``: natural training questions read aloud by Piper (all voices of the language, in turn)
  and written back by Whisper. Kept only when Whisper wrote something else - the topic stays the
  one of the original question.
- ``recording``: the home's own voice commands - the WAV files Home Assistant keeps with
  ``assist_pipeline: debug_recording_dir``, copied to ``workspace/inputs/recordings``. Whisper
  writes them, the teacher gives the topic (as for the log), test-like sentences drop out. The
  recordings and their text stay on the machine.

Both are resumable: what Whisper wrote is kept in ``generated/asr.json`` and
``generated/recordings.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
import random
import socket
from typing import Any
from urllib.parse import urlparse
import wave

from ..context import Context
from ..holdout import Holdout, normalize
from ..teacher import PARALLEL
from .common import JsonlWriter, in_parallel, progress, read_jsonl, stage

PIPER_PORT = 10200
WHISPER_PORT = 10300
TIMEOUT = 120
SAVE_EVERY = 20
# the sources whose sentences are natural enough to be read aloud
NATURAL = ("paraphrase", "log", "example", "recording")


# --- Wyoming (the protocol of Piper and Whisper in Home Assistant) ------------------------------


class Wyoming:
    """One connection: events are a JSON line, then optional data and payload bytes."""

    def __init__(self, uri: str) -> None:
        parsed = urlparse(uri)
        self.socket = socket.create_connection((parsed.hostname, parsed.port), timeout=TIMEOUT)
        self.file = self.socket.makefile("rb")

    def __enter__(self) -> Wyoming:
        return self

    def __exit__(self, *_: object) -> None:
        self.file.close()
        self.socket.close()

    def send(self, kind: str, data: dict[str, Any] | None = None, payload: bytes = b"") -> None:
        body = json.dumps(data or {}).encode()
        header = {"type": kind, "data_length": len(body), "payload_length": len(payload)}
        self.socket.sendall(json.dumps(header).encode() + b"\n" + body + payload)

    def receive(self) -> tuple[str, dict[str, Any], bytes]:
        line = self.file.readline()
        if not line:
            raise ConnectionError("the Wyoming server closed the connection")
        header = json.loads(line)
        data = dict(header.get("data") or {})
        if header.get("data_length"):
            data.update(json.loads(self.file.read(header["data_length"])))
        payload = self.file.read(header["payload_length"]) if header.get("payload_length") else b""
        return header["type"], data, payload


def describe(uri: str) -> dict[str, Any]:
    with Wyoming(uri) as connection:
        connection.send("describe")
        while True:
            kind, data, _ = connection.receive()
            if kind == "info":
                return data


def voices(uri: str, language: str) -> list[str]:
    """Names of the installed voices of a language (``pl`` -> pl_PL-…)."""
    found = []
    for program in describe(uri).get("tts") or []:
        for voice in program.get("voices") or []:
            if any(str(lang).startswith(language) for lang in voice.get("languages") or []):
                found.append(voice["name"])
    return sorted(found)


def synthesize(uri: str, text: str, voice: str | None) -> tuple[bytes, int, int, int]:
    """Speech of a text: raw PCM, rate, sample width and channels."""
    with Wyoming(uri) as connection:
        connection.send(
            "synthesize", {"text": text, **({"voice": {"name": voice}} if voice else {})}
        )
        audio, fmt = bytearray(), (22050, 2, 1)
        while True:
            kind, data, payload = connection.receive()
            if kind == "audio-start":
                fmt = (data.get("rate", 22050), data.get("width", 2), data.get("channels", 1))
            elif kind == "audio-chunk":
                audio += payload
            elif kind == "audio-stop":
                return bytes(audio), *fmt
            elif kind == "error":
                raise RuntimeError(f"Piper: {data.get('text') or data}")


def transcribe(uri: str, audio: bytes, rate: int, width: int, channels: int, language: str) -> str:
    """Whisper's text of raw PCM."""
    fmt = {"rate": rate, "width": width, "channels": channels}
    with Wyoming(uri) as connection:
        connection.send("transcribe", {"language": language})
        connection.send("audio-start", fmt)
        step = rate * width * channels  # one second per chunk
        for start in range(0, len(audio), step):
            connection.send("audio-chunk", fmt, audio[start : start + step])
        connection.send("audio-stop")
        while True:
            kind, data, _ = connection.receive()
            if kind == "transcript":
                return " ".join(str(data.get("text") or "").split())
            if kind == "error":
                raise RuntimeError(f"Whisper: {data.get('text') or data}")


def read_wav(path: Path) -> tuple[bytes, int, int, int]:
    with wave.open(str(path), "rb") as audio:
        return (
            audio.readframes(audio.getnframes()),
            audio.getframerate(),
            audio.getsampwidth(),
            audio.getnchannels(),
        )


def endpoints(settings: dict[str, Any]) -> tuple[str, str]:
    """Piper's and Whisper's addresses: from the settings, else the home Ollama's host."""
    speech = settings["generate"]["router"].get("speech") or {}
    host = urlparse(settings["ollama"]["jetson"]).hostname
    piper = speech.get("piper") or f"tcp://{host}:{PIPER_PORT}"
    whisper = speech.get("whisper") or f"tcp://{host}:{WHISPER_PORT}"
    return piper, whisper


def hallucination(pack: Any, text: str) -> bool:
    """What Whisper writes for silence or noise: a known sentence, or a fragment of the video
    subtitles it learnt on („Dzięki za oglądanie!”, „Subtitles by the Amara.org community”)."""
    if normalize(text) in {normalize(t) for t in pack.WHISPER_HALLUCINATIONS}:
        return True
    lower = text.lower()
    return any(part in lower for part in pack.WHISPER_HALLUCINATION_PARTS)


def _load(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _save(path: Path, data: dict[str, str]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")


# --- asr: training questions through Piper and Whisper -------------------------------------------


def asr_noise(ctx: Context, writer: JsonlWriter, holdout: Holdout) -> None:
    settings = ctx.settings["generate"]["router"]
    per_topic = int(settings.get("asr_per_topic") or 0)
    if not per_topic:
        return
    stage("router speech")
    piper, whisper = endpoints(ctx.settings)
    language = ctx.pack.CODE
    names = (settings.get("speech") or {}).get("voices") or voices(piper, language)
    if not names:
        print(f"!! no {language} voices in Piper at {piper} - speech noise skipped", flush=True)
        return
    cache_path = ctx.ws.generated / "asr.json"
    heard = _load(cache_path)
    rng = random.Random(f"{ctx.settings['generate']['seed']}:asr")
    by_topic: dict[str, list[str]] = {}
    for row in read_jsonl(ctx.ws.generated / "router.jsonl"):
        if row.get("source") in NATURAL and row["topic"] in ctx.config.topics:
            by_topic.setdefault(row["topic"], []).append(row["text"])
    jobs = []
    for topic in sorted(by_topic):
        texts = sorted(set(by_topic[topic]))
        rng.shuffle(texts)
        jobs += [(topic, text) for text in texts[:per_topic]]
    voice_of = {text: names[i % len(names)] for i, (_, text) in enumerate(jobs)}

    def listen(text: str) -> str:
        audio = synthesize(piper, text, voice_of[text])
        return transcribe(whisper, *audio, language)

    missing = [text for _, text in jobs if text not in heard]
    for first in range(0, len(missing), SAVE_EVERY):
        part = missing[first : first + SAVE_EVERY]
        for text, result in zip(part, in_parallel(listen, part, PARALLEL), strict=True):
            heard[text] = result
        _save(cache_path, heard)
        progress("router", "speech", len(jobs) - len(missing) + first + len(part), len(jobs))
    changed = 0
    for topic, text in jobs:
        result = heard.get(text, "")
        if not normalize(result) or normalize(result) == normalize(text):
            continue  # Whisper got it right - nothing new for the router
        if holdout.match(result):
            continue
        changed += 1
        writer.write(
            {
                "role": "router",
                "part": f"asr:{topic}",
                "text": result,
                "topic": topic,
                "source": "asr",
                "spoken": text,
            }
        )
    print(f"speech: {len(jobs)} questions read aloud, {changed} written differently", flush=True)


# --- recording: the home's own voice commands ----------------------------------------------------


def recordings(ctx: Context, writer: JsonlWriter, holdout: Holdout) -> None:
    settings = ctx.settings["generate"]["router"]
    folder = ctx.ws.root / "inputs" / "recordings"
    if not settings.get("recordings") or not folder.is_dir():
        return
    stage("router recordings")
    _, whisper = endpoints(ctx.settings)
    language = ctx.pack.CODE
    files = sorted(p for p in folder.rglob("*.wav") if p.is_file())
    cache_path = ctx.ws.generated / "recordings.json"
    heard = _load(cache_path)
    missing = [p for p in files if str(p.relative_to(folder)) not in heard]

    def listen(path: Path) -> str:
        try:
            return transcribe(whisper, *read_wav(path), language)
        except (wave.Error, EOFError):
            return ""  # a broken file - nothing to hear

    for first in range(0, len(missing), SAVE_EVERY):
        part = missing[first : first + SAVE_EVERY]
        for path, text in zip(part, in_parallel(listen, part, PARALLEL), strict=True):
            heard[str(path.relative_to(folder))] = text
        _save(cache_path, heard)
        progress("router", "recordings", len(files) - len(missing) + first + len(part), len(files))
    texts = list(dict.fromkeys(t for t in heard.values() if t and not hallucination(ctx.pack, t)))
    kept, test_like = holdout.split(texts)
    print(
        f"recordings: {len(files)} files, {len(texts)} distinct sentences, "
        f"{len(test_like)} like a test question",
        flush=True,
    )
    from .labels import Checker

    checker = Checker(ctx)  # the judge's topics, kept in generated/labels.json
    todo = [t for t in kept if ("recording", normalize(t)) not in writer.seen]
    for first in range(0, len(todo), SAVE_EVERY):
        part = todo[first : first + SAVE_EVERY]
        checker.ask(part)
        for text in part:
            topic = checker.topic(text)
            if topic in ctx.config.topics:
                writer.write(
                    {
                        "role": "router",
                        "part": "recording",
                        "text": text,
                        "topic": topic,
                        "source": "recording",
                    }
                )
        progress("router", "recording", writer.count("recording"), len(kept), len(test_like))
