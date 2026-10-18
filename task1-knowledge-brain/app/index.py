from __future__ import annotations

import sqlite3

from app import store
from app.db import utcnow
from app.embedder import embed_documents

BATCH = 32


def sync_index(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT chunks.id, chunks.text, chunks.heading, chunks.chunk_type,
               chunks.content_hash, chunks.embedded_hash, chunks.active,
               chunks.image_url, pages.url, pages.title
        FROM chunks
        JOIN pages ON pages.id = chunks.page_id
        """
    ).fetchall()

    to_embed: list[sqlite3.Row] = []
    keep_ids: set[str] = set()
    for row in rows:
        cid = store.chunk_id(row["id"])
        if row["active"]:
            keep_ids.add(cid)
            if row["embedded_hash"] != row["content_hash"]:
                to_embed.append(row)
        else:
            conn.execute(
                "UPDATE chunks SET embedded_hash = NULL, updated_at = ? WHERE id = ?",
                (utcnow(), row["id"]),
            )

    knowledge_rows = conn.execute("SELECT id FROM knowledge_records").fetchall()
    for row in knowledge_rows:
        keep_ids.add(store.knowledge_id(row["id"]))

    stale = [item for item in store.all_ids() if item not in keep_ids]
    store.delete_ids(stale)

    indexed = 0
    now = utcnow()
    for start in range(0, len(to_embed), BATCH):
        batch = to_embed[start : start + BATCH]
        texts = [
            f"{row['title'] or ''}\n{row['heading'] or ''}\n{row['text']}"
            for row in batch
        ]
        vectors = embed_documents(texts)
        store.upsert(
            ids=[store.chunk_id(row["id"]) for row in batch],
            documents=texts,
            embeddings=vectors,
            metadatas=[
                {
                    "url": row["url"],
                    "title": row["title"] or "",
                    "heading": row["heading"] or "",
                    "chunk_type": row["chunk_type"],
                    "image_url": row["image_url"] or "",
                    "sqlite_id": row["id"],
                    "kind": "chunk",
                }
                for row in batch
            ],
        )
        for row in batch:
            conn.execute(
                "UPDATE chunks SET embedded_hash = ?, updated_at = ? WHERE id = ?",
                (row["content_hash"], now, row["id"]),
            )
            indexed += 1
    conn.commit()
    return {"indexed": indexed, "deleted_from_index": len(stale)}


def upsert_knowledge(
    record_id: int,
    question: str,
    answer: str,
    url: str,
) -> None:
    text = f"Resolved knowledge\nQuestion: {question}\nAnswer: {answer}"
    vector = embed_documents([text])[0]
    store.upsert(
        ids=[store.knowledge_id(record_id)],
        documents=[text],
        embeddings=[vector],
        metadatas=[
            {
                "url": url,
                "title": "Resolved escalation",
                "heading": question[:180],
                "chunk_type": "knowledge",
                "image_url": "",
                "sqlite_id": record_id,
                "kind": "knowledge",
            }
        ],
    )
