"""fastembed wrapper for nomic-embed-text-v1.5.

Deliberately not sentence-transformers/torch — see docs/tech-stack.md for why. fastembed runs the same
model through ONNX Runtime, keeping the knowledge server's dependency footprint (and install size) away from
the 6-12GB VRAM budget reserved for the actual coding model.
"""

from __future__ import annotations

from fastembed import TextEmbedding

MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
EMBEDDING_DIM = 768  # fixed by the model; used to size the LanceDB vector column in store.py

_model: TextEmbedding | None = None


def get_model() -> TextEmbedding:
    """Lazily load the model once per process — loading it per-call would dominate latency for the
    real-time gate's fast-path queries (docs/architecture.md#two-speeds)."""
    global _model
    if _model is None:
        _model = TextEmbedding(model_name=MODEL_NAME)
    return _model


def embed(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts. fastembed's nomic-embed-text-v1.5 expects a 'search_document:' or
    'search_query:' prefix for best results — callers should prefix appropriately rather than passing raw
    text, since the two prefixes produce different embeddings for the same underlying model."""
    return [vector.tolist() for vector in get_model().embed(texts)]


def embed_document(text: str) -> list[float]:
    return embed([f"search_document: {text}"])[0]


def embed_query(text: str) -> list[float]:
    return embed([f"search_query: {text}"])[0]
