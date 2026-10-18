from __future__ import annotations

from functools import lru_cache

from app.config import EMBED_MODEL


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=EMBED_MODEL)


def embed_documents(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return [vec.tolist() for vec in _model().embed(texts)]


def embed_query(text: str) -> list[float]:
    vectors = list(_model().query_embed([text]))
    if not vectors:
        vectors = list(_model().embed([text]))
    return vectors[0].tolist()
