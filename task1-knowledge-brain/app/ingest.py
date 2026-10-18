from __future__ import annotations

import argparse
import sqlite3
from typing import Iterable

from app.config import CRAWL_LIMIT, VISION_MAX_IMAGES, VISION_MAX_PER_PAGE, redact
from app.db import get_conn, utcnow
from app.http_client import PoliteClient
from app.index import sync_index
from app.parse import ParsedArticle, chunk_hash, page_content_hash, parse_article_html
from app.sitemap import fetch_article_urls, screenshot_preference_score
from app.vision import VisionUnavailable, describe_image


def upsert_sitemap(conn: sqlite3.Connection, articles: list[tuple[str, str | None]]) -> int:
    now = utcnow()
    seen = {url for url, _ in articles}
    for url, lastmod in articles:
        row = conn.execute("SELECT id FROM pages WHERE url = ?", (url,)).fetchone()
        if row:
            conn.execute(
                """
                UPDATE pages
                SET sitemap_lastmod = ?, active = 1,
                    status = CASE WHEN status = 'removed' THEN 'pending' ELSE status END,
                    updated_at = ?
                WHERE url = ?
                """,
                (lastmod, now, url),
            )
        else:
            conn.execute(
                """
                INSERT INTO pages (url, sitemap_lastmod, status, active, created_at, updated_at)
                VALUES (?, ?, 'pending', 1, ?, ?)
                """,
                (url, lastmod, now, now),
            )
    removed = 0
    for row in conn.execute(
        "SELECT id, url FROM pages WHERE active = 1"
    ).fetchall():
        if row["url"] not in seen:
            conn.execute(
                """
                UPDATE pages
                SET active = 0, status = 'removed', updated_at = ?
                WHERE id = ?
                """,
                (now, row["id"]),
            )
            conn.execute(
                "UPDATE chunks SET active = 0, updated_at = ? WHERE page_id = ?",
                (now, row["id"]),
            )
            removed += 1
    conn.commit()
    return removed


def pages_needing_fetch(
    conn: sqlite3.Connection, limit: int, *, existing_only: bool = False
) -> list[sqlite3.Row]:
    extra = "AND status = 'ok' AND fetched_at IS NOT NULL" if existing_only else ""
    rows = conn.execute(
        f"""
        SELECT * FROM pages
        WHERE active = 1
          {extra}
          AND (
                status IN ('pending', 'error', 'fetching')
                OR content_hash IS NULL
                OR (
                    sitemap_lastmod IS NOT NULL
                    AND COALESCE(ingested_lastmod, '') != sitemap_lastmod
                )
              )
        """
    ).fetchall()
    ranked = sorted(
        rows,
        key=lambda r: screenshot_preference_score(r["url"], r["image_count"]),
        reverse=True,
    )
    return ranked[:limit]


def replace_chunks(
    conn: sqlite3.Connection,
    page_id: int,
    parsed: ParsedArticle,
    image_payloads: list[tuple[str, str, str, str, bool, str]],
) -> None:
    now = utcnow()
    keep_hashes: list[str] = []
    ordinal = 0
    for chunk in parsed.text_chunks:
        digest = chunk_hash("text", chunk.heading, "", chunk.text)
        keep_hashes.append(digest)
        _upsert_chunk(
            conn,
            page_id,
            ordinal,
            "text",
            chunk.heading,
            chunk.text,
            None,
            None,
            False,
            digest,
            now,
            vision_status=None,
        )
        ordinal += 1
    for heading, image_url, alt, text, unsure, vision_status in image_payloads:
        digest = chunk_hash("image", heading, image_url, "")
        keep_hashes.append(digest)
        _upsert_chunk(
            conn,
            page_id,
            ordinal,
            "image",
            heading,
            text,
            image_url,
            alt,
            unsure,
            digest,
            now,
            vision_status=vision_status,
        )
        ordinal += 1
    if keep_hashes:
        placeholders = ",".join("?" * len(keep_hashes))
        conn.execute(
            f"""
            UPDATE chunks
            SET active = 0, updated_at = ?
            WHERE page_id = ? AND content_hash NOT IN ({placeholders})
            """,
            [now, page_id, *keep_hashes],
        )
    else:
        conn.execute(
            "UPDATE chunks SET active = 0, updated_at = ? WHERE page_id = ?",
            (now, page_id),
        )


