"""The single OpenAI client wrapper. No other module imports the OpenAI SDK.

Agents call `get_llm()` and use `structured()` for anything they parse. Tests swap in a
`FakeLLM` with `set_llm()` (or the `fake_llm` fixture) so the real API is never hit.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, TypeVar

import openai
from pydantic import BaseModel, ValidationError

from app.config import get_settings

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


@contextmanager
def _sdk_errors() -> Iterator[None]:
    """Surface SDK, network, and parsing failures as LLMError so callers can fall back."""
    try:
        yield
    except (openai.OpenAIError, ValidationError) as exc:
        raise LLMError(f"{type(exc).__name__}: {exc}") from exc


class LLMClient(Protocol):
    def structured(self, system: str, user: str, schema: type[T]) -> T: ...

    def transcribe(self, audio: bytes, filename: str = "note.webm") -> str: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAILLM:
    """Real client. Built lazily so importing this module never needs a key."""

    def __init__(
        self,
        model: str | None = None,
        embed_model: str = "text-embedding-3-small",
        client: Any | None = None,
    ) -> None:
        self.model = model or get_settings().openai_model
        self.embed_model = embed_model
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            key = get_settings().openai_api_key
            if key is None or not key.get_secret_value():
                raise LLMError("OPENAI_API_KEY is not set")
            self._client = openai.OpenAI(api_key=key.get_secret_value(), timeout=30.0)
        return self._client

    def structured(self, system: str, user: str, schema: type[T]) -> T:
        with _sdk_errors():
            completion = self.client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format=schema,
                temperature=0,
            )
        message = completion.choices[0].message
        if getattr(message, "refusal", None):
            raise LLMError(f"model refused: {message.refusal}")
        if message.parsed is None:
            raise LLMError("model returned no parsed output")
        return message.parsed

    def transcribe(self, audio: bytes, filename: str = "note.webm") -> str:
        with _sdk_errors():
            result = self.client.audio.transcriptions.create(
                model="whisper-1", file=(filename, audio)
            )
        return result.text

    def embed(self, texts: list[str]) -> list[list[float]]:
        with _sdk_errors():
            response = self.client.embeddings.create(model=self.embed_model, input=texts)
        return [item.embedding for item in response.data]


Responder = Callable[[str, str], BaseModel] | BaseModel


@dataclass
class FakeLLM:
    """Deterministic stand-in for tests and offline demos.

    Register a canned instance (or a `(system, user) -> instance` callable) per schema.
    Every call is recorded in `calls` for assertions.
    """

    responses: dict[type[BaseModel], Responder] = field(default_factory=dict)
    transcripts: list[str] = field(default_factory=list)
    embedding_dim: int = 8
    calls: list[dict[str, Any]] = field(default_factory=list)

    def on(self, schema: type[T], response: Callable[[str, str], T] | T) -> FakeLLM:
        self.responses[schema] = response
        return self

    def structured(self, system: str, user: str, schema: type[T]) -> T:
        self.calls.append(
            {"method": "structured", "schema": schema, "system": system, "user": user}
        )
        if schema not in self.responses:
            raise LLMError(f"FakeLLM has no response registered for {schema.__name__}")
        response = self.responses[schema]
        result = response(system, user) if callable(response) else response
        return schema.model_validate(result.model_dump())

    def transcribe(self, audio: bytes, filename: str = "note.webm") -> str:
        self.calls.append({"method": "transcribe", "filename": filename})
        if not self.transcripts:
            raise LLMError("FakeLLM has no transcript queued")
        return self.transcripts.pop(0)

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append({"method": "embed", "count": len(texts)})
        return [_hash_embedding(t, self.embedding_dim) for t in texts]


def _hash_embedding(text: str, dim: int) -> list[float]:
    """Cheap deterministic bag-of-words vector so similarity still means something."""
    vec = [0.0] * dim
    for word in text.lower().split():
        vec[sum(map(ord, word)) % dim] += 1.0
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


class CachedLLM:
    """Read-through cache of structured outputs, keyed by schema and exact prompt.

    The demo shift is deterministic, so its briefing, replan note, incident report, and drills
    hit the same prompts every run. A recorded cache replays them without an API call; anything
    else falls through to `inner`. With `record=True` misses are saved back to `path`.
    """

    def __init__(self, inner: LLMClient, path: Path, record: bool = False) -> None:
        self.inner = inner
        self.path = Path(path)
        self.record = record
        self._lock = threading.Lock()
        self.entries: dict[str, dict[str, Any]] = (
            json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        )

    @staticmethod
    def key(system: str, user: str, schema: type[BaseModel]) -> str:
        raw = json.dumps([schema.__name__, system, user], ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def structured(self, system: str, user: str, schema: type[T]) -> T:
        key = self.key(system, user, schema)
        entry = self.entries.get(key)
        if entry is not None and entry["schema"] == schema.__name__:
            with _sdk_errors():
                return schema.model_validate(entry["output"])
        result = self.inner.structured(system, user, schema)
        if self.record:
            with self._lock:
                self.entries[key] = {
                    "schema": schema.__name__,
                    "output": result.model_dump(mode="json"),
                }
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(
                    json.dumps(self.entries, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
        return result

    def transcribe(self, audio: bytes, filename: str = "note.webm") -> str:
        return self.inner.transcribe(audio, filename)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.inner.embed(texts)


def build_llm() -> LLMClient:
    """The real client, behind the demo cache unless LLM_CACHE=off."""
    settings = get_settings()
    client: LLMClient = OpenAILLM()
    if settings.llm_cache == "off":
        return client
    return CachedLLM(client, settings.llm_cache_path, record=settings.llm_cache == "record")


_llm: LLMClient | None = None


def get_llm() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = build_llm()
    return _llm


def set_llm(llm: LLMClient | None) -> None:
    """Override the process-wide client. Pass None to reset to the real one."""
    global _llm
    _llm = llm
