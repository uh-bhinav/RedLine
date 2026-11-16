"""
Level 3 benchmark agent: Stateful Customer Support (Phase 2 Section 10).

Differences from the Level 1 RAG agent that make this Level 3:
  1. Structured memory: after every turn the agent extracts and stores entities,
     preferences, and constraints mentioned by the user into session_state. These
     are used explicitly in subsequent prompts.
  2. Memory bugs are the failure mode this agent is designed to surface --
     forgetting what the user said two turns ago, re-asking already-answered
     questions, contradicting stated preferences.
  3. Uses model profile system (not hardcoded model names).
  4. Uses the LLM rate limiter (not hardcoded sleeps).

Eval cases probe 7 distinct failure categories:
  entity memory, preference memory, constraint memory, correction memory,
  repeated-question suppression, context accumulation, topic continuity.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import json
import numpy as np
from google import genai
from google.genai import types

from apps.api.core.config import get_settings
from apps.api.core.llm_rate_limiter import get_limiter
from apps.api.core.model_profiles import get_profile
from apps.api.services.adapters.base import AgentTurnResult, ToolCall

# Use the model profile system -- never hardcode a model name
PROFILE = get_profile("high_reasoning")
KNOWLEDGE_BASE_DIR = REPO_ROOT / "agents" / "rag_agent" / "knowledge_base" / "docs"
RELEVANCE_THRESHOLD = 0.60
TOP_K = 3


_settings = get_settings()
_client = genai.Client(api_key=_settings.gemini_api_key)
_limiter = get_limiter("high_reasoning")
# Separate from _limiter: embedding_model and chat_model are different models
# with different provider-side quotas. Sharing one limiter for both meant every
# retrieval embedding call silently consumed chat call budget under the wrong
# model's name in Redis. See get_limiter()'s docstring.
_embedding_limiter = get_limiter("high_reasoning", for_embedding=True)

# Lazy-loaded KB (same as RAG agent)
_CHUNKS: list[dict] | None = None
_CHUNK_EMBEDDINGS: list[list[float]] | None = None


def _load_chunks() -> list[dict]:
    chunks = []
    for doc_path in sorted(KNOWLEDGE_BASE_DIR.glob("*.md")):
        text = doc_path.read_text(encoding="utf-8")
        sections = text.split("\n## ")
        for section in sections:
            section = section.strip()
            if not section or (section.startswith("# ") and "\n" not in section):
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


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    a_arr, b_arr = np.array(a), np.array(b)
    denom = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
    return float(np.dot(a_arr, b_arr) / denom) if denom else 0.0


def _ensure_kb_indexed() -> None:
    global _CHUNKS, _CHUNK_EMBEDDINGS
    if _CHUNKS is not None:
        return
    _CHUNKS = _load_chunks()
    _CHUNK_EMBEDDINGS, _ = _embed([c["text"] for c in _CHUNKS], "RETRIEVAL_DOCUMENT")


def _retrieve(query: str) -> tuple[list[dict], int]:
    _ensure_kb_indexed()
    [qv], tokens = _embed([query], "RETRIEVAL_QUERY")
    scored = sorted(
        zip(_CHUNKS, _CHUNK_EMBEDDINGS),
        key=lambda pair: _cosine_similarity(qv, pair[1]),
        reverse=True,
    )
    return [c for c, _ in scored[:TOP_K] if _cosine_similarity(qv, _) >= RELEVANCE_THRESHOLD], tokens


def _extract_memory(user_message: str, assistant_reply: str) -> dict:
    """
    Calls the LLM to extract structured memory from one exchange.
    Returns a dict of {entity_type: value} pairs.
    This is what makes this agent Level 3 -- it builds explicit structured state,
    not just raw conversation history.
    """
    _limiter.acquire()
    prompt = (
        "Extract any entities, preferences, or constraints the user mentioned in "
        "the following exchange. Return ONLY valid JSON with these optional keys:\n"
        '{"product": "...", "order_id": "...", "date": "...", "issue": "...", '
        '"preference": "...", "constraint": "...", "correction": "..."}\n'
        "If nothing was mentioned for a key, omit it. Return {} if nothing relevant.\n\n"
        f"User: {user_message}\n"
        f"Assistant: {assistant_reply}"
    )
    response = _client.models.generate_content(
        model=PROFILE.chat_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.0,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    try:
        return json.loads(response.text)
    except Exception:
        return {}


def run_turn(session_state: dict, user_message: str) -> AgentTurnResult:
    start = time.monotonic()

    # Load structured memory from previous turns
    memory: dict = session_state.setdefault("memory", {})
    history: list[dict] = session_state.setdefault("history", [])

    # Retrieve relevant KB chunks
    relevant_chunks, embed_tokens = _retrieve(user_message)
    retrieval_result = [f"{c['source']}#{c['heading']}" for c in relevant_chunks]

    context_text = (
        "\n\n".join(f"### {c['heading']}\n{c['text']}" for c in relevant_chunks)
        if relevant_chunks else ""
    )

    # Build structured memory string for the prompt
    memory_text = ""
    if memory:
        memory_lines = [f"  - {k}: {v}" for k, v in memory.items() if v]
        if memory_lines:
            memory_text = "What the user has already told us:\n" + "\n".join(memory_lines) + "\n\n"

    # Build conversation history (last 3 turns, condensed)
    history_text = ""
    if history:
        recent = history[-3:]
        history_text = "Recent conversation:\n" + "\n".join(
            f"User: {t['user']}\nAssistant: {t['assistant']}" for t in recent
        ) + "\n\n"

    # Generate response
    if not relevant_chunks and not memory:
        assistant_message = (
            "I don't have information about that in TrailLight Gear's policy documents."
        )
        input_tokens = output_tokens = 0
    else:
        prompt = (
            "You are a customer support assistant for TrailLight Gear.\n\n"
            + memory_text
            + history_text
            + (f"Relevant policy information:\n{context_text}\n\n" if context_text else "")
            + "CRITICAL INSTRUCTIONS:\n"
            "1. NEVER ask for information the user has already provided (see memory above).\n"
            "2. If you have a correction in memory, use the corrected value.\n"
            "3. Honor stated preferences (e.g. if user prefers email, don't suggest calling).\n"
            "4. Answer using ONLY the policy information and memory provided.\n\n"
            f"User: {user_message}"
        )
        _limiter.acquire()
        response = _client.models.generate_content(
            model=PROFILE.chat_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        assistant_message = response.text
        input_tokens = response.usage_metadata.prompt_token_count or 0
        output_tokens = response.usage_metadata.candidates_token_count or 0

    # Extract and merge structured memory from this turn
    new_memory = _extract_memory(user_message, assistant_message)
    # Corrections override existing values
    memory.update(new_memory)

    history.append({"user": user_message, "assistant": assistant_message})

    embed_cost = (embed_tokens / 1_000_000) * 0.15
    chat_cost = ((input_tokens / 1_000_000) * 0.30) + ((output_tokens / 1_000_000) * 2.50)
    cost_usd = round(embed_cost + chat_cost, 6)
    latency_ms = int((time.monotonic() - start) * 1000)

    return AgentTurnResult(
        assistant_message=assistant_message,
        tool_calls=[
            ToolCall(
                name="retrieve_documents",
                arguments={"query": user_message},
                result=retrieval_result,
                latency_ms=latency_ms,
            )
        ],
        latency_ms=latency_ms,
        cost_usd=cost_usd,
    )