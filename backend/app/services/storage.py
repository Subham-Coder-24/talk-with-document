"""Local-disk file storage. Swap this module for blob storage (e.g. Azure Blob) later."""

import hashlib
import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config import settings

_CHUNK = 1024 * 1024


class FileTooLarge(Exception):
    pass


def project_dir(project_id: uuid.UUID) -> Path:
    return settings.upload_dir / str(project_id)


def safe_suffix(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    # Only keep a short, alphanumeric extension; never trust the client's name for paths.
    return suffix if 1 < len(suffix) <= 10 and suffix[1:].isalnum() else ""


async def save_upload(
    file: UploadFile, project_id: uuid.UUID, document_id: uuid.UUID
) -> tuple[Path, int, str]:
    """Stream an upload to disk. Returns (path, size_bytes, sha256)."""
    target_dir = project_dir(project_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{document_id}{safe_suffix(file.filename or '')}"

    limit = settings.max_upload_mb * 1024 * 1024
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("wb") as out:
            while chunk := await file.read(_CHUNK):
                size += len(chunk)
                if size > limit:
                    raise FileTooLarge(f"exceeds {settings.max_upload_mb} MB limit")
                digest.update(chunk)
                out.write(chunk)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path, size, digest.hexdigest()


def delete_file(path: str | Path) -> None:
    Path(path).unlink(missing_ok=True)


def delete_project_files(project_id: uuid.UUID) -> None:
    shutil.rmtree(project_dir(project_id), ignore_errors=True)
