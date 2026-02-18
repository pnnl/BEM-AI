from __future__ import annotations

from typing import Any

import httpx


def _doc_text(row: dict[str, Any]) -> str:
    return " ".join(
        filter(None, [row.get("title"), row.get("snippet"), row.get("content")])
    )


def _fallback_score(query: str, text: str) -> float:
    q_tokens = [x for x in query.lower().split() if x]
    hay = text.lower()
    return float(sum(hay.count(token) for token in q_tokens))


def bm25_scores(query: str, rows: list[dict[str, Any]]) -> list[float]:
    docs = [_doc_text(r) for r in rows]
    try:
        from rank_bm25 import BM25Okapi

        tokenized = [d.lower().split() for d in docs]
        bm25 = BM25Okapi(tokenized)
        return [float(x) for x in bm25.get_scores(query.lower().split())]
    except Exception:
        return [_fallback_score(query, d) for d in docs]


async def jina_rerank(
    client: httpx.AsyncClient,
    query: str,
    rows: list[dict[str, Any]],
    api_key: str,
    top_k: int,
) -> list[tuple[int, float]]:
    docs = [_doc_text(r) for r in rows]
    resp = await client.post(
        "https://api.jina.ai/v1/rerank",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "jina-reranker-v2-base-multilingual",
            "query": query,
            "documents": docs,
            "top_n": top_k,
        },
    )
    if resp.status_code == 401:
        raise ValueError("Jina rerank authentication failed (401).")
    if resp.status_code >= 400:
        raise RuntimeError(f"Jina rerank failed with status {resp.status_code}.")
    results = resp.json().get("results") or []
    return [(int(r["index"]), float(r.get("relevance_score", 0.0))) for r in results]


async def cohere_rerank(
    client: httpx.AsyncClient,
    query: str,
    rows: list[dict[str, Any]],
    api_key: str,
    top_k: int,
) -> list[tuple[int, float]]:
    docs = [_doc_text(r) for r in rows]
    resp = await client.post(
        "https://api.cohere.com/v2/rerank",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "rerank-v3.5",
            "query": query,
            "documents": docs,
            "top_n": top_k,
        },
    )
    if resp.status_code == 401:
        raise ValueError("Cohere rerank authentication failed (401).")
    if resp.status_code >= 400:
        raise RuntimeError(f"Cohere rerank failed with status {resp.status_code}.")
    results = resp.json().get("results") or []
    return [(int(r["index"]), float(r.get("relevance_score", 0.0))) for r in results]
