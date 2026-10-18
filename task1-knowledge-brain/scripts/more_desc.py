import sqlite3
conn = sqlite3.connect("data/brain.sqlite")
conn.row_factory = sqlite3.Row
urls = [
    "%12000050864%",
    "%5000682657%",
    "%12000109387%",
]
for like in urls:
    print("\n========", like)
    for row in conn.execute(
        """
        SELECT pages.title, chunks.heading, chunks.text
        FROM chunks JOIN pages ON pages.id=chunks.page_id
        WHERE chunks.active=1 AND chunks.chunk_type='image' AND chunks.vision_status='ok'
          AND pages.url LIKE ?
        """,
        (like,),
    ):
        print("HEADING", row["heading"])
        print(row["text"][:1200])
        print("----")
