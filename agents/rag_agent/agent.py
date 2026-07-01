"""
RAG benchmark agent (Phase1 roadmap Section 7).

Implements the AgentAdapter-compatible run_turn(session_state, user_message) contract.
Retrieves the most relevant knowledge-base chunks for the user's question, grounds the
LLM's answer in them, and explicitly says "I don't know" when nothing relevant is found
-- instead of hallucinating a confident wrong answer, which is the specific RAG failure
mode this benchmark agent exists to make testable.

Standalone usage (from the repo root):
    python agents/rag_agent/agent.py "What is the refund policy?"

DEVIATION NOTE (roadmap rule 5): the directory is "rag_agent" (underscore), not
"rag-agent" as drawn in Section 3's tree. Python cannot import a package with a
hyphen in its name via a dotted module path, and Section 6's own example entrypoint
string ('agents.rag_agent.agent:run_turn') already uses the underscore form -- this
just makes the actual directory name consistent with that.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# Make `apps.api.*` importable regardless of how this script is invoked --
# directly as a script, via `python -m`, or dynamically via LocalPythonAdapter's
# importlib.import_module(). Computed relative to this file so it's correct no
# matter the caller's working directory.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np
from google import genai
from google.genai import types

from apps.api.core.config import get_settings
from apps.api.services.adapters.base import AgentTurnResult, ToolCall

CHAT_MODEL = "gemini-2.5-flash"
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSIONS = 768
RELEVANCE_THRESHOLD = 0.60  # calibrated 2026-06: noise floor ~0.55-0.56, real relevance ~0.67+
TOP_K = 3

# Gemini pricing as of mid-2026, USD per 1M tokens (ai.google.dev/gemini-api/docs/pricing).
# Update here if pricing changes -- this is the only place cost math lives.
CHAT_INPUT_COST_PER_M = 0.30
CHAT_OUTPUT_COST_PER_M = 2.50
EMBEDDING_INPUT_COST_PER_M = 0.15

KNOWLEDGE_BASE_DIR = Path(__file__).parent / "knowledge_base" / "docs"

# print(KNOWLEDGE_BASE_DIR)
# print(KNOWLEDGE_BASE_DIR.exists())
# print(list(KNOWLEDGE_BASE_DIR.glob("*.md")))

_settings = get_settings()
_client = genai.Client(api_key=_settings.gemini_api_key)

# Lazily populated on first real run_turn() call, not at import time -- importing
# this module (e.g. for testing _load_chunks/_cosine_similarity) must not burn a
# real embedding API call. Indexed once per process, then cached.
_CHUNKS: list[dict] | None = None
_CHUNK_EMBEDDINGS: list[list[float]] | None = None


def _load_chunks() -> list[dict]:
    """Splits each knowledge-base doc into chunks on markdown '## ' section headers."""
    chunks = []
    for doc_path in sorted(KNOWLEDGE_BASE_DIR.glob("*.md")):
        text = doc_path.read_text(encoding="utf-8")
        sections = text.split("\n## ")
        for section in sections:
            section = section.strip()
            if not section or section.startswith("# "):
                # the first split piece is just the doc's H1 title line with no body
                if section.startswith("# ") and "\n" not in section:
                    continue
            heading = section.split("\n", 1)[0].lstrip("#").strip()
            chunks.append({"source": doc_path.name, "heading": heading, "text": section})
    return chunks


def _embed(texts: list[str], task_type: str) -> tuple[list[list[float]], int]:
    """Returns (embedding vectors, total input tokens used) for cost tracking."""
    response = _client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=texts,
        config=types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=EMBEDDING_DIMENSIONS,
        ),
    )
    total_tokens = sum(int(e.statistics.token_count) for e in response.embeddings if e.statistics)
    return [e.values for e in response.embeddings], total_tokens


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    a_arr, b_arr = np.array(a), np.array(b)
    denom = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
    if denom == 0:
        return 0.0
    return float(np.dot(a_arr, b_arr) / denom)


def _ensure_knowledge_base_indexed() -> None:
    global _CHUNKS, _CHUNK_EMBEDDINGS
    if _CHUNKS is not None:
        return
    _CHUNKS = _load_chunks()
    print(f"Chunks loaded: {len(_CHUNKS)}")
    print(_CHUNKS[:3])
    _CHUNK_EMBEDDINGS, _ = _embed([c["text"] for c in _CHUNKS], task_type="RETRIEVAL_DOCUMENT")


def _retrieve(query: str) -> tuple[list[dict], int]:
    """Returns (relevant chunks above the relevance threshold, query embedding tokens used)."""
    _ensure_knowledge_base_indexed()
    [query_embedding], tokens_used = _embed([query], task_type="RETRIEVAL_QUERY")
    scored = [
        (chunk, _cosine_similarity(query_embedding, chunk_embedding))
        for chunk, chunk_embedding in zip(_CHUNKS, _CHUNK_EMBEDDINGS)
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    relevant = [chunk for chunk, score in scored[:TOP_K] if score >= RELEVANCE_THRESHOLD]
    return relevant, tokens_used


def run_turn(session_state: dict, user_message: str) -> AgentTurnResult:
    start = time.monotonic()
    history: list[dict] = session_state.setdefault("history", [])

    relevant_chunks, embed_tokens = _retrieve(user_message)
    retrieval_result = [f"{c['source']}#{c['heading']}" for c in relevant_chunks]

    if not relevant_chunks:
        # The specific RAG failure mode this benchmark agent exists to catch:
        # admit missing context instead of confidently hallucinating an answer.
        assistant_message = (
            "I don't know -- I couldn't find anything in TrailLight Gear's policy "
            "documents that answers that question."
        )
        input_tokens = output_tokens = 0
    else:
        context_text = "\n\n".join(f"### {c['heading']}\n{c['text']}" for c in relevant_chunks)
        history_text = "\n".join(
            f"User: {turn['user']}\nAssistant: {turn['assistant']}" for turn in history[-3:]
        )
        prompt = (
            "You are a customer support assistant for TrailLight Gear. Answer the "
            "user's question using ONLY the context below. If the context does not "
            "contain the answer, say you don't know -- never guess or make up policy "
            "details.\n\n"
            f"Context:\n{context_text}\n\n"
            f"{('Conversation so far:' + chr(10) + history_text + chr(10) + chr(10)) if history_text else ''}"
            f"User question: {user_message}"
        )
        response = _client.models.generate_content(
            model=CHAT_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        assistant_message = response.text
        input_tokens = response.usage_metadata.prompt_token_count or 0
        output_tokens = response.usage_metadata.candidates_token_count or 0

    history.append({"user": user_message, "assistant": assistant_message})

    cost_usd = (
        (embed_tokens / 1_000_000) * EMBEDDING_INPUT_COST_PER_M
        + (input_tokens / 1_000_000) * CHAT_INPUT_COST_PER_M
        + (output_tokens / 1_000_000) * CHAT_OUTPUT_COST_PER_M
    )
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
        cost_usd=round(cost_usd, 6),
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python agents/rag_agent/agent.py "your question here"')
        sys.exit(1)

    question = " ".join(sys.argv[1:])
    result = run_turn({}, question)
    print(result.assistant_message)
    print(
        f"\n[retrieved: {result.tool_calls[0].result} | "
        f"cost: ${result.cost_usd:.6f} | latency: {result.latency_ms}ms]"
    )