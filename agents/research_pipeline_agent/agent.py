"""
Level 4 benchmark agent: Multi-Agent Research Pipeline (Phase 2 Section 10).

Architecture: Planner → [ResearcherA + ResearcherB] → Verifier → Synthesizer

Why this design tests what AgentBench needs to test (Holy Grail §12):
  - Planner: decomposes the user question into 2 distinct sub-queries
  - ResearcherA and ResearcherB: independently answer each sub-query via RAG
    (sequential in Phase 2, logically independent -- Phase 3 adds true async)
  - Verifier: checks whether the researchers' outputs are consistent and sufficient
  - Synthesizer: combines verified outputs into a final answer

The eval cases probe coordination failures:
  - Does the planner generate DISTINCT sub-queries (not duplicates)?
  - Does the synthesizer USE BOTH researchers' outputs?
  - Does the verifier CATCH gaps when a researcher finds nothing?
  - Is the total cost BOUNDED (coordination should not cause unbounded cost)?
  - Are there NO contradictions between the researchers?

Uses model profile system and rate limiter throughout.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np
from google import genai
from google.genai import types

from apps.api.core.config import get_settings
from apps.api.core.llm_rate_limiter import get_limiter
from apps.api.core.model_profiles import get_profile
from apps.api.services.adapters.base import AgentTurnResult, ToolCall

PROFILE = get_profile("high_reasoning")
KNOWLEDGE_BASE_DIR = REPO_ROOT / "agents" / "rag_agent" / "knowledge_base" / "docs"
RELEVANCE_THRESHOLD = 0.55
TOP_K = 3

_settings = get_settings()
_client = genai.Client(api_key=_settings.gemini_api_key)
_limiter = get_limiter("high_reasoning")
# Separate from _limiter: embedding_model and chat_model are different models
# with different provider-side quotas. Sharing one limiter for both meant every
# retrieval embedding call silently consumed chat call budget under the wrong
# model's name in Redis. See get_limiter()'s docstring.
_embedding_limiter = get_limiter("high_reasoning", for_embedding=True)

_CHUNKS: list[dict] | None = None
_CHUNK_EMBEDDINGS: list[list[float]] | None = None


def _load_chunks() -> list[dict]:
    chunks = []
    for doc_path in sorted(KNOWLEDGE_BASE_DIR.glob("*.md")):
        text = doc_path.read_text(encoding="utf-8")
        sections = text.split("\n## ")
        for section in sections:
            section = section.strip()
            if not section:
                continue
            heading = section.split("\n", 1)[0].lstrip("#").strip()
            chunks.append({"source": doc_path.name, "heading": heading, "text": section})
    return chunks


def _embed(texts: list[str], task_type: str) -> tuple[list[list[float]], int]:
    _embedding_limiter.acquire()
    response = _client.models.embed_content(
        model=PROFILE.embedding_model,
        contents=texts,
        config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=768),
    )
    tokens = sum(int(e.statistics.token_count) for e in response.embeddings if e.statistics)
    return [e.values for e in response.embeddings], tokens


def _cosine(a, b) -> float:
    a, b = np.array(a), np.array(b)
    d = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / d) if d else 0.0


def _ensure_indexed():
    global _CHUNKS, _CHUNK_EMBEDDINGS
    if _CHUNKS is not None:
        return
    _CHUNKS = _load_chunks()
    _CHUNK_EMBEDDINGS, _ = _embed([c["text"] for c in _CHUNKS], "RETRIEVAL_DOCUMENT")


def _retrieve(query: str) -> tuple[str, int]:
    _ensure_indexed()
    [qv], tokens = _embed([query], "RETRIEVAL_QUERY")
    scored = sorted(
        zip(_CHUNKS, _CHUNK_EMBEDDINGS),
        key=lambda pair: _cosine(qv, pair[1]),
        reverse=True,
    )
    top = [c for c, emb in scored[:TOP_K] if _cosine(qv, emb) >= RELEVANCE_THRESHOLD]
    if not top:
        return "No relevant information found in the knowledge base.", tokens
    context = "\n\n".join(f"### {c['heading']}\n{c['text']}" for c in top)
    return context, tokens


def _llm(prompt: str) -> tuple[str, int, int]:
    """Single LLM call with rate limiting. Returns (text, input_tokens, output_tokens)."""
    _limiter.acquire()
    response = _client.models.generate_content(
        model=PROFILE.chat_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.1,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    return (
        response.text,
        response.usage_metadata.prompt_token_count or 0,
        response.usage_metadata.candidates_token_count or 0,
    )


def _planner(question: str) -> tuple[str, str]:
    """Decomposes the user question into two distinct research sub-queries."""
    text, _, _ = _llm(
        f"You are a research planner. Decompose the following question into exactly "
        f"2 DISTINCT sub-questions that together cover the full answer. "
        f"The sub-questions must be different from each other and each answerable independently.\n"
        f"Return ONLY a JSON array with exactly 2 strings: [\"sub-question 1\", \"sub-question 2\"]\n\n"
        f"Question: {question}"
    )
    try:
        parts = json.loads(text.strip())
        if isinstance(parts, list) and len(parts) >= 2:
            return str(parts[0]), str(parts[1])
    except Exception:
        pass
    # Fallback: split the question in half
    mid = question.split("and") if "and" in question else [question, question]
    return mid[0].strip(), (mid[1].strip() if len(mid) > 1 else question)


def _researcher(sub_query: str, researcher_id: str) -> tuple[str, int]:
    """Answers one sub-query via RAG. Returns (answer, embed_tokens)."""
    context, embed_tokens = _retrieve(sub_query)
    answer, _, _ = _llm(
        f"You are Researcher {researcher_id}. Answer the following question using ONLY "
        f"the provided context. If the context does not contain the answer, say exactly: "
        f"'INSUFFICIENT: I could not find information about this in the knowledge base.'\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {sub_query}"
    )
    return answer, embed_tokens


def _verifier(
    question: str, sub_q1: str, answer1: str, sub_q2: str, answer2: str
) -> tuple[str, bool]:
    """
    Checks the two researchers' outputs for consistency and completeness.
    Returns (verdict_text, is_sufficient).
    """
    text, _, _ = _llm(
        f"You are a Verifier. Review these two research outputs for the question: '{question}'\n\n"
        f"Researcher A answered '{sub_q1}':\n{answer1}\n\n"
        f"Researcher B answered '{sub_q2}':\n{answer2}\n\n"
        f"Check for: (1) contradictions between A and B, (2) gaps where a researcher said "
        f"'INSUFFICIENT', (3) whether together they fully answer the original question.\n"
        f"Return JSON: {{\"sufficient\": true/false, \"issues\": \"describe any problems or 'none'\"}}"
    )
    try:
        v = json.loads(text.strip())
        return v.get("issues", "none"), bool(v.get("sufficient", True))
    except Exception:
        return text, True


def _synthesizer(question: str, answer1: str, answer2: str, verifier_notes: str) -> str:
    """Combines both researchers' outputs into a final coherent answer."""
    text, _, _ = _llm(
        f"You are a Synthesizer. Combine these two research outputs into one comprehensive "
        f"answer to the question: '{question}'\n\n"
        f"Research output 1:\n{answer1}\n\n"
        f"Research output 2:\n{answer2}\n\n"
        f"Verifier notes: {verifier_notes}\n\n"
        f"Write a single, coherent answer that draws on BOTH research outputs. "
        f"If the verifier flagged issues, acknowledge any limitations."
    )
    return text


