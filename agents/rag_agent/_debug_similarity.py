"""
One-off diagnostic: prints every knowledge-base chunk's cosine similarity score
for a given query, sorted descending. Not part of the agent itself -- just for
picking a real RELEVANCE_THRESHOLD instead of guessing.

Usage (from repo root):
    python agents/rag_agent/_debug_similarity.py "What's your CEO's name?"
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import agents.rag_agent.agent as agent

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python agents/rag_agent/_debug_similarity.py "your question"')
        sys.exit(1)

    query = " ".join(sys.argv[1:])
    agent._ensure_knowledge_base_indexed()
    [query_embedding], _ = agent._embed([query], task_type="RETRIEVAL_QUERY")

    scored = [
        (chunk, agent._cosine_similarity(query_embedding, chunk_embedding))
        for chunk, chunk_embedding in zip(agent._CHUNKS, agent._CHUNK_EMBEDDINGS)
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)

    print(f"Query: {query!r}\n")
    for chunk, score in scored:
        print(f"  {score:.4f}  {chunk['source']}#{chunk['heading']}")