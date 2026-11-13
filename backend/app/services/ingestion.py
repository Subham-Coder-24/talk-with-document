"""Background ingestion: parse -> chunk -> embed -> store.

Runs in-process with asyncio tasks and a concurrency limit. For multi-instance
deployments, replace `enqueue` with a real queue (Celery/RQ/Azure Queue) – the
`ingest_document` function is already self-contained and idempotent.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from sqlalchemy import delete, insert, select, update
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.db import SessionLocal
from app.models import Chunk, Document, DocumentStatus
from app.services import llm
from app.services.chunking import chunk_sections
from app.services.embeddings import embedder
from app.services.parsers import Section, UnsupportedFile, is_image, parse_file
from app.services.retrieval import invalidate_project

log = logging.getLogger(__name__)

_semaphore = asyncio.Semaphore(settings.max_concurrent_ingestions)
_tasks: set[asyncio.Task] = set()
_INSERT_BATCH = 500


class IngestionError(Exception):
    pass


def enqueue(document_id: uuid.UUID) -> None:
    task = asyncio.create_task(_run(document_id), name=f"ingest-{document_id}")
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _run(document_id: uuid.UUID) -> None:
    async with _semaphore:
        try:
            await ingest_document(document_id)
        except Exception:  # never let a background task die silently
            log.exception("Unexpected ingestion failure for %s", document_id)


async def _set_status(document_id: uuid.UUID, status: str, **fields) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(Document).where(Document.id == document_id).values(status=status, **fields)
        )
        await session.commit()


async def _extract(path: Path) -> list[Section]:
    if is_image(path):
        if not settings.describe_images:
            raise UnsupportedFile("Image indexing is disabled (DESCRIBE_IMAGES=false).")
        description = await llm.describe_image(path)
        return [Section(f"[Image content]\n{description}")]
    return await run_in_threadpool(parse_file, path)


async def ingest_document(document_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            return
        project_id, filename, path = doc.project_id, doc.filename, Path(doc.stored_path)

    await _set_status(document_id, DocumentStatus.PROCESSING, error=None)
    log.info("Ingesting %s (%s)", filename, document_id)

    try:
        if not path.exists():
            raise IngestionError("Stored file is missing on the server.")
        sections = await _extract(path)
        chunks = chunk_sections(sections, settings.chunk_size, settings.chunk_overlap)
        if not chunks:
            raise IngestionError("No text could be extracted from this file.")

        # Prefix the filename so the embedding carries document-level context.
        embed_inputs = [f"{filename}\n\n{c.text}" for c in chunks]
        vectors = await run_in_threadpool(embedder.embed_passages, embed_inputs)

        async with SessionLocal() as session:
            # Bail out quietly if the document was deleted while we were working.
            if await session.scalar(select(Document.id).where(Document.id == document_id)) is None:
                return
            await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
            rows = [
                {
                    "document_id": document_id,
                    "project_id": project_id,
                    "chunk_index": i,
                    "page": c.page,
                    "content": c.text,
                    "embedding": vectors[i].tolist(),
                }
                for i, c in enumerate(chunks)
            ]
            for start in range(0, len(rows), _INSERT_BATCH):
                await session.execute(insert(Chunk), rows[start : start + _INSERT_BATCH])
            await session.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(status=DocumentStatus.READY, num_chunks=len(rows), error=None)
            )
            await session.commit()
        invalidate_project(project_id)
        log.info("Ingested %s: %d chunks", filename, len(chunks))

    except (UnsupportedFile, IngestionError) as exc:
        await _set_status(document_id, DocumentStatus.FAILED, error=str(exc), num_chunks=0)
        log.warning("Could not ingest %s: %s", filename, exc)
    except Exception as exc:
        await _set_status(
            document_id,
            DocumentStatus.FAILED,
            error=f"Processing error: {type(exc).__name__}: {exc}"[:2000],
            num_chunks=0,
        )
        log.exception("Failed to ingest %s", filename)


async def resume_pending() -> int:
    """Re-queue documents left pending/processing by a previous run (e.g. after a crash)."""
    async with SessionLocal() as session:
        ids = (
            await session.scalars(
                select(Document.id).where(
                    Document.status.in_([DocumentStatus.PENDING, DocumentStatus.PROCESSING])
                )
            )
        ).all()
    for doc_id in ids:
        enqueue(doc_id)
    return len(ids)
