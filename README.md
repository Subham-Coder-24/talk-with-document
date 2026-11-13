# DocChat — chat with your documents (RAG)

Create projects, upload any number of files into each, and ask questions. Answers come from **Azure OpenAI** (GPT-4o), grounded in your files using **hybrid retrieval** and **open-source local embeddings**, with clickable citations.

```
frontend/  React + Vite + TypeScript + Tailwind  (projects, uploads, chat UI)
backend/   FastAPI + SQLAlchemy (async) + Postgres (ingestion, retrieval, chat API)
storage/   uploads/<project_id>/<document_id>.<ext>   and   models/ (embedding model cache)
```

## Architecture

```
Upload ──► save to storage/uploads ──► Document(status=pending)
              │ background task (bounded concurrency)
              ▼
     parse (pdf/docx/pptx/xlsx/csv/html/json/text/code;  images → GPT-4o vision OCR+description)
              ▼
     chunk (structure-aware, ~1000 chars, 150 overlap, page numbers kept)
              ▼
     embed (BAAI/bge-small-en-v1.5 via fastembed/ONNX, CPU, 384-d)
              ▼
     Postgres  rag.chunks (content, embedding real[], tsvector GIN)  → status=ready

Question ──► condense follow-up with chat history (GPT-4o)
         ──► hybrid search  = dense cosine  +  Postgres full-text  → Reciprocal Rank Fusion
         ──► prompt with numbered sources → GPT-4o streamed over SSE → saved with citations
```

**Vector search backend** is picked automatically at startup:

| pgvector installed? | dense search                                           |
| ------------------- | ------------------------------------------------------ |
| yes                 | in-database `embedding::vector <=> query` (pgvector)   |
| no (current setup)  | exact cosine in NumPy over a per-project cached matrix |

Embeddings are stored as `real[]` either way, so installing pgvector later needs no migration. `GET /api/health` shows which backend is active.

## Prerequisites

- Python 3.12 via [uv](https://docs.astral.sh/uv/) (`uv` picks 3.12 automatically from `backend/.python-version`)
- Node 20+
- PostgreSQL 14+ (tables are created in the schema set by `RADAR_DB_SCHEMA`, default `rag`)
- An Azure OpenAI chat deployment (vision-capable such as gpt-4o, if you want image indexing)

## Setup

```powershell
copy .env.example .env      # then fill in the values

cd backend;  uv sync;        cd ..
cd frontend; npm install;    cd ..
```

`AZURE_OPENAI_ENDPOINT` can be either style:
- `https://<resource>.openai.azure.com/openai/v1` (v1 API; `AZURE_OPENAI_API_VERSION` is ignored)
- `https://<resource>.openai.azure.com` (classic; uses `AZURE_OPENAI_API_VERSION`)

`AZURE_OPENAI_DEPLOYMENT` is the deployment name sent as `model`.

The embedding model (~130 MB) is downloaded from Hugging Face to `storage/models` on first start.

## Run

**Development** (hot reload on both sides):

```powershell
./dev.ps1
# or manually:
cd backend;  uv run uvicorn app.main:app --reload --port 8000
cd frontend; npm run dev          # http://localhost:5173 (proxies /api to :8000)
```

**Single process** (FastAPI serves the built UI):

```powershell
cd frontend; npm run build; cd ..
cd backend;  uv run uvicorn app.main:app --port 8000      # http://localhost:8000
```

API docs: http://localhost:8000/docs

## Tests

```powershell
cd backend; uv run pytest
```

## API overview

| Method | Path                                          | Purpose                                     |
| ------ | --------------------------------------------- | ------------------------------------------- |
| GET    | `/api/projects`                               | list projects (with file/chat counts)       |
| POST   | `/api/projects`                               | create project                              |
| PATCH / DELETE | `/api/projects/{id}`                  | rename / delete (cascades files, chats)     |
| GET    | `/api/projects/{id}/documents`                | list files + ingestion status               |
| POST   | `/api/projects/{id}/documents`                | multipart upload, field `files` (1..50)     |
| GET    | `/api/documents/{id}/download`                | original file                               |
| POST   | `/api/documents/{id}/reprocess`               | retry a failed ingestion                    |
| DELETE | `/api/documents/{id}`                         | delete file + its chunks                    |
| POST   | `/api/projects/{id}/search`                   | raw hybrid retrieval (debug relevance)      |
| GET/POST | `/api/projects/{id}/conversations`          | list / create chats                         |
| GET/PATCH/DELETE | `/api/conversations/{id}`           | messages / rename / delete                  |
| POST   | `/api/conversations/{id}/messages`            | ask; **SSE** stream of `sources`, `token`, `done`, `error` |

`messages` accepts `{"content": "...", "document_ids": [...]}`. `document_ids` is optional and limits retrieval to the files selected in the UI.

## Supported files

PDF (text layer), DOCX, PPTX (incl. speaker notes), XLSX, CSV/TSV, HTML, JSON, Markdown/TXT, source code, and any other UTF-8 text. Images (PNG/JPG/WEBP/GIF) are transcribed and described by GPT-4o vision. Legacy `.doc/.ppt/.xls` and scanned PDFs without a text layer are reported as failed with a reason. Duplicate files (same SHA-256) within a project are skipped.

## Production notes / next steps

- **Auth & multi-tenancy:** there is no login yet. Add auth (e.g. Entra ID / OIDC) and an `owner_id` on projects.
- **pgvector:** install it on the Postgres server (Windows build: see the [pgvector README](https://github.com/pgvector/pgvector#windows)), restart the API, and it is picked up automatically. At large scale add an HNSW expression index: `CREATE INDEX ON rag.chunks USING hnsw ((embedding::vector(384)) vector_cosine_ops);`
- **Ingestion queue:** ingestion runs in-process. For several API instances, move `ingestion.ingest_document` behind a real queue (Celery/RQ/Azure Queue). The NumPy cache is per-process, so use pgvector when scaling out.
- **Storage:** `services/storage.py` is the only module that touches disk; swap it for Azure Blob Storage.
- **Migrations:** tables are created on startup with `create_all`; adopt Alembic before changing the schema.
- **OCR for scanned PDFs:** render pages to images and reuse `llm.describe_image`, or add Azure Document Intelligence.
- **Changing the embedding model:** set `EMBEDDING_MODEL` and `EMBEDDING_DIM`, then reprocess all documents.
