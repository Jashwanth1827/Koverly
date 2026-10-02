"""Retrieval service (RAG) with strict tenant isolation.

All retrieval queries are filtered by ``family_id`` — a user can never
retrieve another family's chunks. Embeddings are compared with cosine
similarity in Python, which is adequate for per-family corpora; a Postgres
deployment can swap in a pgvector index behind the same function signature.
"""

from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import SourceRef
from app.ai.factory import get_ai_provider
from app.models.document import Document, DocumentChunk
from app.utils.text import lexical_overlap


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def retrieve(
    db: AsyncSession,
    *,
    family_id: str,
    query: str,
    top_k: int = 5,
    policy_id: str | None = None,
) -> list[SourceRef]:
    """Return the most relevant chunks, scoped to one family."""
    provider = get_ai_provider()
    query_vec = (await provider.embed([query]))[0]

    stmt = (
        select(DocumentChunk, Document.original_filename)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            DocumentChunk.family_id == family_id,  # tenant isolation
            Document.status == "processed",
        )
    )
    if policy_id:
        stmt = stmt.where(DocumentChunk.policy_id == policy_id)

    rows = (await db.execute(stmt)).all()
    if not rows:
        return []

    scored = []
    for chunk, filename in rows:
        # Combine embedding similarity with lexical overlap. Hashing embeddings
        # can cancel to ~0 for short queries (signed-hash collisions), which
        # would drop a chunk that genuinely contains the answer; lexical
        # overlap keeps such chunks retrievable. Swap for a real embedding
        # model in production and the lexical term simply becomes a tiebreaker.
        emb = _cosine(query_vec, chunk.embedding or [])
        lex = lexical_overlap(query, chunk.content)
        score = emb + 0.5 * lex
        scored.append((score, emb, lex, chunk, filename))
    scored.sort(key=lambda x: x[0], reverse=True)

    results: list[SourceRef] = []
    for score, emb, lex, chunk, filename in scored[:top_k]:
        if score <= 0:
            continue
        results.append(
            SourceRef(
                document_id=chunk.document_id,
                document_name=filename,
                page_number=chunk.page_number,
                snippet=chunk.content[:600],
            )
        )
    return results
