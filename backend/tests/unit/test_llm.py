from types import SimpleNamespace

import pytest

from app import llm as llm_module
from app.llm import FakeLLM, LLMError, OpenAILLM, get_llm, set_llm
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
    assert isinstance(get_llm(), OpenAILLM)
    set_llm(None)