def _upsert_chunk(
    conn: sqlite3.Connection,
    page_id: int,
    ordinal: int,
    chunk_type: str,
    heading: str,
    text: str,
    image_url: str | None,
    image_alt: str | None,
    unsure: bool,
    digest: str,
    now: str,
    vision_status: str | None = None,
) -> None:
    existing = conn.execute(
        "SELECT id, text FROM chunks WHERE page_id = ? AND content_hash = ?",
        (page_id, digest),
    ).fetchone()
    if existing:
        text_changed = existing["text"] != text
        conn.execute(
            """
            UPDATE chunks
            SET ordinal = ?, text = ?, image_alt = ?, vision_unsure = ?,
                vision_status = COALESCE(?, vision_status),
                active = 1, embedded_hash = CASE WHEN ? THEN NULL ELSE embedded_hash END,
                updated_at = ?
            WHERE id = ?
            """,
            (
                ordinal,
                text,
                image_alt,
                int(unsure),
                vision_status,
                int(text_changed),
                now,
                existing["id"],
            ),
        )
        return
    conn.execute(
        """
        INSERT INTO chunks (
            page_id, ordinal, chunk_type, heading, text, image_url, image_alt,
            vision_unsure, vision_status, content_hash, active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (
            page_id,
            ordinal,
            chunk_type,
            heading,
            text,
            image_url,
            image_alt,
            int(unsure),
            vision_status,
            digest,
            now,
            now,
        ),
    )


def ingest_page(
    conn: sqlite3.Connection,
    client: PoliteClient,
    page: sqlite3.Row,
    vision_budget: list[int],
    vision_ok: list[int],
    *,
    mutate_url: str | None = None,
    mutate_token: str | None = None,
) -> str:
    now = utcnow()
    conn.execute(
        """
        UPDATE pages
        SET status = 'fetching', fetch_attempts = fetch_attempts + 1, updated_at = ?
        WHERE id = ?
        """,
        (now, page["id"]),
    )
    conn.commit()
    try:
        response = client.get_text(page["url"])
        parsed = parse_article_html(response.text, str(response.url))
        if mutate_url and mutate_token and page["url"] == mutate_url:
            if parsed.text_chunks:
                parsed.text_chunks[0].text += f" {mutate_token}"
            parsed.body_html += mutate_token
        content_hash = page_content_hash(parsed)
        unchanged = page["content_hash"] == content_hash and page["status"] == "ok"
        image_payloads: list[tuple[str, str, str, str, bool, str]] = []
        if not unchanged:
            per_page = 0
            for image in parsed.images:
                alt = image.alt or ""
                status = "pending"
                if vision_budget[0] > 0 and per_page < VISION_MAX_PER_PAGE:
                    try:
                        text, status = describe_image(client, conn, image.url)
                        vision_budget[0] -= 1
                        per_page += 1
                        if status in {"ok", "unsure"}:
                            vision_ok[0] += 1
                    except VisionUnavailable as exc:
                        vision_budget[0] = 0
                        extra = f" Alt text: {alt}." if alt else ""
                        text = (
                            f"Screenshot from article.{extra} "
                            f"UNSURE: vision paused ({exc}). "
                            f"Source image: {image.url}"
                        )
                        status = "failed"
                else:
                    extra = f" Alt text: {alt}." if alt else ""
                    text = (
                        f"Screenshot from article.{extra} "
                        "Vision description not generated this run. "
                        f"Source image: {image.url}"
                    )
                    status = "pending"
                    if alt:
                        text = (
                            f"Screenshot from article. Visible alt text: {alt}. "
                            f"Source image: {image.url}"
                        )
                unsure = status in {"unsure", "failed"}
                image_payloads.append((image.heading, image.url, alt, text, unsure, status))
            replace_chunks(conn, page["id"], parsed, image_payloads)
        conn.execute(
            """
            UPDATE pages
            SET canonical_url = ?, title = ?, content_hash = ?, status = 'ok',
                http_status = ?, error = NULL, image_count = ?, fetched_at = ?,
                parsed_at = ?, ingested_lastmod = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                parsed.canonical_url,
                parsed.title,
                content_hash,
                response.status_code,
                len(parsed.images),
                now,
                now,
                page["sitemap_lastmod"],
                now,
                page["id"],
            ),
        )
        conn.commit()
        if unchanged:
            return "skipped"
        if page["content_hash"]:
            return "updated"
        return "added"
    except Exception as exc:
        conn.execute(
            """
            UPDATE pages
            SET status = 'error', error = ?, updated_at = ?
            WHERE id = ?
            """,
            (redact(f"{type(exc).__name__}: {exc}"), utcnow(), page["id"]),
        )
        conn.commit()
        return "failed"


