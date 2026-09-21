"""fastembed wrapper for nomic-embed-text-v1.5.

Deliberately not sentence-transformers/torch — see docs/tech-stack.md for why. fastembed runs the same
model through ONNX Runtime, keeping the knowledge server's dependency footprint (and install size) away from
the 6-12GB VRAM budget reserved for the actual coding model.
"""

from __future__ import annotations

import os

from fastembed import TextEmbedding

MODEL_NAME = os.getenv("RESYNC_EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v1.5-Q")
EMBEDDING_DIM = 768  # fixed by the model; used to size the LanceDB vector column in store.py

_model: TextEmbedding | None = None
_fallback_mode: bool = False


def get_model() -> TextEmbedding | None:
    """Lazily load the model once per process — loading it per-call would dominate latency for the
    real-time gate's fast-path queries (docs/architecture.md#two-speeds).

    Gracefully falls back if model cannot be loaded (e.g. offline sandbox, firewall timeout).
    """
    global _model, _fallback_mode
    if _fallback_mode or os.getenv("RESYNC_OFFLINE_EMBEDDINGS") == "1":
        return None
    if _model is None:
        import logging
        import threading

        res: TextEmbedding | None = None
        exc_raised: Exception | None = None

        def _init_thread() -> None:
            nonlocal res, exc_raised
            try:
                try:
                    res = TextEmbedding(model_name=MODEL_NAME, local_files_only=True)
                except Exception:
                    res = TextEmbedding(model_name=MODEL_NAME)
            except Exception as e:
                exc_raised = e

        t = threading.Thread(target=_init_thread, daemon=True)
        t.start()
        timeout_sec = float(os.getenv("RESYNC_EMBEDDING_DOWNLOAD_TIMEOUT", "3.0"))
        t.join(timeout=timeout_sec)

        if t.is_alive() or res is None:
            logging.getLogger(__name__).warning(
                "Fastembed model '%s' timed out or unavailable (%s); falling back to zero-vector embeddings.",
                MODEL_NAME,
                exc_raised or "timeout",
            )
            _fallback_mode = True
            return None

        _model = res
    return _model


def embed(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts. fastembed's nomic-embed-text-v1.5 expects a 'search_document:' or
    'search_query:' prefix for best results — callers should prefix appropriately rather than passing raw
    text, since the two prefixes produce different embeddings for the same underlying model."""
    model = get_model()
    if model is None:
        return [[0.0] * EMBEDDING_DIM for _ in texts]
    try:
        return [vector.tolist() for vector in model.embed(texts)]
    except Exception:
        return [[0.0] * EMBEDDING_DIM for _ in texts]


def embed_document(text: str) -> list[float]:
    return embed([f"search_document: {text}"])[0]


def embed_query(text: str) -> list[float]:
    return embed([f"search_query: {text}"])[0]
