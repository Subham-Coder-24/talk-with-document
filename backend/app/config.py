from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> repo root is two levels above "app"
ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Azure OpenAI -------------------------------------------------------
    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_deployment: str
    azure_openai_model: str = "gpt-4o"

    # --- Database -----------------------------------------------------------
    database_url: str
    db_schema: str = Field(
        default="rag", validation_alias=AliasChoices("DB_SCHEMA", "RADAR_DB_SCHEMA")
    )

    # --- Storage ------------------------------------------------------------
    upload_dir: Path = ROOT_DIR / "storage" / "uploads"
    model_cache_dir: Path = ROOT_DIR / "storage" / "models"
    max_upload_mb: int = 100

    # --- Embeddings (open-source, runs locally on CPU via ONNX) -------------
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    embedding_batch_size: int = 32

    # --- RAG ----------------------------------------------------------------
    chunk_size: int = 1000  # characters
    chunk_overlap: int = 150  # characters
    retrieval_top_k: int = 6
    retrieval_candidates: int = 30  # per retriever, before fusion
    history_turns: int = 6  # previous messages sent to the LLM
    max_concurrent_ingestions: int = 2
    describe_images: bool = True  # use GPT-4o vision to index images

    # --- HTTP ---------------------------------------------------------------
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    frontend_dist: Path = ROOT_DIR / "frontend" / "dist"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
