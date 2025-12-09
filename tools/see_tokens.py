import asqlite
import os
from pathlib import Path

# Use the data/ directory for the database next to the project root
data_dir = Path(__file__).resolve().parent.parent / "data"
data_dir.mkdir(exist_ok=True)
db_path = data_dir / "maddieply.db"

conn = asqlite.connect(str(db_path))
cur = conn.cursor()

cur.execute("SELECT * FROM tokens;")
rows = cur.fetchall()

if not rows:
    print("No tokens found in the database.")

for row in rows:
    print(row)

conn.close()