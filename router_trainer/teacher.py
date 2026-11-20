"""The teacher: a big model in the trainer's own Ollama on the GPU box (default Gemma 4 26B).

It writes paraphrases, plans of commands and reference answers. It runs on the training
machine (tools/ollama, own model folder, own port), so the home Ollama is not loaded; before
training it is unloaded to free the graphics card.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any
import urllib.error
import urllib.request

from .config import TOOLS

OLLAMA_DIR = TOOLS / "ollama"
RETRIES = 2
# One context for every call: Ollama reloads the model whenever num_ctx changes, and the
# generators alternate between writing (short prompts) and checking (the long control and
# router prompts) - with two sizes every label paid two reloads.
NUM_CTX = 8192
# The trainer's Ollama: requests of the generators run side by side in these slots (the card
# was a quarter busy with one), flash attention and a q8_0 cache as in the home Ollama.
PARALLEL = 2


def http(
    url: str,
    path: str,
    body: dict[str, Any] | None = None,
    timeout: float = 600,
    method: str | None = None,
) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{url.rstrip('/')}{path}", data, {"Content-Type": "application/json"}, method=method
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw) if raw.strip() else {}


def local_url(settings: dict[str, Any]) -> str:
    return f"http://127.0.0.1:{settings['ollama']['local_port']}"


def ollama_env(host: str, models: Path, parallel: int = PARALLEL) -> dict[str, str]:
    env = dict(os.environ, OLLAMA_HOST=host, OLLAMA_MODELS=str(models))
    env.setdefault("OLLAMA_NUM_PARALLEL", str(parallel))
    env.setdefault("OLLAMA_FLASH_ATTENTION", "1")
    env.setdefault("OLLAMA_KV_CACHE_TYPE", "q8_0")
    env["LD_LIBRARY_PATH"] = f"{OLLAMA_DIR / 'lib' / 'ollama'}:{env.get('LD_LIBRARY_PATH', '')}"
    return env


def start_local(settings: dict[str, Any], workspace_root: Path) -> str:
    """The trainer's Ollama (started detached when it is not running yet)."""
    url = local_url(settings)
    try:
        http(url, "/api/version", timeout=3)
        return url
    except OSError:
        pass
    binary = OLLAMA_DIR / "bin" / "ollama"
    if not binary.exists():
        raise FileNotFoundError(f"{binary} missing - run scripts/setup.sh on the GPU machine")
    models = workspace_root / "ollama-models"
    models.mkdir(parents=True, exist_ok=True)
    log = workspace_root / "jobs" / "ollama.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    port = settings["ollama"]["local_port"]
    with log.open("ab") as out:
        subprocess.Popen(
            [str(binary), "serve"],
            env=ollama_env(f"127.0.0.1:{port}", models),
            stdout=out,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    for _ in range(60):
        try:
            http(url, "/api/version", timeout=2)
            return url
        except OSError:
            time.sleep(1)
    raise RuntimeError(f"the trainer's Ollama did not start ({log})")


class Teacher:
    """Chat with the teacher model: JSON (with a schema) or plain text."""

    def __init__(self, url: str, model: str) -> None:
        self.url = url.rstrip("/")
        self.model = model

    def ensure(self) -> None:
        """Download the teacher model into the trainer's Ollama when it is missing."""
        names = {m["name"] for m in http(self.url, "/api/tags").get("models", [])}
        if self.model in names or f"{self.model}:latest" in names:
            return
        print(f".. pulling {self.model} into the trainer's Ollama", flush=True)
        http(self.url, "/api/pull", {"model": self.model, "stream": False}, timeout=7200)

    def _chat(self, body: dict[str, Any]) -> str:
        body = {"model": self.model, "stream": False, "think": False, "keep_alive": "30m", **body}
        for attempt in range(RETRIES + 1):
            try:
                return http(self.url, "/api/chat", body)["message"]["content"]
            except urllib.error.HTTPError:
                raise
            except (OSError, KeyError) as err:
                if attempt == RETRIES:
                    raise
                print(f"!! teacher: {err} - retry", flush=True)
                time.sleep(5)
        raise AssertionError("unreachable")

    def json(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        temperature: float = 0.0,
        num_predict: int = 400,
        seed: int | None = None,
    ) -> dict[str, Any] | None:
        options: dict[str, Any] = {
            "temperature": temperature,
            "num_predict": num_predict,
            "num_ctx": NUM_CTX,
        }
        if seed is not None:
            options["seed"] = seed
        content = self._chat({"format": schema, "options": options, "messages": messages})
        try:
            value = json.loads(content)
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    def text(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        num_predict: int = 300,
    ) -> str:
        options = {"temperature": temperature, "num_predict": num_predict, "num_ctx": NUM_CTX}
        return " ".join(self._chat({"options": options, "messages": messages}).split())

    def unload(self) -> None:
        with contextlib.suppress(OSError):
            http(self.url, "/api/generate", {"model": self.model, "keep_alive": 0}, timeout=60)


# --- other teachers: an OpenAI-compatible API, Claude, or by hand ---------------------------------
#
# Every call of the generators belongs to a role: ``writer`` writes the data (paraphrases,
# commands, answers), ``judge`` checks and labels it (topics, parsing commands back, test facts),
# ``test_writer`` writes the generated test. Each role has its own teacher in trainer.yaml
# (``teacher.<role>``: provider, model, base_url) - e.g. Claude writes, the local Gemma judges.

PROVIDERS = ("ollama", "openai", "claude", "manual")
ROLES = ("writer", "judge", "test_writer")
DEFAULT_MODELS = {"claude": "claude-opus-5-5"}  # an OpenAI-compatible API: name the model
OPENAI_URL = "https://api.openai.com/v1"
# API keys: workspace/secrets/<provider>_key (mode 600, saved by the studio), or the environment
KEY_ENV = {"openai": "OPENAI_API_KEY", "claude": "ANTHROPIC_API_KEY"}
SECRETS_DIR = "secrets"
API_RETRIES = 5


class ManualRole(RuntimeError):
    """The role is done by hand (provider ``manual``): its prompts are exported, the answers
    imported (router-trainer handoff)."""


def is_manual(settings: dict[str, Any], role: str) -> bool:
    """Is the role done by hand (exported and imported, router-trainer handoff)?"""
    return role_settings(settings, role)["provider"] == "manual"


def role_settings(settings: dict[str, Any], role: str) -> dict[str, Any]:
    """provider, model, base_url and effort of a role; the ``ollama`` models are the defaults."""
    own = dict((settings.get("teacher") or {}).get(role) or {})
    provider = own.get("provider") or "ollama"
    if provider not in PROVIDERS:
        raise ValueError(f"teacher.{role}.provider: {provider!r} (one of {', '.join(PROVIDERS)})")
    ollama_model = settings["ollama"]["test_writer" if role == "test_writer" else "teacher"]
    model = own.get("model") or (
        ollama_model if provider == "ollama" else DEFAULT_MODELS.get(provider, "")
    )
    return {
        "provider": provider,
        "model": model,
        "base_url": own.get("base_url") or "",
        "effort": own.get("effort") or "low",
    }


def secret_path(workspace_root: Path, provider: str) -> Path:
    return workspace_root / SECRETS_DIR / f"{provider}_key"


def save_key(workspace_root: Path, provider: str, key: str) -> None:
    """Save an API key readable by the owner only (an empty key removes it)."""
    path = secret_path(workspace_root, provider)
    if not key.strip():
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(key.strip() + "\n")
    path.chmod(0o600)


def api_key(workspace_root: Path, provider: str) -> str:
    path = secret_path(workspace_root, provider)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return os.environ.get(KEY_ENV.get(provider, ""), "")


def has_key(workspace_root: Path, provider: str) -> bool:
    return bool(api_key(workspace_root, provider))


def _split_system(messages: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    return system, [m for m in messages if m["role"] != "system"]


def strict_schema(schema: Any) -> Any:
    """A JSON schema as structured outputs want it: every object closed and fully required."""
    if isinstance(schema, dict):
        out = {key: strict_schema(value) for key, value in schema.items()}
        if out.get("type") == "object" and "properties" in out:
            out.setdefault("additionalProperties", False)
            out["required"] = list(out["properties"])
        return out
    if isinstance(schema, list):
        return [strict_schema(item) for item in schema]
    return schema


def _parse(text: str) -> dict[str, Any] | None:
    """A JSON object from a reply (also inside ```json fences or after a sentence)."""
    text = (text or "").strip()
    for candidate in (text, text[text.find("{") : text.rfind("}") + 1] if "{" in text else ""):
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


class OpenAITeacher:
    """Any OpenAI-compatible chat API (OpenAI, OpenRouter, Groq, LM Studio, vLLM …)."""

    def __init__(self, base_url: str, model: str, key: str) -> None:
        self.url = (base_url or OPENAI_URL).rstrip("/")
        self.model = model
        self.key = key
        self.schema_ok = True  # dropped after the first refusal of response_format json_schema

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        for attempt in range(API_RETRIES + 1):
            request = urllib.request.Request(
                f"{self.url}/chat/completions", json.dumps(body).encode(), headers
            )
            try:
                with urllib.request.urlopen(request, timeout=600) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError as err:
                if err.code in (429, 500, 502, 503, 504, 529) and attempt < API_RETRIES:
                    wait = float(err.headers.get("Retry-After") or 2 ** (attempt + 1))
                    print(f"!! teacher API: HTTP {err.code} - retry in {wait:.0f} s", flush=True)
                    time.sleep(min(wait, 120))
                    continue
                raise
            except OSError:
                if attempt == API_RETRIES:
                    raise
                time.sleep(2 ** (attempt + 1))
        raise AssertionError("unreachable")

    def _content(self, body: dict[str, Any]) -> str:
        reply = self._post({"model": self.model, **body})
        return (reply.get("choices") or [{}])[0].get("message", {}).get("content") or ""

    def json(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        temperature: float = 0.0,
        num_predict: int = 400,
        seed: int | None = None,
    ) -> dict[str, Any] | None:
        body: dict[str, Any] = {"messages": messages, "temperature": temperature,
                                "max_tokens": max(num_predict, 256)}  # fmt: skip
        if seed is not None:
            body["seed"] = seed
        if self.schema_ok:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "answer", "schema": strict_schema(schema), "strict": True},
            }
            try:
                return _parse(self._content(body))
            except urllib.error.HTTPError as err:
                if err.code != 400:
                    raise
                self.schema_ok = False  # this server does not take schemas: ask in words
        body.pop("response_format", None)
        hint = "Answer with JSON only, matching this schema: " + json.dumps(schema)
        body["messages"] = [*messages, {"role": "system", "content": hint}]
        return _parse(self._content(body))

    def text(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        num_predict: int = 300,
    ) -> str:
        body = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max(num_predict, 256),
        }
        return " ".join(self._content(body).split())


