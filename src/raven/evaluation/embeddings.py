"""Deterministic lexical test vectors, not learned or production embeddings."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

DIMENSIONS = 512
SEED = "RX41-20260908"
_STOPWORDS_TEXT = (
    "a al alla alle anche che chi con da dal dalla degli dei del della delle di dove e è "
    "ed fra gli ha i il in la le lo nel nella non o per quale quali quando si sono su tra "
    "un una uno scenario sintetico rx41 what where which when who is are the and of to "
    "for an does do this that"
)
_STOPWORDS = set(_STOPWORDS_TEXT.split())


def deterministic_embedding(text: str) -> tuple[float, ...]:
    """Hash a bag of words into a normalized vector using a fixed public seed.

    Polarity is deliberately not adjudicated here. This lexical control tests retrieval
    plumbing; it cannot estimate the quality of a multilingual semantic embedding model.
    """
    tokens = [
        token
        for token in re.findall(r"[\w]+(?:[-.]\w+)*", text.casefold())
        if token not in _STOPWORDS
    ]
    counts = Counter(tokens)
    vector = [0.0] * DIMENSIONS
    for token, count in counts.items():
        digest = hashlib.sha256(f"{SEED}:{token}".encode()).digest()
        position = int.from_bytes(digest[:4], "big") % DIMENSIONS
        vector[position] += (1.0 + math.log(count)) * (1 if digest[4] % 2 else -1)
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        vector[0] = 1.0
        norm = 1.0
    return tuple(value / norm for value in vector)
