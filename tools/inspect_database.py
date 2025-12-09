import argparse
import sqlite3

DB_FILE = "data/maddieply.db"

def dump_table(table: str) -> None:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        row = cur.fetchone()
        if not row:
            print(f"Table '{table}' not found in {DB_FILE}.")
            return

        cur.execute(f"PRAGMA table_info({table})")
        columns = [c[1] for c in cur.fetchall()]
        cur.execute(f"SELECT * FROM {table}")
        rows = cur.fetchall()

        print(f"DB_FILE: {DB_FILE}")
        print(f"TABLE: {table}")
        print(f"ROWS: {len(rows)}")
        if not rows:
            print("(no data)")
            return
        print("COLUMNS:", ", ".join(columns))
        for idx, r in enumerate(rows, start=1):
            row_dict = {col: r[col] for col in columns}
            print(f"{idx}:", row_dict)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a table in maddieply.db")
    parser.add_argument("table", nargs="?", help="Table name (lowercase)")
    args = parser.parse_args()
    table = (args.table or input("Enter table name: ")).strip().lower()
    if not table:
        parser.error("Table name is required.")
    dump_table(table)


if __name__ == "__main__":
    main()