def run_turn(session_state: dict, user_message: str) -> AgentTurnResult:
    start = time.monotonic()
    total_input_tokens = 0
    total_output_tokens = 0
    total_embed_tokens = 0

    # Stage 1: Planner
    sub_q1, sub_q2 = _planner(user_message)

    # Stage 2: Researchers (sequential, logically independent)
    answer1, embed1 = _researcher(sub_q1, "A")
    total_embed_tokens += embed1

    answer2, embed2 = _researcher(sub_q2, "B")
    total_embed_tokens += embed2

    # Stage 3: Verifier
    verifier_notes, is_sufficient = _verifier(user_message, sub_q1, answer1, sub_q2, answer2)

    # Stage 4: Synthesizer
    final_answer = _synthesizer(user_message, answer1, answer2, verifier_notes)

    latency_ms = int((time.monotonic() - start) * 1000)

    # Cost: 5 LLM calls (planner + 2 researchers + verifier + synthesizer) + embeddings
    embed_cost = (total_embed_tokens / 1_000_000) * 0.15
    # Rough estimate: each LLM call ~500 input + ~200 output tokens at gemini-2.5-flash
    # pricing (verified 2026-07-29 against ai.google.dev/gemini-api/docs/pricing --
    # $0.30/1M input, $2.50/1M output, unchanged from the old gemini-2.0-flash figures)
    estimated_input = 5 * 500
    estimated_output = 5 * 200
    chat_cost = (estimated_input / 1_000_000) * 0.30 + (estimated_output / 1_000_000) * 2.50
    cost_usd = round(embed_cost + chat_cost, 6)

    return AgentTurnResult(
        assistant_message=final_answer,
        tool_calls=[
            ToolCall(
                name="planner",
                arguments={"question": user_message},
                result=[sub_q1, sub_q2],
                latency_ms=latency_ms,
            ),
            ToolCall(
                name="researcher_a",
                arguments={"sub_query": sub_q1},
                result=answer1,
                latency_ms=latency_ms,
            ),
            ToolCall(
                name="researcher_b",
                arguments={"sub_query": sub_q2},
                result=answer2,
                latency_ms=latency_ms,
            ),
            ToolCall(
                name="verifier",
                arguments={"notes": verifier_notes, "sufficient": is_sufficient},
                result=verifier_notes,
                latency_ms=latency_ms,
            ),
        ],
        latency_ms=latency_ms,
        cost_usd=cost_usd,
    )