def run_vision_pass(conn: sqlite3.Connection, *, model: str = "claude-haiku-5-5") -> dict[str, int]:
    stats = {"described": 0, "failed": 0, "unsure": 0, "skipped_tiny": 0}
    rows = conn.execute(
        """
        SELECT chunks.id, chunks.image_url, chunks.heading, chunks.vision_status,
               chunks.text, pages.url AS page_url
        FROM chunks
        JOIN pages ON pages.id = chunks.page_id
        WHERE chunks.active = 1 AND pages.active = 1 AND pages.status = 'ok'
          AND chunks.chunk_type = 'image' AND chunks.image_url IS NOT NULL
        ORDER BY pages.id, chunks.ordinal
        """
    ).fetchall()
    per_page: dict[str, int] = {}
    budget = VISION_MAX_IMAGES
    with PoliteClient() as client:
        for row in rows:
            status = row["vision_status"] or ""
            if status in {"ok", "unsure", "skipped_tiny"}:
                continue
            page_url = row["page_url"]
            if per_page.get(page_url, 0) >= VISION_MAX_PER_PAGE or budget <= 0:
                continue
            try:
                text, new_status = describe_image(
                    client, conn, row["image_url"], model=model
                )
            except VisionUnavailable as exc:
                print(f"vision stopped: {exc}")
                break
            budget -= 1
            per_page[page_url] = per_page.get(page_url, 0) + 1
            if new_status in {"ok", "unsure"}:
                stats["described"] += 1
            if new_status == "unsure":
                stats["unsure"] += 1
            elif new_status == "failed":
                stats["failed"] += 1
            elif new_status == "skipped_tiny":
                stats["skipped_tiny"] += 1
            conn.execute(
                """
                UPDATE chunks
                SET text = ?, vision_unsure = ?, vision_status = ?,
                    embedded_hash = NULL, updated_at = ?
                WHERE id = ?
                """,
                (
                    text,
                    int(new_status in {"unsure", "failed"}),
                    new_status,
                    utcnow(),
                    row["id"],
                ),
            )
            conn.commit()
            print(f"  vision {new_status}: {page_url}")
    return stats


def run_ingest(
    limit: int,
    index_only: bool = False,
    *,
    vision_only: bool = False,
    existing_only: bool = False,
    exclude_urls: list[str] | None = None,
    mutate_url: str | None = None,
    mutate_token: str | None = None,
) -> dict[str, int]:
    counts = {
        "added": 0,
        "updated": 0,
        "removed": 0,
        "failed": 0,
        "skipped": 0,
        "vision_described": 0,
        "indexed": 0,
        "deleted_from_index": 0,
    }
    with get_conn() as conn:
        started = utcnow()
        run_id = conn.execute(
            "INSERT INTO ingest_runs (started_at, limit_n) VALUES (?, ?)",
            (started, limit),
        ).lastrowid
        conn.commit()
        vision_ok = [0]
        if vision_only:
            vision_stats = run_vision_pass(conn)
            counts["vision_described"] = vision_stats["described"]
            counts["vision_failed"] = vision_stats["failed"]
            counts["vision_unsure"] = vision_stats["unsure"]
            counts["vision_skipped_tiny"] = vision_stats["skipped_tiny"]
            print(
                "VISION "
                f"described={vision_stats['described']} failed={vision_stats['failed']} "
                f"unsure={vision_stats['unsure']} skipped_tiny={vision_stats['skipped_tiny']}"
            )
        elif not index_only:
            with PoliteClient() as client:
                articles = fetch_article_urls(client)
                if exclude_urls:
                    skip = set(exclude_urls)
                    articles = [item for item in articles if item[0] not in skip]
                counts["removed"] = upsert_sitemap(conn, articles)
                queue = pages_needing_fetch(
                    conn, limit, existing_only=existing_only
                )
                vision_budget = [VISION_MAX_IMAGES]
                print(
                    f"Fetching up to {len(queue)} article pages "
                    f"(sitemap articles={len(articles)})"
                )
                for page in queue:
                    result = ingest_page(
                        conn,
                        client,
                        page,
                        vision_budget,
                        vision_ok,
                        mutate_url=mutate_url,
                        mutate_token=mutate_token,
                    )
                    counts[result] += 1
                    print(f"  {result}: {page['url']}")
            counts["vision_described"] = vision_ok[0]
        else:
            counts["vision_described"] = 0
        index_counts = sync_index(conn)
        counts["indexed"] = index_counts["indexed"]
        counts["deleted_from_index"] = index_counts["deleted_from_index"]
        conn.execute(
            """
            UPDATE ingest_runs
            SET finished_at = ?, added = ?, updated = ?, removed = ?,
                failed = ?, skipped = ?, vision_described = ?,
                indexed = ?, deleted_from_index = ?
            WHERE id = ?
            """,
            (
                utcnow(),
                counts["added"],
                counts["updated"],
                counts["removed"],
                counts["failed"],
                counts["skipped"],
                counts["vision_described"],
                counts["indexed"],
                counts["deleted_from_index"],
                run_id,
            ),
        )
        conn.commit()
    return counts


