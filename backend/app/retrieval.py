"""Guide retrieval: a small in-memory vector store over guide sections.

Score = blend of embedding cosine similarity and a normalised BM25 keyword score (title and
heading words count extra), so exact safety terms still match. Embeddings are cached on disk by content hash; if embeddings
are unavailable the index falls back to keywords alone.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.guides import GUIDES_DIR, GuideSection, get_guides
from app.llm import LLMClient, LLMError, get_llm

CACHE_PATH = GUIDES_DIR / ".cache" / "embeddings.json"
EMBED_WEIGHT = 0.6
BM25_K1 = 1.2
BM25_B = 0.75
HEADING_BOOST = 3  # a word in the guide title or section heading counts this many times
STOPWORDS = set(
    "the and for you your are with that this from have has was were not but all any can "
    "what when where how why who does did into onto out off over under then than them they "
    "their there here its it's our use using should would could will just like also".split()
)


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z]+", text.lower())
    return [w.rstrip("s") if len(w) > 4 else w for w in words if len(w) > 2 and w not in STOPWORDS]


@dataclass(frozen=True)
class Hit:
    section: GuideSection
    score: float

    @property
    def source(self) -> str:
        return self.section.source


class GuideIndex:
    def __init__(
        self,
        sections: list[GuideSection],
        llm: LLMClient | None = None,
        cache_path: Path | None = CACHE_PATH,
    ) -> None:
        self.sections = sections
        self.texts = [f"{s.guide_title}. {s.heading}. {s.text}" for s in sections]
        self._tokens = [
            Counter(tokenize(f"{s.guide_title} {s.heading}") * HEADING_BOOST + tokenize(s.text))
            for s in sections
        ]
        self._lengths = [sum(toks.values()) for toks in self._tokens]
        self._avg_len = sum(self._lengths) / len(self._lengths) if self._lengths else 1.0
        df = Counter(tok for toks in self._tokens for tok in toks)
        n = len(sections)
        self._idf = {tok: math.log(1 + (n - c + 0.5) / (c + 0.5)) for tok, c in df.items()}
        self.llm = llm
        self.cache_path = cache_path
        self.vectors: np.ndarray | None = self._embed_sections()

    # --- embeddings -------------------------------------------------------

    def _load_cache(self) -> dict[str, list[float]]:
        if self.cache_path and self.cache_path.exists():
            return json.loads(self.cache_path.read_text())
        return {}

    def _embed_sections(self) -> np.ndarray | None:
        if self.llm is None or not self.sections:
            return None
        cache = self._load_cache()
        keys = [hashlib.sha1(t.encode()).hexdigest() for t in self.texts]
        missing = [i for i, k in enumerate(keys) if k not in cache]
        try:
            if missing:
                vectors = self.llm.embed([self.texts[i] for i in missing])
                cache.update({keys[i]: v for i, v in zip(missing, vectors)})
                if self.cache_path:
                    self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                    self.cache_path.write_text(json.dumps(cache))
        except LLMError:
            return None
        matrix = np.array([cache[k] for k in keys], dtype=float)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix / np.where(norms == 0, 1, norms)

    def _embed_query(self, query: str) -> np.ndarray | None:
        if self.vectors is None or self.llm is None:
            return None
        try:
            vec = np.array(self.llm.embed([query])[0], dtype=float)
        except LLMError:
            return None
        norm = np.linalg.norm(vec)
        return vec / norm if norm else None

    # --- scoring ----------------------------------------------------------

    def _keyword_scores(self, query: str) -> np.ndarray:
        """BM25, scaled to 0-1 by the best score the query's words could possibly reach."""
        q = set(tokenize(query))
        unseen_idf = math.log(1 + (len(self.sections) + 0.5) / 0.5)
        ceiling = sum(self._idf.get(tok, unseen_idf) * (BM25_K1 + 1) for tok in q)
        if not ceiling:
            return np.zeros(len(self.sections))
        scores = []
        for toks, length in zip(self._tokens, self._lengths):
            norm = BM25_K1 * (1 - BM25_B + BM25_B * length / self._avg_len)
            total = sum(
                self._idf[tok] * toks[tok] * (BM25_K1 + 1) / (toks[tok] + norm)
                for tok in q
                if tok in toks
            )
            scores.append(total / ceiling)
        return np.array(scores)

    def search(self, query: str, k: int = 3, min_score: float = 0.2) -> list[Hit]:
        if not self.sections:
            return []
        scores = self._keyword_scores(query)
        qvec = self._embed_query(query)
        if qvec is not None:
            cosine = np.clip(self.vectors @ qvec, 0, 1)
            scores = EMBED_WEIGHT * cosine + (1 - EMBED_WEIGHT) * scores
        order = np.argsort(-scores, kind="stable")[:k]
        return [
            Hit(self.sections[i], round(float(scores[i]), 3))
            for i in order
            if scores[i] >= min_score
        ]


@lru_cache
def get_guide_index() -> GuideIndex:
    sections = [s for g in get_guides() for s in g.sections]
    return GuideIndex(sections, llm=get_llm())