class ClaudeTeacher:
    """Claude through Anthropic's own SDK: JSON by structured outputs (the schema itself),
    a server-side fallback model when a request is declined, retries by the SDK."""

    FALLBACK_BETA = "server-side-fallback-2026-07-01"

    def __init__(self, model: str, key: str, effort: str = "low", base_url: str = "") -> None:
        try:
            import anthropic
        except ImportError as err:
            raise RuntimeError(
                "the Claude teacher needs the anthropic package (pip install 'anthropic>=2.10')"
            ) from err
        options: dict[str, Any] = {"api_key": key or None, "max_retries": API_RETRIES}
        if base_url:
            options["base_url"] = base_url
        self.client = anthropic.Anthropic(**options)
        self.model = model
        self.effort = effort

    def _create(self, messages: list[dict[str, str]], output: dict[str, Any]) -> str:
        system, rest = _split_system(messages)
        # Sampling options and seeds are not accepted by current Claude models; the thinking
        # tokens count against max_tokens, so the limit is generous (only what is written is paid).
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 16000,
            "messages": rest,
            "output_config": {"effort": self.effort, **output},
            "betas": [self.FALLBACK_BETA],
            "fallbacks": "default",
        }
        if system:
            params["system"] = system
        response = self.client.beta.messages.create(**params)
        if response.stop_reason == "refusal":
            return ""
        return next((b.text for b in response.content if b.type == "text"), "")

    def json(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        temperature: float = 0.0,
        num_predict: int = 400,
        seed: int | None = None,
    ) -> dict[str, Any] | None:
        output = {"format": {"type": "json_schema", "schema": strict_schema(schema)}}
        return _parse(self._create(messages, output))

    def text(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        num_predict: int = 300,
    ) -> str:
        return " ".join(self._create(messages, {}).split())


