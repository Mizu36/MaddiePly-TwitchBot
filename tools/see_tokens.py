import asqlite
import os

# Use the data/ directory for the database
data_dir = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(data_dir, exist_ok=True)
db_path = os.path.join(data_dir, "maddieply.db")

conn = asqlite.connect(db_path)
cur = conn.cursor()

cur.execute("SELECT * FROM tokens;")
rows = cur.fetchall()

if not rows:
    print("No tokens found in the database.")

for row in rows:
    print(row)

conn.close()