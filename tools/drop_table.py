import argparse
import re
import sqlite3

DB = 'data/maddieply.db'
VALID_TABLE_RE = re.compile(r'^[a-z0-9_]+$')


def drop_table(table: str) -> None:
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    try:
        print(f'Dropping table {table}...')
        cur.execute(f'DROP TABLE IF EXISTS {table}')
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description='Drop a table from maddieply.db')
    parser.add_argument('table', nargs='?', help='Name of the table to drop (lowercase)')
    args = parser.parse_args()

    table = (args.table or input('Enter table name: ')).strip().lower()
    if not table:
        parser.error('Table name is required.')
    if not VALID_TABLE_RE.match(table):
        parser.error('Table name may only contain lowercase letters, numbers, and underscores.')

    drop_table(table)


if __name__ == '__main__':
    main()