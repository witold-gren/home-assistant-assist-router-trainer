"""Router examples through real speech: a pretend Piper and Whisper speak the Wyoming protocol."""

from __future__ import annotations

import json
import socketserver
import threading
import wave

import pytest

from router_trainer.generate import router, speech
from router_trainer.generate.common import read_jsonl
from tests.conftest import needs_router
from tests.test_generate import FakeTeacher

pytestmark = needs_router

# what the pretend Whisper "hears": the audio is the text itself, with a few words misheard
MISHEARD = {"o kocie": "Okoczy", "parasol": "para sol"}
VOICES = ["pl_PL-gosia-medium", "pl_PL-jarvis-medium", "en_US-amy-low"]


def _send(handler, kind: str, data: dict | None = None, payload: bytes = b"") -> None:
    body = json.dumps(data or {}).encode()
    header = {"type": kind, "data_length": len(body), "payload_length": len(payload)}
    handler.wfile.write(json.dumps(header).encode() + b"\n" + body + payload)


class Wyoming(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        audio = bytearray()
        while line := self.rfile.readline():
            header = json.loads(line)
            data = json.loads(self.rfile.read(header.get("data_length", 0)) or b"{}")
            payload = self.rfile.read(header.get("payload_length", 0))
            kind = header["type"]
            if kind == "describe":
                voices = [{"name": v, "languages": [v[:5]]} for v in VOICES]
                _send(self, "info", {"tts": [{"name": "piper", "voices": voices}]})
            elif kind == "synthesize":
                self.server.voices.append((data.get("voice") or {}).get("name"))
                _send(self, "audio-start", {"rate": 16000, "width": 2, "channels": 1})
                _send(self, "audio-chunk", {"rate": 16000}, data["text"].encode())
                _send(self, "audio-stop")
                return
            elif kind == "audio-chunk":
                audio += payload
            elif kind == "audio-stop":
                text = audio.decode("utf-8", "replace")
                for heard, written in MISHEARD.items():
                    text = text.replace(heard, written)
                _send(self, "transcript", {"text": f" {text} "})
                return


@pytest.fixture
def server():
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Wyoming)
    srv.voices = []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, f"tcp://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def test_the_protocol_speaks_and_hears(server) -> None:
    srv, uri = server
    assert speech.voices(uri, "pl") == ["pl_PL-gosia-medium", "pl_PL-jarvis-medium"]
    audio = speech.synthesize(uri, "Opowiedz o kocie", "pl_PL-gosia-medium")
    assert audio[1:] == (16000, 2, 1) and srv.voices == ["pl_PL-gosia-medium"]
    assert speech.transcribe(uri, *audio, "pl") == "Opowiedz Okoczy"


def test_the_home_server_is_found_from_the_ollama_address(ctx) -> None:
    ctx.settings["ollama"]["jetson"] = "http://home.local:11434"
    assert speech.endpoints(ctx.settings) == ("tcp://home.local:10200", "tcp://home.local:10300")
    ctx.settings["generate"]["router"]["speech"]["whisper"] = "tcp://other:10301"
    assert speech.endpoints(ctx.settings)[1] == "tcp://other:10301"


def _speech_to(ctx, uri) -> None:
    ctx.settings["generate"]["router"]["speech"] = {"piper": uri, "whisper": uri, "voices": []}


