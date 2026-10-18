from __future__ import annotations

from functools import lru_cache

from app.config import CHROMA_DIR

COLLECTION = "knowledge"


@lru_cache(maxsize=1)
def collection():
    import chromadb

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client.get_or_create_collection(
        name=COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )


def chunk_id(sqlite_id: int) -> str:
    return f"chunk-{sqlite_id}"


def knowledge_id(record_id: int) -> str:
    return f"knowledge-{record_id}"


def upsert(
    ids: list[str],
    documents: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict],
) -> None:
    if not ids:
        return
    collection().upsert(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )


def delete_ids(ids: list[str]) -> None:
    if not ids:
        return
    collection().delete(ids=ids)


def all_ids() -> set[str]:
    result = collection().get(include=[])
    return set(result.get("ids") or [])


def count() -> int:
    return collection().count()


def query(embedding: list[float], top_k: int) -> dict:
    return collection().query(
        query_embeddings=[embedding],
        n_results=max(top_k, 1),
        include=["documents", "metadatas", "distances"],
        where={"kind": "chunk"},
    )