class ManualTeacher:
    """A role done by hand: the generators do not call it (router-trainer handoff instead)."""

    def __init__(self, role: str) -> None:
        self.role = role

    def json(self, *args: Any, **kwargs: Any) -> None:
        raise ManualRole(f"the {self.role} is set to `manual` - use router-trainer handoff")

    text = json


class CachedTeacher:
    """Remembers every answer of a paid or remote teacher (generated/teacher/<role>.jsonl): a
    resumed step asks nothing twice."""

    def __init__(self, inner: Any, path: Path) -> None:
        self.inner = inner
        self.model = getattr(inner, "model", "")
        self.path = path
        self.answers: dict[str, Any] = {}
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                with contextlib.suppress(ValueError, KeyError):
                    row = json.loads(line)
                    self.answers[row["key"]] = row["answer"]

    def _key(self, kind: str, messages: Any, schema: Any, options: dict[str, Any]) -> str:
        import hashlib

        raw = json.dumps([kind, self.model, messages, schema, options], sort_keys=True,
                         ensure_ascii=False)  # fmt: skip
        return hashlib.sha256(raw.encode()).hexdigest()

    def _remember(self, key: str, answer: Any) -> None:
        self.answers[key] = answer
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"key": key, "answer": answer}, ensure_ascii=False) + "\n")

    def json(self, messages, schema, **options) -> dict[str, Any] | None:
        key = self._key("json", messages, schema, options)
        if key not in self.answers:
            answer = self.inner.json(messages, schema, **options)
            if answer is None:
                return None  # not remembered: asked again next time
            self._remember(key, answer)
        return self.answers[key]

    def text(self, messages, **options) -> str:
        key = self._key("text", messages, None, options)
        if key not in self.answers:
            answer = self.inner.text(messages, **options)
            if not answer:
                return answer
            self._remember(key, answer)
        return self.answers[key]

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def make(settings: dict[str, Any], workspace_root: Path, role: str) -> Any:
    """The teacher of a role as trainer.yaml sets it (``teacher.<role>``)."""
    if role not in ROLES:
        raise ValueError(f"unknown teacher role {role!r}")
    chosen = role_settings(settings, role)
    provider = chosen["provider"]
    if provider == "ollama":
        teacher = Teacher(start_local(settings, workspace_root), chosen["model"])
        teacher.ensure()
        return teacher
    if provider == "manual":
        return ManualTeacher(role)
    key = api_key(workspace_root, provider)
    if provider == "openai":
        if not chosen["model"]:
            raise RuntimeError(f"teacher.{role}.model: name the model of the OpenAI-compatible API")
        inner: Any = OpenAITeacher(chosen["base_url"], chosen["model"], key)
    else:
        if not key:
            raise RuntimeError(
                "no Claude API key - save it in the studio (Settings → Teacher) or set "
                "ANTHROPIC_API_KEY"
            )
        inner = ClaudeTeacher(chosen["model"], key, chosen["effort"], chosen["base_url"])
    return CachedTeacher(inner, workspace_root / "generated" / "teacher" / f"{role}.jsonl")