def test_misheard_questions_keep_their_topic(ctx, server) -> None:
    srv, uri = server
    _speech_to(ctx, uri)
    ctx.settings["generate"]["router"]["asr_per_topic"] = 5
    out = ctx.ws.generated / "router.jsonl"
    rows = [
        ("Opowiedz historię o kocie", "inne", "paraphrase"),
        ("Czy wziąć parasol?", "inne", "log"),
        ("Jaka jest pogoda?", "inne", "paraphrase"),  # heard right - nothing new
        ("Zapal światło o kocie", "sterowanie", "trigger"),  # templates are not read aloud
    ]
    with router.JsonlWriter(out) as writer:
        for text, topic, source in rows:
            writer.write({"role": "router", "part": source, "text": text, "topic": topic,
                          "source": source})  # fmt: skip
        speech.asr_noise(ctx, writer, ctx.holdout())
    heard = {r["text"]: (r["topic"], r["spoken"]) for r in read_jsonl(out) if r["source"] == "asr"}
    assert heard == {
        "Opowiedz historię Okoczy": ("inne", "Opowiedz historię o kocie"),
        "Czy wziąć para sol?": ("inne", "Czy wziąć parasol?"),
    }
    assert set(srv.voices) == {"pl_PL-gosia-medium", "pl_PL-jarvis-medium"}  # voices in turn
    # resumed: what Whisper wrote is kept, nothing is read aloud again
    srv.voices.clear()
    with router.JsonlWriter(out) as writer:
        speech.asr_noise(ctx, writer, ctx.holdout())
    assert srv.voices == []


def _wav(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        data = text.encode()
        audio.writeframes(data + b" " * (len(data) % 2))  # whole 16-bit frames


def test_the_homes_recordings_become_labelled_questions(ctx, server) -> None:
    _, uri = server
    _speech_to(ctx, uri)
    folder = ctx.ws.root / "inputs" / "recordings"
    _wav(folder / "Salon OK Nabu" / "1" / "01_stt.wav", "Włącz telewizor w salonie")
    _wav(folder / "Kuchnia OK Nabu" / "2" / "01_stt.wav", "Ile waży słoń?")
    _wav(folder / "Kuchnia OK Nabu" / "3" / "01_stt.wav", "Ile waży słoń?")  # the same twice
    _wav(folder / "Salon OK Nabu" / "4" / "01_stt.wav", "Dziękuję.")  # Whisper on silence
    _wav(folder / "Salon OK Nabu" / "5" / "01_stt.wav", "Włącz światło w kuchni")  # in the test
    (folder / "broken.wav").write_bytes(b"not a wav")
    ctx.teacher_obj = FakeTeacher()
    out = ctx.ws.generated / "router.jsonl"
    with router.JsonlWriter(out) as writer:
        speech.recordings(ctx, writer, ctx.holdout())
    rows = {r["text"]: r["topic"] for r in read_jsonl(out) if r["source"] == "recording"}
    assert rows == {"Włącz telewizor w salonie": "sterowanie", "Ile waży słoń?": "inne"}
    heard = json.loads((ctx.ws.generated / "recordings.json").read_text(encoding="utf-8"))
    assert len(heard) == 6 and heard["broken.wav"] == ""
    ctx.settings["generate"]["router"]["recordings"] = False
    with router.JsonlWriter(out) as writer:
        speech.recordings(ctx, writer, ctx.holdout())  # switched off: nothing happens


def test_whisper_noise_is_recognised(ctx) -> None:
    for text in (
        "Dziękuję.",
        "Dzięki za oglądanie!",
        "Subtitles by the Amara.org community",
        "Nie zapomnijcie zasubskrybować oraz zafollowować mnie na Facebooku!",
    ):
        assert speech.hallucination(ctx.pack, text), text
    for text in ("Dziękuję, włącz światło.", "Jakie lekcje ma jutro Ola?", "Cześć!"):
        assert not speech.hallucination(ctx.pack, text), text


def test_without_the_home_server_the_speech_sources_are_skipped(ctx, capsys) -> None:
    _speech_to(ctx, "tcp://127.0.0.1:9")  # nothing listens there
    ctx.settings["generate"]["router"]["asr_per_topic"] = 5
    out = ctx.ws.generated / "router.jsonl"
    with router.JsonlWriter(out) as writer:
        writer.write({"role": "router", "part": "paraphrase", "text": "Opowiedz o kocie",
                      "topic": "inne", "source": "paraphrase"})  # fmt: skip
        with pytest.raises(OSError):
            speech.asr_noise(ctx, writer, ctx.holdout())
