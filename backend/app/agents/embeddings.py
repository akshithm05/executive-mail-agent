"""Embedding support for the long-term memory subsystem.

Anthropic does not serve an embeddings endpoint, so the memory system talks
to embeddings through a small :class:`EmbeddingProvider` protocol instead of
a concrete SDK -- exactly the same seam this codebase already uses for
``StructuredLLMClient`` (swappable behind ``GraphDependencies``). Two things
can implement it:

* :class:`HashingEmbeddingProvider` (used today): a deterministic, local,
  dependency-free embedding using the feature-hashing trick (character
  n-grams hashed into a fixed-size vector, L2-normalized). It requires no
  API key and no network call, so semantic memory retrieval genuinely works
  out of the box -- it is a real, if low-fidelity, embedding, not a stub.
* A future neural provider (e.g. Voyage AI, which Anthropic recommends as
  its embeddings partner, or OpenAI) -- add a class implementing the same
  ``embed``/``embed_batch`` methods and select it via
  ``MemorySettings.embedding_provider``. No caller in this module needs to
  change: ``MemoryService`` and ``MemoryRetrievalService`` only depend on
  the protocol.

Vector storage today is a plain JSON float array on ``Memory.embedding``
(see ``app/infra/models/memory.py``) and similarity search is an
in-application cosine-similarity scan (see
``MemoryRepository.list_embedding_candidates``). Swapping to ``pgvector`` or
an external vector database later means changing that one repository method
and the embedding provider -- not any of the scoring/retrieval/graph code
that calls them.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class EmbeddingProvider(Protocol):
    """Turns text into a fixed-size embedding vector."""

    @property
    def model_name(self) -> str:
        """Identifier stored alongside each embedding (``Memory.embedding_model``)."""
        ...

    @property
    def dimensions(self) -> int:
        """Length of every vector this provider returns."""
        ...

    def embed(self, text: str) -> list[float]:
        """Embed a single piece of text."""
        ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts. Default providers may just loop ``embed``."""
        ...


def _char_ngrams(token: str, n: int = 3) -> list[str]:
    if len(token) <= n:
        return [token]
    return [token[i : i + n] for i in range(len(token) - n + 1)]


class HashingEmbeddingProvider:
    """Deterministic local embedding via the hashing trick (no API/network).

    Each token's character n-grams are hashed (SHA-256, truncated) into a
    bucket in a fixed-size vector; bucket signs alternate based on a second
    hash bit to reduce collision bias (the standard "signed hashing trick",
    as used by e.g. ``sklearn.feature_extraction.HashingVectorizer``). The
    result is L2-normalized so cosine similarity behaves sensibly.

    This is not a learned semantic embedding -- it will not capture synonyms
    the way a neural embedding would. It reliably captures lexical overlap
    (shared words/substrings), which is enough to group memories about the
    same sender, topic, or recurring phrase, and it has the advantage of
    being real, fast, and requiring zero configuration.
    """

    def __init__(self, dimensions: int = 256) -> None:
        self._dimensions = dimensions

    @property
    def model_name(self) -> str:
        """Identifier stored alongside each embedding this provider produces."""
        return f"hashing-trick-{self._dimensions}d"

    @property
    def dimensions(self) -> int:
        """Length of every vector this provider returns."""
        return self._dimensions

    def embed(self, text: str) -> list[float]:
        """Embed one piece of text into a fixed-size, L2-normalized vector."""
        vector = [0.0] * self._dimensions
        tokens = _TOKEN_PATTERN.findall(text.lower())
        for token in tokens:
            for gram in _char_ngrams(token):
                digest = hashlib.sha256(gram.encode("utf-8")).digest()
                bucket = int.from_bytes(digest[:4], "big") % self._dimensions
                sign = 1.0 if digest[4] % 2 == 0 else -1.0
                vector[bucket] += sign

        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            return vector
        return [v / norm for v in vector]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts, one at a time."""
        return [self.embed(text) for text in texts]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return cosine similarity in [-1, 1], or 0.0 for a zero-length vector."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
