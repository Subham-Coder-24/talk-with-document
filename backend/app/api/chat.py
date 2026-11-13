import json
import logging
import uuid

import anyio
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.projects import get_project_or_404
from app.db import SessionLocal, get_session
from app.models import Conversation, Message
from app.schemas import (
    ChatRequest,
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    ConversationUpdate,
)
from app.services import llm
from app.services.rag import build_messages, condense_question, sources_payload, title_from
from app.services.retrieval import hybrid_search

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])

DEFAULT_TITLE = "New chat"


async def _get_conv_or_404(session: AsyncSession, conversation_id: uuid.UUID) -> Conversation:
    conv = await session.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conv


@router.get("/projects/{project_id}/conversations", response_model=list[ConversationOut])
async def list_conversations(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    await get_project_or_404(session, project_id)
    convs = await session.scalars(
        select(Conversation)
        .where(Conversation.project_id == project_id)
        .order_by(Conversation.updated_at.desc())
    )
    return convs.all()


@router.post(
    "/projects/{project_id}/conversations",
    response_model=ConversationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    project_id: uuid.UUID,
    body: ConversationCreate | None = None,
    session: AsyncSession = Depends(get_session),
):
    await get_project_or_404(session, project_id)
    conv = Conversation(project_id=project_id, title=(body and body.title) or DEFAULT_TITLE)
    session.add(conv)
    await session.commit()
    await session.refresh(conv)
    return conv


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    conv = await session.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(selectinload(Conversation.messages))
    )
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conv


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
async def rename_conversation(
    conversation_id: uuid.UUID,
    body: ConversationUpdate,
    session: AsyncSession = Depends(get_session),
):
    conv = await _get_conv_or_404(session, conversation_id)
    conv.title = body.title.strip()
    await session.commit()
    await session.refresh(conv)
    return conv


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    conv = await _get_conv_or_404(session, conversation_id)
    await session.delete(conv)
    await session.commit()


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: uuid.UUID,
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
):
    """Send a user message and stream the assistant's answer as Server-Sent Events.

    Event types: `sources` (retrieved citations), `token` (answer delta),
    `done` (persisted message id + conversation title), `error`.
    """
    conv = await _get_conv_or_404(session, conversation_id)
    project_id = conv.project_id
    history = list(
        (
            await session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at)
            )
        ).all()
    )

    question = body.content.strip()
    session.add(Message(conversation_id=conversation_id, role="user", content=question))
    if not history and conv.title == DEFAULT_TITLE:
        conv.title = title_from(question)
    conv.updated_at = func.now()
    await session.commit()
    await session.refresh(conv)
    title = conv.title

    async def event_stream():
        parts: list[str] = []
        sources: list[dict] = []
        saved = False

        async def save_answer(content: str) -> uuid.UUID:
            async with SessionLocal() as s:
                msg = Message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=content,
                    sources=sources,
                )
                s.add(msg)
                await s.commit()
                return msg.id

        try:
            async with SessionLocal() as s:
                search_query = await condense_question(history, question)
                chunks = await hybrid_search(
                    s, project_id, search_query, document_ids=body.document_ids
                )
            sources = sources_payload(chunks)
            yield _sse({"type": "sources", "sources": sources, "query": search_query})

            async for token in llm.stream(build_messages(history, question, chunks)):
                parts.append(token)
                yield _sse({"type": "token", "content": token})

            message_id = await save_answer("".join(parts))
            saved = True
            yield _sse({"type": "done", "message_id": str(message_id), "title": title})
        except Exception as exc:
            log.exception("Chat generation failed")
            yield _sse({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
        finally:
            # Client disconnected mid-stream: keep the partial answer.
            if parts and not saved:
                with anyio.CancelScope(shield=True):
                    try:
                        await save_answer("".join(parts) + "\n\n*(response interrupted)*")
                    except Exception:
                        log.exception("Failed to persist partial answer")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
