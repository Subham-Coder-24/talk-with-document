"""Local open-source embeddings (fastembed / ONNX Runtime, CPU-only, no torch)."""

from __future__ import annotations

import logging
import threading

import numpy as np

from app.config import settings

log = logging.getLogger(__name__)


class Embedder:
    def __init__(self, model_name: str, cache_dir: str, batch_size: int, expected_dim: int):
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.batch_size = batch_size
        self.expected_dim = expected_dim
        self._model = None
        self._lock = threading.Lock()

    def _get(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from fastembed import TextEmbedding

                    log.info("Loading embedding model %s ...", self.model_name)
                    model = TextEmbedding(self.model_name, cache_dir=self.cache_dir)
                    dim = len(next(iter(model.query_embed("dimension probe"))))
                    if dim != self.expected_dim:
                        raise RuntimeError(
                            f"Embedding model {self.model_name} produces {dim}-dim vectors but "
                            f"EMBEDDING_DIM={self.expected_dim}. Update EMBEDDING_DIM and re-index."
                        )
                    self._model = model
                    log.info("Embedding model ready (dim=%s)", dim)
        return self._model

    def warmup(self) -> None:
        self._get()

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        """Blocking – run in a worker thread. Returns L2-normalised float32 [n, dim]."""
        if not texts:
            return np.zeros((0, self.expected_dim), dtype=np.float32)
        vecs = np.asarray(
            list(self._get().passage_embed(texts, batch_size=self.batch_size)), dtype=np.float32
        )
        return _normalize(vecs)

    def embed_query(self, text: str) -> np.ndarray:
        vec = np.asarray(next(iter(self._get().query_embed(text))), dtype=np.float32)
        return _normalize(vec[None, :])[0]


def _normalize(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return m / norms


embedder = Embedder(
    settings.embedding_model,
    str(settings.model_cache_dir),
    settings.embedding_batch_size,
    settings.embedding_dim,
)
