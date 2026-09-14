import sqlite3
from pathlib import Path

DB_PATH = Path("trinity.db")

COLUMNS = {
    "timeframe_directions_json": "TEXT",
    "timeframe_scores_json": "TEXT",
}


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    with sqlite3.connect(DB_PATH) as conn:
        current_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(pair_context)")
        }

        for name, column_type in COLUMNS.items():
            if name not in current_columns:
                conn.execute(
                    f"ALTER TABLE pair_context "
                    f"ADD COLUMN {name} {column_type}"
                )
                print(f"ADDED {name}")
            else:
                print(f"EXISTS {name}")

    print("Migration complete.")


if __name__ == "__main__":
    main()