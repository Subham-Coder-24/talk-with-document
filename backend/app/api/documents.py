import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import get_project_or_404
from app.db import get_session
from app.models import Document, DocumentStatus, Project
from app.schemas import DocumentOut, SkippedFile, UploadResult
from app.services import ingestion, storage
from app.services.retrieval import invalidate_project

router = APIRouter(prefix="/api", tags=["documents"])

MAX_FILES_PER_REQUEST = 50


async def _get_doc_or_404(session: AsyncSession, document_id: uuid.UUID) -> Document:
    doc = await session.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


@router.get("/projects/{project_id}/documents", response_model=list[DocumentOut])
async def list_documents(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    await get_project_or_404(session, project_id)
    docs = await session.scalars(
        select(Document)
        .where(Document.project_id == project_id)
        .order_by(Document.created_at.desc())
    )
    return docs.all()


@router.post(
    "/projects/{project_id}/documents",
    response_model=UploadResult,
    status_code=status.HTTP_201_CREATED,
)
async def upload_documents(
    project_id: uuid.UUID,
    files: list[UploadFile] = File(..., description="One or more files"),
    session: AsyncSession = Depends(get_session),
):
    await get_project_or_404(session, project_id)
    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"At most {MAX_FILES_PER_REQUEST} files per upload"
        )

    uploaded: list[Document] = []
    skipped: list[SkippedFile] = []
    seen_hashes: set[str] = set()

    for file in files:
        name = Path(file.filename or "untitled").name[:512]
        doc_id = uuid.uuid4()
        try:
            path, size, sha = await storage.save_upload(file, project_id, doc_id)
        except storage.FileTooLarge as exc:
            skipped.append(SkippedFile(filename=name, reason=str(exc)))
            continue
        finally:
            await file.close()

        if size == 0:
            storage.delete_file(path)
            skipped.append(SkippedFile(filename=name, reason="file is empty"))
            continue

        duplicate = sha in seen_hashes or await session.scalar(
            select(Document.id).where(Document.project_id == project_id, Document.sha256 == sha)
        )
        if duplicate:
            storage.delete_file(path)
            skipped.append(SkippedFile(filename=name, reason="already uploaded to this project"))
            continue
        seen_hashes.add(sha)

        doc = Document(
            id=doc_id,
            project_id=project_id,
            filename=name,
            stored_path=str(path),
            content_type=file.content_type or mimetypes.guess_type(name)[0],
            size_bytes=size,
            sha256=sha,
            status=DocumentStatus.PENDING,
        )
        session.add(doc)
        uploaded.append(doc)

    if uploaded:
        await session.execute(
            update(Project).where(Project.id == project_id).values(updated_at=func.now())
        )
    try:
        await session.commit()
    except Exception:
        for doc in uploaded:
            storage.delete_file(doc.stored_path)
        raise

    for doc in uploaded:
        await session.refresh(doc)
        ingestion.enqueue(doc.id)

    return UploadResult(
        uploaded=[DocumentOut.model_validate(d) for d in uploaded], skipped=skipped
    )


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(document_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    return await _get_doc_or_404(session, document_id)


@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    doc = await _get_doc_or_404(session, document_id)
    path = Path(doc.stored_path)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File is missing on the server")
    # inline so PDFs/images open in the browser; filename is preserved for saving.
    return FileResponse(
        path,
        media_type=doc.content_type or "application/octet-stream",
        filename=doc.filename,
        content_disposition_type="inline",
    )


@router.post("/documents/{document_id}/reprocess", response_model=DocumentOut)
async def reprocess_document(
    document_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    doc = await _get_doc_or_404(session, document_id)
    if doc.status in (DocumentStatus.PENDING, DocumentStatus.PROCESSING):
        raise HTTPException(status.HTTP_409_CONFLICT, "Document is already being processed")
    doc.status, doc.error = DocumentStatus.PENDING, None
    await session.commit()
    await session.refresh(doc)
    ingestion.enqueue(doc.id)
    return doc


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    doc = await _get_doc_or_404(session, document_id)
    project_id, stored_path = doc.project_id, doc.stored_path
    await session.delete(doc)  # chunks cascade
    await session.commit()
    storage.delete_file(stored_path)
    invalidate_project(project_id)
