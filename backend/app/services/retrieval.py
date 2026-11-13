"""Hybrid retrieval: dense vectors + Postgres full-text search, fused with RRF.

Dense search uses pgvector when the extension is installed; otherwise an exact
cosine search in NumPy over a per-project in-memory matrix (fine up to a few
hundred thousand chunks per project).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

import numpy as np
from sqlalchemy import bindparam, select, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.db import db_state
from app.models import Chunk, Document
from app.services.embeddings import embedder

log = logging.getLogger(__name__)

RRF_K = 60
_T = f'"{settings.db_schema}".chunks'


@dataclass
class RetrievedChunk:
    chunk_id: int
    document_id: uuid.UUID
    filename: str
    page: int | None
    content: str
    score: float


# --- NumPy fallback index ------------------------------------------------------


@dataclass
class _ProjectMatrix:
    ids: np.ndarray  # int64 [n]
    doc_ids: np.ndarray  # object (uuid) [n]
    matrix: np.ndarray  # float32 [n, dim], L2-normalised


class NumpyVectorIndex:
    def __init__(self) -> None:
        self._cache: dict[uuid.UUID, _ProjectMatrix] = {}
        self._versions: dict[uuid.UUID, int] = {}
        self._locks: dict[uuid.UUID, asyncio.Lock] = {}

    def invalidate(self, project_id: uuid.UUID) -> None:
        self._versions[project_id] = self._versions.get(project_id, 0) + 1
        self._cache.pop(project_id, None)

    async def _load(self, session: AsyncSession, project_id: uuid.UUID) -> _ProjectMatrix:
        cached = self._cache.get(project_id)
        if cached is not None:
            return cached
        lock = self._locks.setdefault(project_id, asyncio.Lock())
        async with lock:
            cached = self._cache.get(project_id)
            if cached is not None:
                return cached
            version = self._versions.get(project_id, 0)
            rows = (
                await session.execute(
                    select(Chunk.id, Chunk.document_id, Chunk.embedding).where(
                        Chunk.project_id == project_id
                    )
                )
            ).all()
            if rows:
                ids = np.fromiter((r[0] for r in rows), dtype=np.int64, count=len(rows))
                doc_ids = np.array([r[1] for r in rows], dtype=object)
                matrix = np.asarray([r[2] for r in rows], dtype=np.float32)
            else:
                ids = np.zeros(0, dtype=np.int64)
                doc_ids = np.zeros(0, dtype=object)
                matrix = np.zeros((0, settings.embedding_dim), dtype=np.float32)
            entry = _ProjectMatrix(ids, doc_ids, matrix)
            # Don't cache if an ingestion finished while we were reading.
            if self._versions.get(project_id, 0) == version:
                self._cache[project_id] = entry
            return entry

    async def search(
        self,
        session: AsyncSession,
        project_id: uuid.UUID,
        qvec: np.ndarray,
        k: int,
        document_ids: list[uuid.UUID] | None,
    ) -> list[tuple[int, float]]:
        pm = await self._load(session, project_id)
        if pm.ids.size == 0:
            return []
        scores = pm.matrix @ qvec
        if document_ids:
            mask = np.isin(pm.doc_ids, np.array(document_ids, dtype=object))
            scores = np.where(mask, scores, -np.inf)
        k = min(k, scores.size)
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]
        return [(int(pm.ids[i]), float(scores[i])) for i in top if np.isfinite(scores[i])]


numpy_index = NumpyVectorIndex()


def invalidate_project(project_id: uuid.UUID) -> None:
    numpy_index.invalidate(project_id)


# --- individual retrievers -----------------------------------------------------


def _doc_filter_sql(document_ids: list[uuid.UUID] | None) -> str:
    return " AND document_id = ANY(:doc_ids)" if document_ids else ""


def _bind_doc_ids(stmt, document_ids):
    if document_ids:
        stmt = stmt.bindparams(bindparam("doc_ids", type_=ARRAY(UUID(as_uuid=True))))
    return stmt


async def _dense_search(
    session: AsyncSession,
    project_id: uuid.UUID,
    qvec: np.ndarray,
    k: int,
    document_ids: list[uuid.UUID] | None,
) -> list[tuple[int, float]]:
    if not db_state.pgvector:
        return await numpy_index.search(session, project_id, qvec, k, document_ids)

    dim = int(settings.embedding_dim)
    vec_expr = f"embedding::vector({dim})"
    stmt = text(
        f"""
        SELECT id, 1 - ({vec_expr} <=> CAST(CAST(:q AS text) AS vector)) AS score
        FROM {_T}
        WHERE project_id = :pid{_doc_filter_sql(document_ids)}
        ORDER BY {vec_expr} <=> CAST(CAST(:q AS text) AS vector)
        LIMIT :k
        """
    )
    stmt = _bind_doc_ids(stmt, document_ids)
    params = {"q": "[" + ",".join(f"{x:.7f}" for x in qvec) + "]", "pid": project_id, "k": k}
    if document_ids:
        params["doc_ids"] = document_ids
    rows = (await session.execute(stmt, params)).all()
    return [(r[0], float(r[1])) for r in rows]


async def _keyword_search(
    session: AsyncSession,
    project_id: uuid.UUID,
    query: str,
    k: int,
    document_ids: list[uuid.UUID] | None,
) -> list[tuple[int, float]]:
    # plainto_tsquery ANDs every term, which is too strict for natural-language
    # questions; rewrite it into an OR query and let ts_rank_cd do the ranking.
    stmt = text(
        f"""
        WITH q AS (
            SELECT replace(plainto_tsquery('english', :query)::text, ' & ', ' | ')::tsquery AS tsq
        )
        SELECT c.id, ts_rank_cd(c.content_tsv, q.tsq) AS score
        FROM {_T} c, q
        WHERE c.project_id = :pid AND c.content_tsv @@ q.tsq{_doc_filter_sql(document_ids).replace("document_id", "c.document_id")}
        ORDER BY score DESC
        LIMIT :k
        """
    )
    stmt = _bind_doc_ids(stmt, document_ids)
    params: dict = {"query": query, "pid": project_id, "k": k}
    if document_ids:
        params["doc_ids"] = document_ids
    rows = (await session.execute(stmt, params)).all()
    return [(r[0], float(r[1])) for r in rows]


# --- public API ----------------------------------------------------------------


def _rrf(*rankings: list[tuple[int, float]]) -> dict[int, float]:
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, (chunk_id, _) in enumerate(ranking):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
    return fused


async def hybrid_search(
    session: AsyncSession,
    project_id: uuid.UUID,
    query: str,
    top_k: int | None = None,
    document_ids: list[uuid.UUID] | None = None,
) -> list[RetrievedChunk]:
    top_k = top_k or settings.retrieval_top_k
    n = max(settings.retrieval_candidates, top_k)

    qvec = await run_in_threadpool(embedder.embed_query, query)
    dense = await _dense_search(session, project_id, qvec, n, document_ids)
    keyword = await _keyword_search(session, project_id, query, n, document_ids)

    fused = _rrf(dense, keyword)
    best = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    if not best:
        return []

    ids = [cid for cid, _ in best]
    rows = (
        await session.execute(
            select(Chunk.id, Chunk.document_id, Chunk.page, Chunk.content, Document.filename)
            .join(Document, Document.id == Chunk.document_id)
            .where(Chunk.id.in_(ids))
        )
    ).all()
    by_id = {r.id: r for r in rows}
    results = []
    for cid, score in best:
        r = by_id.get(cid)
        if r is None:  # deleted between ranking and fetch
            continue
        results.append(
            RetrievedChunk(
                chunk_id=r.id,
                document_id=r.document_id,
                filename=r.filename,
                page=r.page,
                content=r.content,
                score=round(score, 5),
            )
        )
    return results
