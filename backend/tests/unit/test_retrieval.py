import pytest
from fastapi.testclient import TestClient

from app.db import make_engine
from app.guides import GuideSection, get_guides
from app.llm import FakeLLM, LLMError
from app.main import create_app
from app.retrieval import GuideIndex, get_guide_index, tokenize


@pytest.fixture(scope="module")
def sections():
    return [s for g in get_guides() for s in g.sections]


@pytest.mark.parametrize(
    ("question", "guide_id"),
    [
        ("when do I put my seatbelt on", "seatbelt-and-cab-safety"),
        ("my track is sinking in soft ground what do I do", "soft-ground-and-edges"),
        ("how do I check for hydraulic leaks before starting", "pre-start-walkaround"),
        ("I feel drowsy and tired", "fatigue-and-breaks"),
        ("which joystick moves the boom", "excavator-operation"),
        ("the machine touched a power line", "emergencies-and-reporting"),
    ],
)
def test_keyword_only_index_finds_the_right_guide(sections, question, guide_id):
    index = GuideIndex(sections, llm=None)
    hits = index.search(question)
    assert hits and hits[0].section.guide_id == guide_id


def test_blended_index_uses_embeddings_and_caches_them(sections, tmp_path):
    cache = tmp_path / "emb.json"
    llm = FakeLLM()
    index = GuideIndex(sections, llm=llm, cache_path=cache)
    assert index.vectors.shape == (len(sections), llm.embedding_dim)
    assert cache.exists()
    hits = index.search("seatbelt engine running")
    assert hits[0].section.guide_id == "seatbelt-and-cab-safety"

    again = FakeLLM()
    GuideIndex(sections, llm=again, cache_path=cache)
    assert again.calls == []  # all section vectors came from the cache


def test_falls_back_to_keywords_when_embedding_fails(sections):
    class Broken(FakeLLM):
        def embed(self, texts):
            raise LLMError("down")

    index = GuideIndex(sections, llm=Broken(), cache_path=None)
    assert index.vectors is None
    assert index.search("seatbelt")[0].section.guide_id == "seatbelt-and-cab-safety"


def test_cached_vectors_from_another_model_fall_back_to_keywords(sections, tmp_path):
    cache = tmp_path / "emb.json"
    GuideIndex(sections, llm=FakeLLM(embedding_dim=16), cache_path=cache)
    index = GuideIndex(sections, llm=FakeLLM(embedding_dim=8), cache_path=cache)
    hits = index.search("seatbelt engine running")
    assert hits[0].section.guide_id == "seatbelt-and-cab-safety"


def test_cache_mixing_dimensions_falls_back_to_keywords(sections, tmp_path):
    cache = tmp_path / "emb.json"
    GuideIndex(sections[:2], llm=FakeLLM(embedding_dim=16), cache_path=cache)
    index = GuideIndex(sections, llm=FakeLLM(embedding_dim=8), cache_path=cache)
    assert index.vectors is None
    assert index.search("seatbelt")[0].section.guide_id == "seatbelt-and-cab-safety"


def test_unrelated_question_returns_nothing(sections):
    assert GuideIndex(sections, llm=None).search("what is the capital of france") == []


def test_tokenize_drops_stopwords_and_plurals():
    assert tokenize("The tracks are sinking into mud") == ["track", "sinking", "mud"]


def test_empty_index():
    assert GuideIndex([], llm=None).search("anything") == []


def test_search_endpoint(sections):
    app = create_app(make_engine("sqlite://"))
    app.dependency_overrides[get_guide_index] = lambda: GuideIndex(sections, llm=None)
    with TestClient(app) as client:
        body = client.get("/guides/search", params={"q": "seatbelt", "k": 2}).json()
        assert body[0]["source"].startswith("Seatbelt and cab safety >")
        assert len(body) <= 2
        assert client.get("/guides/search", params={"q": "x"}).status_code == 422


def test_section_source_format():
    s = GuideSection(guide_id="g", guide_title="Title", heading="Head", text="t")
    assert s.source == "Title > Head"
