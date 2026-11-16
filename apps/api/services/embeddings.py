"""
Shared text-embedding helper (extracted during Phase 4 Section 6).

diff_engine.py (Section 2) and mining/engine.py (Section 6) both need "embed a
batch of texts with the platform's one fixed embedding profile" -- extracted here
rather than left as two copies (or a third, when this was first written only for
diff_engine). Comparability matters: two features embedding with different models
would produce vectors that are not meaningfully comparable to each other, so there
is exactly one embedding profile, in exactly one place, regardless of which
feature's agent-under-test used a different profile to generate its own answers.
"""
from __future__ import annotations

from google import genai
from google.genai import types

from apps.api.core.config import get_settings
from apps.api.core.llm_rate_limiter import get_limiter
from apps.api.core.model_profiles import get_profile

# Fixed regardless of the caller -- see module docstring.
EMBEDDING_PROFILE_NAME = "standard"


def _has_real_gemini_key(key: str) -> bool:
    return bool(key) and not key.lower().startswith("placeholder")


def _local_embed(texts: list[str], dims: int = 256) -> list[list[float]]:
    """Deterministic hashed bag-of-words embedding, L2-normalised.

    Used ONLY when no real Gemini key is configured (demo / offline). It is not semantic:
    it measures lexical overlap, so identical texts score 1.0 and unrelated texts score low.
    """
    import hashlib
    import math
    import re

    vectors: list[list[float]] = []
    for text in texts:
        vec = [0.0] * dims
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            bucket = int(hashlib.md5(token.encode()).hexdigest(), 16) % dims  # noqa: S324 (not security)
            vec[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        vectors.append([v / norm for v in vec])
    return vectors


def embed_texts(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    if not _has_real_gemini_key(settings.gemini_api_key):
        return _local_embed(texts)
    client = genai.Client(api_key=settings.gemini_api_key)
    # for_embedding=True: this is genuinely a different model (embedding_model,
    # not chat_model) with its own provider-side quota. Without this flag,
    # get_limiter("standard") would return the SAME limiter agents use for their
    # chat calls on this profile -- see get_limiter()'s docstring for the bug
    # that was.
    limiter = get_limiter(EMBEDDING_PROFILE_NAME, for_embedding=True)
    profile = get_profile(EMBEDDING_PROFILE_NAME)

    limiter.acquire()
    response = client.models.embed_content(
        model=profile.embedding_model,
        contents=texts,
        config=types.EmbedContentConfig(
            task_type="SEMANTIC_SIMILARITY", output_dimensionality=768
        ),
    )
    return [e.values for e in response.embeddings]
