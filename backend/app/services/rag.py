"""Chat-with-your-documents orchestration.

1. Rewrite a follow-up question into a standalone search query (uses history).
2. Hybrid retrieval over the project's chunks.
3. Grounded generation with numbered citations, streamed token-by-token.
"""

from __future__ import annotations

import logging

from app.config import settings
from app.models import Message
from app.services import llm
from app.services.retrieval import RetrievedChunk

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a precise assistant that answers questions using the user's uploaded documents.

Rules:
- Base your answer ONLY on the numbered sources provided in the latest message. Do not use outside knowledge for factual claims.
- Cite every factual statement with the source number in square brackets, e.g. [1] or [2][3]. Only cite numbers that exist.
- If the sources do not contain the answer, say clearly that you couldn't find it in the documents, and mention what related information (if any) is available.
- Be concise and well-structured. Use Markdown (headings, bullet lists, tables) when it helps readability.
- If the user greets you or asks something unrelated to the documents, reply briefly and helpfully without citations."""

CONDENSE_PROMPT = """Given the conversation and a follow-up message, rewrite the follow-up as a single standalone search query that contains all the context needed to find relevant passages in documents. Resolve pronouns and references (e.g. "it" -> the thing being discussed), but do NOT add facts or answers from earlier replies. If the follow-up is already standalone, return it unchanged. Output ONLY the query, nothing else.

Conversation:
{history}

Follow-up message: {question}

Standalone query:"""


def _history_messages(history: list[Message]) -> list[dict]:
    recent = history[-settings.history_turns :] if settings.history_turns else []
    return [{"role": m.role, "content": m.content} for m in recent]


async def condense_question(history: list[Message], question: str) -> str:
    if not history:
        return question
    transcript = "\n".join(
        f"{m.role.upper()}: {m.content[:1500]}" for m in history[-settings.history_turns :]
    )
    try:
        rewritten = await llm.complete(
            [
                {
                    "role": "user",
                    "content": CONDENSE_PROMPT.format(history=transcript, question=question),
                }
            ],
            max_tokens=200,
        )
        return rewritten.strip().strip('"') or question
    except Exception:
        log.warning("Question condensing failed; using raw question", exc_info=True)
        return question


def format_sources(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "(No relevant passages were found in the project's documents.)"
    blocks = []
    for i, c in enumerate(chunks, start=1):
        loc = f", page {c.page}" if c.page else ""
        blocks.append(f"[{i}] Source: {c.filename}{loc}\n{c.content}")
    return "\n\n---\n\n".join(blocks)


def build_messages(
    history: list[Message], question: str, chunks: list[RetrievedChunk]
) -> list[dict]:
    user_turn = (
        f"Sources:\n\n{format_sources(chunks)}\n\n"
        f"=====\n\nQuestion: {question}\n\n"
        "Answer using the sources above and cite them like [1]."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        *_history_messages(history),
        {"role": "user", "content": user_turn},
    ]


def sources_payload(chunks: list[RetrievedChunk]) -> list[dict]:
    return [
        {
            "index": i,
            "chunk_id": c.chunk_id,
            "document_id": str(c.document_id),
            "filename": c.filename,
            "page": c.page,
            "content": c.content,
            "score": c.score,
        }
        for i, c in enumerate(chunks, start=1)
    ]


def title_from(question: str) -> str:
    title = " ".join(question.split())
    return title if len(title) <= 60 else title[:57].rstrip() + "..."

