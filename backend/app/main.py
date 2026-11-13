import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app.api import chat, documents, projects
from app.config import settings
from app.db import db_state, engine, init_db
from app.services import ingestion
from app.services.embeddings import embedder

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
)
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.model_cache_dir.mkdir(parents=True, exist_ok=True)
    await init_db()
    # Load the embedding model up-front so the first upload/question isn't slow.
    await run_in_threadpool(embedder.warmup)
    resumed = await ingestion.resume_pending()
    if resumed:
        log.info("Re-queued %d unfinished document(s)", resumed)
    yield
    await engine.dispose()


app = FastAPI(title="DocChat RAG API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(documents.router)
app.include_router(chat.router)


@app.get("/api/health", tags=["meta"])
async def health():
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "vector_backend": "pgvector" if db_state.pgvector else "numpy",
        "embedding_model": settings.embedding_model,
        "llm_deployment": settings.azure_openai_deployment,
    }


# Serve the built React app (frontend/dist) when present – single-process deploys.
if settings.frontend_dist.is_dir():
    app.mount(
        "/assets", StaticFiles(directory=settings.frontend_dist / "assets"), name="assets"
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (settings.frontend_dist / full_path).resolve()
        if (
            full_path
            and candidate.is_file()
            and candidate.is_relative_to(settings.frontend_dist.resolve())
        ):
            return FileResponse(candidate)
        return FileResponse(settings.frontend_dist / "index.html")
