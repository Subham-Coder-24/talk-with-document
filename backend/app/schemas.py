import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Projects ---------------------------------------------------------------
class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class ProjectOut(ORM):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    document_count: int = 0
    conversation_count: int = 0


# --- Documents --------------------------------------------------------------
class DocumentOut(ORM):
    id: uuid.UUID
    project_id: uuid.UUID
    filename: str
    content_type: str | None
    size_bytes: int
    status: str
    error: str | None
    num_chunks: int
    created_at: datetime
    updated_at: datetime


class SkippedFile(BaseModel):
    filename: str
    reason: str


class UploadResult(BaseModel):
    uploaded: list[DocumentOut]
    skipped: list[SkippedFile]


# --- Retrieval / chat -------------------------------------------------------
class SourceOut(BaseModel):
    index: int  # citation number shown to the user, e.g. [1]
    chunk_id: int
    document_id: uuid.UUID
    filename: str
    page: int | None
    content: str
    score: float


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=50)
    document_ids: list[uuid.UUID] | None = None


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ConversationOut(ORM):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class MessageOut(ORM):
    id: uuid.UUID
    role: str
    content: str
    sources: list[SourceOut] | None
    created_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class ChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    # Optionally restrict retrieval to a subset of the project's documents.
    document_ids: list[uuid.UUID] | None = None
