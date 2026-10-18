import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(".").resolve()))
from app.db import get_conn, utcnow
from app.ingest import run_ingest
from app.rag import search

CHANGE = "https://support.brilliantdirectories.com/support/solutions/articles/12000098757-how-to-remove-post-image-gray-background"
REMOVE = "https://support.brilliantdirectories.com/support/solutions/articles/12000104780-album-photos-api-how-to-edit-album-images-with-api-calls"
TOKEN = "SIMULATED_KB_TOKEN_9f3a"


def counts(conn, url):
    page = conn.execute(
        "SELECT id, status, active, content_hash FROM pages WHERE url=?", (url,)
    ).fetchone()
    chunks = conn.execute(
        """
        SELECT COUNT(*) AS n,
               SUM(CASE WHEN active=1 THEN 1 ELSE 0 END) AS active_n,
               SUM(CASE WHEN active=0 THEN 1 ELSE 0 END) AS inactive_n
        FROM chunks WHERE page_id=?
        """,
        (page["id"],),
    ).fetchone()
    return dict(page), dict(chunks)


def main() -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE pages SET ingested_lastmod='2000-01-01T00:00:00+00:00', updated_at=? WHERE url=?",
            (utcnow(), CHANGE),
        )
        before_change = counts(conn, CHANGE)
        before_remove = counts(conn, REMOVE)
    print("BEFORE change", before_change)
    print("BEFORE remove", before_remove)

    result = run_ingest(
        limit=5,
        existing_only=True,
        exclude_urls=[REMOVE],
        mutate_url=CHANGE,
        mutate_token=TOKEN,
    )
    print("INGEST", result)

    with get_conn() as conn:
        after_change = counts(conn, CHANGE)
        after_remove = counts(conn, REMOVE)
        token_hits = conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE active=1 AND instr(text, ?) > 0",
            (TOKEN,),
        ).fetchone()[0]
        hashes = conn.execute(
            """
            SELECT content_hash, COUNT(*) c FROM chunks
            WHERE page_id=(SELECT id FROM pages WHERE url=?) AND active=1
            GROUP BY content_hash HAVING c > 1
            """,
            (CHANGE,),
        ).fetchall()
    print("AFTER change", after_change)
    print("AFTER remove", after_remove)
    print("token_active_chunks", token_hits, "duplicate_active_hashes", list(hashes))

    token_search = search("What is SIMULATED_KB_TOKEN_9f3a used for in Brilliant Directories?")
    print("SEARCH TOKEN top", [
        ((h["metadata"] or {}).get("url"), round(h["similarity"], 4), h["id"])
        for h in token_search[:3]
    ])
    removed_search = search("How do I edit album images with the Album Photos API?")
    print("SEARCH REMOVED top", [
        ((h["metadata"] or {}).get("url"), round(h["similarity"], 4))
        for h in removed_search[:5]
    ])
    removed_urls = [(h["metadata"] or {}).get("url") for h in removed_search]
    print("removed_url_in_results", REMOVE in removed_urls)


if __name__ == "__main__":
    main()
