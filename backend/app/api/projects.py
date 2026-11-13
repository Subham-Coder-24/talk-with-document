import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Conversation, Document, Project
from app.schemas import ProjectCreate, ProjectOut, ProjectUpdate, SearchRequest, SourceOut
from app.services import storage
from app.services.rag import sources_payload
from app.services.retrieval import hybrid_search, invalidate_project

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _counts_query():
    doc_count = (
        select(func.count(Document.id))
        .where(Document.project_id == Project.id)
        .correlate(Project)
        .scalar_subquery()
    )
    conv_count = (
        select(func.count(Conversation.id))
        .where(Conversation.project_id == Project.id)
        .correlate(Project)
        .scalar_subquery()
    )
    return select(Project, doc_count.label("dc"), conv_count.label("cc"))


def _out(project: Project, dc: int = 0, cc: int = 0) -> ProjectOut:
    out = ProjectOut.model_validate(project)
    out.document_count, out.conversation_count = dc, cc
    return out


async def get_project_or_404(session: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


@router.get("", response_model=list[ProjectOut])
async def list_projects(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(_counts_query().order_by(Project.updated_at.desc()))).all()
    return [_out(p, dc, cc) for p, dc, cc in rows]


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectCreate, session: AsyncSession = Depends(get_session)):
    project = Project(name=body.name.strip(), description=body.description)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return _out(project)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    row = (await session.execute(_counts_query().where(Project.id == project_id))).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return _out(*row)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID, body: ProjectUpdate, session: AsyncSession = Depends(get_session)
):
    project = await get_project_or_404(session, project_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(project, field, value.strip() if isinstance(value, str) else value)
    await session.commit()
    return await get_project(project_id, session)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    project = await get_project_or_404(session, project_id)
    await session.delete(project)  # FK cascades remove documents, chunks, chats
    await session.commit()
    storage.delete_project_files(project_id)
    invalidate_project(project_id)


@router.post("/{project_id}/search", response_model=list[SourceOut])
async def search_project(
    project_id: uuid.UUID, body: SearchRequest, session: AsyncSession = Depends(get_session)
):
    """Raw retrieval endpoint – handy for debugging relevance."""
    await get_project_or_404(session, project_id)
    chunks = await hybrid_search(session, project_id, body.query, body.top_k, body.document_ids)
    return sources_payload(chunks)