def check(settings: dict[str, Any], workspace_root: Path, role: str) -> dict[str, Any]:
    """One short question to the teacher of a role (the studio's Check): does it answer JSON?"""
    chosen = role_settings(settings, role)
    out = {"role": role, **{k: chosen[k] for k in ("provider", "model", "base_url")}}
    if chosen["provider"] == "manual":
        return {**out, "ok": True, "message": "by hand: router-trainer handoff"}
    if chosen["provider"] == "ollama":
        try:
            names = {
                m["name"]
                for m in http(local_url(settings), "/api/tags", timeout=5).get("models", [])
            }
        except OSError as err:
            return {**out, "ok": False, "message": f"the trainer's Ollama: {err}"}
        present = chosen["model"] in names or f"{chosen['model']}:latest" in names
        message = "ready" if present else "not downloaded yet - fetched on first use"
        return {**out, "ok": True, "message": message}
    try:
        made = make(settings, workspace_root, role)
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
        answer = made.inner.json([{"role": "user", "content": 'Answer {"ok": true}.'}], schema)
    except Exception as err:
        return {**out, "ok": False, "message": f"{type(err).__name__}: {err}"[:300]}
    ok = isinstance(answer, dict) and answer.get("ok") is True
    return {**out, "ok": ok, "message": "answers JSON" if ok else f"unexpected answer: {answer}"}
