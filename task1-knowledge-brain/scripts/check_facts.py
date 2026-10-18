import sqlite3

conn = sqlite3.connect("data/brain.sqlite")
for q in [
    "Photos by Pexels",
    "Johnny Cook",
    "44841",
    "info@samplesite.com",
    "Keep log",
    "Return to files list",
]:
    n = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE active=1 AND chunk_type='text' AND instr(text, ?) > 0",
        (q,),
    ).fetchone()[0]
    i = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE active=1 AND chunk_type='image' AND instr(text, ?) > 0",
        (q,),
    ).fetchone()[0]
    print(q, "text", n, "image", i)
