import sqlite3
import re
from pathlib import Path

conn = sqlite3.connect("data/brain.sqlite")
conn.row_factory = sqlite3.Row

print("STATUS COUNTS")
print(list(conn.execute(
    "SELECT vision_status, COUNT(*) FROM chunks WHERE chunk_type='image' AND active=1 GROUP BY vision_status"
)))

texts = " ".join(
    r[0].lower()
    for r in conn.execute("SELECT text FROM chunks WHERE active=1 AND chunk_type='text'")
    if r[0]
)

print("\n=== SAMPLE DESCRIPTIONS ===")
rows = conn.execute(
    """
    SELECT pages.title, pages.url, chunks.heading, chunks.text
    FROM chunks JOIN pages ON pages.id = chunks.page_id
    WHERE chunks.active=1 AND chunks.chunk_type='image' AND chunks.vision_status='ok'
    ORDER BY chunks.id
    """
).fetchall()
for row in rows[:3]:
    print("\nTITLE:", row["title"])
    print("URL:", row["url"])
    print("HEADING:", row["heading"])
    print(row["text"][:900])
    print("---")

print("\n=== UNIQUE-ISH IMAGE PHRASES ===")
shown = 0
for row in rows:
    desc = row["text"]
    # pull quoted UI labels
    labels = re.findall(r'"([^"]{6,80})"', desc)
    for label in labels:
        if label.lower() not in texts and shown < 12:
            print(f"LABEL {label!r}")
            print(" page:", row["title"])
            print(" url:", row["url"])
            shown += 1
