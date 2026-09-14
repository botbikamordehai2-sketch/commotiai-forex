import json
import sqlite3
from pathlib import Path

DB_PATH = Path("trinity.db")
JSON_PATH = Path("research_context.json")

PAIR_CONTEXT_COLUMNS = {
    "timeframe_directions_json": "TEXT",
    "timeframe_scores_json": "TEXT",
}


def as_json(value):
    return json.dumps(
        value if value is not None else {},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def ensure_pair_context_evidence_columns(conn):
    existing_columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(pair_context)")
    }

    for column_name, column_type in PAIR_CONTEXT_COLUMNS.items():
        if column_name not in existing_columns:
            conn.execute(
                f"ALTER TABLE pair_context "
                f"ADD COLUMN {column_name} {column_type}"
            )
            print(f"ADDED missing column: {column_name}")


def validate_timeframe_evidence(item):
    directions = item.get("timeframe_directions")
    scores = item.get("timeframe_scores")

    if not isinstance(directions, dict):
        raise ValueError(
            "Each pair_context item must include "
            "timeframe_directions as an object"
        )

    if not isinstance(scores, dict):
        raise ValueError(
            "Each pair_context item must include "
            "timeframe_scores as an object"
        )

    required_timeframes = {"W1", "D1", "H4", "H1"}

    direction_keys = set(directions)
    score_keys = set(scores)

    if direction_keys != required_timeframes:
        raise ValueError(
            "timeframe_directions must contain exactly "
            f"{sorted(required_timeframes)}; found {sorted(direction_keys)}"
        )

    if score_keys != required_timeframes:
        raise ValueError(
            "timeframe_scores must contain exactly "
            f"{sorted(required_timeframes)}; found {sorted(score_keys)}"
        )

    allowed_directions = {"BULLISH", "BEARISH", "NEUTRAL"}

    invalid_directions = {
        timeframe: value
        for timeframe, value in directions.items()
        if value not in allowed_directions
    }

    if invalid_directions:
        raise ValueError(
            f"Invalid timeframe directions: {invalid_directions}"
        )

    for timeframe, score in scores.items():
        if score is not None and not isinstance(score, (int, float)):
            raise ValueError(
                f"timeframe_scores[{timeframe}] must be numeric or null"
            )

    return directions, scores


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    if not JSON_PATH.exists():
        raise FileNotFoundError(f"JSON not found: {JSON_PATH}")

    with JSON_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)

    required = [
        "generated_at_utc",
        "research_only",
        "timeframe_freshness",
        "data_quality_flags",
        "pair_context",
        "manual_notes",
    ]

    missing = [key for key in required if key not in data]

    if missing:
        raise ValueError(
            f"Missing required JSON fields: {', '.join(missing)}"
        )

    if not isinstance(data["pair_context"], list):
        raise ValueError("pair_context must be a list")

    if not isinstance(data["manual_notes"], list):
        raise ValueError("manual_notes must be a list")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_pair_context_evidence_columns(conn)

        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO research_runs (
                generated_at_utc,
                research_only,
                purpose,
                market_session_utc,
                timeframe_freshness_json,
                data_quality_flags_json,
                source_file
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(generated_at_utc) DO NOTHING
            """,
            (
                data["generated_at_utc"],
                int(bool(data["research_only"])),
                data.get("purpose"),
                data.get("market_session_utc"),
                as_json(data["timeframe_freshness"]),
                as_json(data["data_quality_flags"]),
                JSON_PATH.name,
            ),
        )

        row = cur.execute(
            "SELECT id FROM research_runs WHERE generated_at_utc = ?",
            (data["generated_at_utc"],),
        ).fetchone()

        if row is None:
            raise RuntimeError("Unable to resolve research run after insert")

        run_id = row[0]

        for item in data["pair_context"]:
            pair = item.get("pair")

            if not pair:
                raise ValueError(
                    "Each pair_context item must include pair"
                )

            directions, scores = validate_timeframe_evidence(item)

            cur.execute(
                """
                INSERT INTO pair_context (
                    run_id,
                    pair,
                    alignment,
                    display_status,
                    signal_quality,
                    h1_score_diff,
                    all_timeframe_timestamps_present,
                    timeframe_freshness_json,
                    timeframe_directions_json,
                    timeframe_scores_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, pair) DO UPDATE SET
                    alignment = excluded.alignment,
                    display_status = excluded.display_status,
                    signal_quality = excluded.signal_quality,
                    h1_score_diff = excluded.h1_score_diff,
                    all_timeframe_timestamps_present =
                        excluded.all_timeframe_timestamps_present,
                    timeframe_freshness_json =
                        excluded.timeframe_freshness_json,
                    timeframe_directions_json =
                        excluded.timeframe_directions_json,
                    timeframe_scores_json =
                        excluded.timeframe_scores_json
                """,
                (
                    run_id,
                    pair,
                    item.get("alignment"),
                    item.get("display_status"),
                    item.get("signal_quality"),
                    item.get("h1_score_diff"),
                    (
                        int(bool(item["all_timeframe_timestamps_present"]))
                        if item.get(
                            "all_timeframe_timestamps_present"
                        ) is not None
                        else None
                    ),
                    as_json(item.get("timeframe_freshness")),
                    as_json(directions),
                    as_json(scores),
                ),
            )

        for note in data["manual_notes"]:
            summary = note.get("summary")

            if not summary:
                raise ValueError(
                    "Each manual note must include summary"
                )

            cur.execute(
                """
                INSERT OR IGNORE INTO manual_notes (
                    created_at_utc,
                    event_time_utc,
                    minutes_to_event,
                    event_window,
                    currency,
                    pair,
                    category,
                    severity,
                    status,
                    summary,
                    source_url,
                    verified_by,
                    source_file
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    note.get("created_at_utc"),
                    note.get("event_time_utc"),
                    note.get("minutes_to_event"),
                    note.get("event_window"),
                    note.get("currency"),
                    note.get("pair"),
                    note.get("category"),
                    note.get("severity"),
                    note.get("status"),
                    summary,
                    note.get("source_url"),
                    note.get("verified_by"),
                    JSON_PATH.name,
                ),
            )

    print(
        f"Loaded run_id={run_id}; "
        f"pairs={len(data['pair_context'])}; "
        f"manual_notes_seen={len(data['manual_notes'])}"
    )


if __name__ == "__main__":
    main()