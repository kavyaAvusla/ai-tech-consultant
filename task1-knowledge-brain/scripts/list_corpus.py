import sqlite3
from pathlib import Path

conn = sqlite3.connect(Path("data/brain.sqlite"))
conn.row_factory = sqlite3.Row
print("PAGES")
for row in conn.execute(
    "SELECT id, status, active, image_count, title, url FROM pages WHERE status='ok' ORDER BY id"
):
    print(f"{row['id']}\t{row['image_count']}\t{row['title']}\n  {row['url']}")
print("\nTEXT SNIPPETS")
for row in conn.execute(
    """
    SELECT pages.id, pages.title, chunks.heading, substr(chunks.text,1,280) AS t
    FROM chunks JOIN pages ON pages.id = chunks.page_id
    WHERE chunks.active=1 AND chunks.chunk_type='text'
    ORDER BY pages.id, chunks.ordinal
    """
):
    print(f"\n[{row['id']}] {row['title']} / {row['heading']}\n{row['t']}")