def print_report(counts: dict[str, int]) -> None:
    print("INGEST COUNTS")
    print(
        "added={added} updated={updated} removed={removed} failed={failed} "
        "skipped={skipped} vision_described={vision_described} "
        "indexed={indexed} deleted_from_index={deleted_from_index}".format(
            indexed=counts.get("indexed", 0),
            deleted_from_index=counts.get("deleted_from_index", 0),
            **{k: counts.get(k, 0) for k in ("added", "updated", "removed", "failed", "skipped", "vision_described")},
        )
    )
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT url, title, status, image_count,
                   (SELECT COUNT(*) FROM chunks c
                    WHERE c.page_id = pages.id AND c.active = 1) AS chunks,
                   (SELECT COUNT(*) FROM chunks c
                    WHERE c.page_id = pages.id AND c.active = 1
                      AND c.chunk_type = 'image') AS image_chunks
            FROM pages
            WHERE fetched_at IS NOT NULL
            ORDER BY fetched_at DESC
            LIMIT 50
            """
        ).fetchall()
        print("\nFETCHED PAGES")
        for i, row in enumerate(rows, 1):
            title = (row["title"] or "")[:70]
            print(
                f"{i:02d}. [{row['status']}] images={row['image_count'] or 0} "
                f"chunks={row['chunks']} img_chunks={row['image_chunks']}\n"
                f"    {title}\n    {row['url']}"
            )
        totals = conn.execute(
            """
            SELECT
              SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) AS active_pages,
              SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) AS ok_pages,
              SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error_pages,
              SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_pages
            FROM pages
            """
        ).fetchone()
        chunk_totals = conn.execute(
            """
            SELECT
              SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) AS active_chunks,
              SUM(CASE WHEN active = 1 AND chunk_type = 'text' THEN 1 ELSE 0 END) AS text_chunks,
              SUM(CASE WHEN active = 1 AND chunk_type = 'image' THEN 1 ELSE 0 END) AS image_chunks
            FROM chunks
            """
        ).fetchone()
        vision_stats = conn.execute(
            """
            SELECT COUNT(*) AS n,
                   AVG(latency_ms) AS avg_ms,
                   SUM(input_tokens) AS in_tok,
                   SUM(output_tokens) AS out_tok,
                   SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS errors
            FROM llm_calls WHERE purpose = 'vision'
            """
        ).fetchone()
        print("\nMANIFEST")
        print(
            f"active_pages={totals['active_pages']} ok={totals['ok_pages']} "
            f"error={totals['error_pages']} pending={totals['pending_pages']}"
        )
        print(
            f"active_chunks={chunk_totals['active_chunks']} "
            f"text={chunk_totals['text_chunks']} image={chunk_totals['image_chunks']}"
        )
        print(
            f"vision_calls={vision_stats['n']} avg_latency_ms={int(vision_stats['avg_ms'] or 0)} "
            f"input_tokens={vision_stats['in_tok'] or 0} output_tokens={vision_stats['out_tok'] or 0} "
            f"errors={vision_stats['errors'] or 0}"
        )


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Crawl Brilliant Directories support articles (resumable)."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=CRAWL_LIMIT,
        help="Max article pages to fetch this run (default from CRAWL_LIMIT).",
    )
    parser.add_argument(
        "--index-only",
        action="store_true",
        help="Skip crawling; embed new/changed chunks into Chroma.",
    )
    parser.add_argument(
        "--vision-only",
        action="store_true",
        help="Caption existing image chunks (skips tiny icons; respects caps).",
    )
    parser.add_argument(
        "--existing-only",
        action="store_true",
        help="Only refetch already ingested pages that look stale.",
    )
    parser.add_argument("--exclude-url", action="append", default=[])
    parser.add_argument("--mutate-url", default=None)
    parser.add_argument("--mutate-token", default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)
    counts = run_ingest(
        args.limit,
        index_only=args.index_only,
        vision_only=args.vision_only,
        existing_only=args.existing_only,
        exclude_urls=args.exclude_url,
        mutate_url=args.mutate_url,
        mutate_token=args.mutate_token,
    )
    print_report(counts)


if __name__ == "__main__":
    main()
