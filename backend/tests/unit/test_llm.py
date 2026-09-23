import json
from types import SimpleNamespace

import pytest

from app import llm as llm_module
from app.config import Settings
from app.llm import CachedLLM, FakeLLM, LLMError, OpenAILLM, build_llm, get_llm, set_llm
from app.schemas import Briefing, Replan

BRIEFING = Briefing(headline="Wet ground today", key_risks=["soft edge"], focus_tip="Go slow")


class _StubCompletions:
    def __init__(self, message):
        self.message = message
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(choices=[SimpleNamespace(message=self.message)])


def _openai_with(message) -> tuple[OpenAILLM, _StubCompletions]:
    completions = _StubCompletions(message)
    client = SimpleNamespace(beta=SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    return OpenAILLM(model="test-model", client=client), completions


def test_openai_structured_passes_schema_and_returns_parsed():
    llm, completions = _openai_with(SimpleNamespace(parsed=BRIEFING, refusal=None))
    result = llm.structured("sys", "user", Briefing)
    assert result == BRIEFING
    assert completions.kwargs["response_format"] is Briefing
    assert completions.kwargs["model"] == "test-model"
    assert completions.kwargs["messages"][0] == {"role": "system", "content": "sys"}


def test_openai_structured_raises_on_refusal():
    llm, _ = _openai_with(SimpleNamespace(parsed=None, refusal="no"))
    with pytest.raises(LLMError, match="refused"):
        llm.structured("sys", "user", Briefing)


def test_openai_without_key_raises(monkeypatch):
    monkeypatch.setattr(
        llm_module, "get_settings", lambda: SimpleNamespace(openai_api_key=None, openai_model="m")
    )
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        _ = OpenAILLM().client


def test_fake_llm_canned_and_callable_responses():
    fake = FakeLLM().on(Briefing, BRIEFING)
    fake.on(Replan, lambda system, user: Replan(new_order=[2, 1], explanation=user))
    assert fake.structured("s", "u", Briefing) == BRIEFING
    assert fake.structured("s", "swap", Replan).explanation == "swap"
    assert [c["schema"] for c in fake.calls] == [Briefing, Replan]


def test_fake_llm_unregistered_schema_raises():
    with pytest.raises(LLMError):
        FakeLLM().structured("s", "u", Briefing)


def test_fake_llm_transcripts_and_embeddings_are_deterministic():
    fake = FakeLLM(transcripts=["soft ground near the ramp"])
    assert fake.transcribe(b"audio") == "soft ground near the ramp"
    a, b = fake.embed(["soft ground", "soft ground"])
    assert a == b
    assert abs(sum(v * v for v in a) - 1.0) < 1e-9


def test_set_llm_overrides_global():
    fake = FakeLLM()
    set_llm(fake)
    try:
        assert get_llm() is fake
    finally:
        set_llm(None)
    default = get_llm()
    assert isinstance(default, CachedLLM) and isinstance(default.inner, OpenAILLM)
    set_llm(None)


def _settings(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(llm_module, "get_settings", lambda: Settings(_env_file=None))


def test_build_llm_skips_cache_when_off(monkeypatch):
    _settings(monkeypatch, LLM_CACHE="off")
    assert isinstance(build_llm(), OpenAILLM)


def test_build_llm_record_mode(monkeypatch, tmp_path):
    _settings(monkeypatch, LLM_CACHE="record", LLM_CACHE_PATH=str(tmp_path / "c.json"))
    llm = build_llm()
    assert isinstance(llm, CachedLLM) and llm.record
    assert llm.path == tmp_path / "c.json"


def test_cache_miss_goes_to_inner_and_is_not_saved_in_read_mode(tmp_path):
    fake = FakeLLM().on(Briefing, BRIEFING)
    cached = CachedLLM(fake, tmp_path / "c.json")
    assert cached.structured("sys", "user", Briefing) == BRIEFING
    assert len(fake.calls) == 1
    assert not (tmp_path / "c.json").exists()


def test_recorded_output_replays_without_calling_inner(tmp_path):
    path = tmp_path / "c.json"
    CachedLLM(FakeLLM().on(Briefing, BRIEFING), path, record=True).structured("s", "u", Briefing)
    assert json.loads(path.read_text())

    silent = FakeLLM()  # no responses: any call through would raise
    replayed = CachedLLM(silent, path).structured("s", "u", Briefing)
    assert replayed == BRIEFING
    assert silent.calls == []


def test_cache_key_depends_on_prompt_and_schema(tmp_path):
    path = tmp_path / "c.json"
    CachedLLM(FakeLLM().on(Briefing, BRIEFING), path, record=True).structured("s", "u", Briefing)
    cached = CachedLLM(FakeLLM(), path)
    with pytest.raises(LLMError):
        cached.structured("s", "different user prompt", Briefing)
    with pytest.raises(LLMError):
        cached.structured("s", "u", Replan)


def test_corrupt_cache_entry_raises_llm_error_so_agents_fall_back(tmp_path):
    path = tmp_path / "c.json"
    key = CachedLLM.key("s", "u", Briefing)
    path.write_text(json.dumps({key: {"schema": "Briefing", "output": {"headline": 3}}}))
    with pytest.raises(LLMError):
        CachedLLM(FakeLLM(), path).structured("s", "u", Briefing)


def test_cache_passes_transcribe_and_embed_through(tmp_path):
    fake = FakeLLM(transcripts=["hello"])
    cached = CachedLLM(fake, tmp_path / "c.json")
    assert cached.transcribe(b"a") == "hello"
    assert cached.embed(["x"]) == fake.embed(["x"])
