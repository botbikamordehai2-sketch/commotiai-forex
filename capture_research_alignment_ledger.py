import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from alignment_classifier import (
    classify_timeframe_directions,
    make_classification_summary,
)

DB_PATH = Path("trinity.db")
LEDGER_PATH = Path("research_alignment_ledger.jsonl")
SNAPSHOT_PATH = Path("dashboard_snapshot_v2.json")

LEDGER_SCOPE = "seven_pair_dashboard_parity_v1"

EXPECTED_PAIRS = {
    "AUD/USD",
    "EUR/USD",
    "GBP/USD",
    "NZD/USD",
    "USD/CAD",
    "USD/CHF",
    "USD/JPY",
}

REQUIRED_TIMEFRAMES = ("W1", "D1", "H4", "H1")
MAX_SNAPSHOT_RUN_DELTA_SECONDS = 1.0

REQUIRED_ALIGNMENT_CLASSES = {
    "FULL_4_OF_4",
    "HIGHER_3_OF_3_H1_OPPOSES",
    "THREE_OF_4_SAME",
    "TWO_VS_TWO",
    "INSUFFICIENT_OR_INVALID",
}


def parse_json(value, default=None):
    if value is None:
        return {} if default is None else default

    if isinstance(value, (dict, list)):
        return value

    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {} if default is None else default


def parse_utc(value, label):
    if value is None or str(value).strip() == "":
        raise RuntimeError(f"{label}: missing timestamp")

    try:
        timestamp = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise RuntimeError(
            f"{label}: invalid timestamp: {value}"
        ) from exc

    if timestamp.tzinfo is None:
        raise RuntimeError(
            f"{label}: timestamp must include timezone: {value}"
        )

    return timestamp.astimezone(timezone.utc)


def table_columns(conn, table_name):
    return {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})")
    }


def select_optional(columns, name, fallback_sql="NULL"):
    if name in columns:
        return name

    return f"{fallback_sql} AS {name}"


def load_latest_run_and_pairs():
    if not DB_PATH.exists():
        raise RuntimeError(f"Database not found: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        run_columns = table_columns(conn, "research_runs")
        pair_columns = table_columns(conn, "pair_context")

        if not run_columns or not pair_columns:
            raise RuntimeError(
                "Required table research_runs or pair_context is missing"
            )

        run_query = f"""
            SELECT
                id,
                {select_optional(run_columns, "generated_at_utc")},
                {select_optional(run_columns, "market_session_utc")},
                {select_optional(
                    run_columns,
                    "timeframe_freshness_json",
                    "'{{}}'"
                )},
                {select_optional(
                    run_columns,
                    "data_quality_flags_json",
                    "'[]'"
                )},
                {select_optional(run_columns, "research_only", "1")},
                {select_optional(run_columns, "purpose")},
                {select_optional(run_columns, "source_file")}
            FROM research_runs
            ORDER BY id DESC
            LIMIT 1
        """

        run = conn.execute(run_query).fetchone()

        if run is None:
            raise RuntimeError("No research_runs found in DB")

        pair_query = f"""
            SELECT
                {select_optional(pair_columns, "pair")},
                {select_optional(pair_columns, "alignment")},
                {select_optional(pair_columns, "display_status")},
                {select_optional(pair_columns, "signal_quality")},
                {select_optional(pair_columns, "h1_score_diff")},
                {select_optional(
                    pair_columns,
                    "all_timeframe_timestamps_present",
                    "0"
                )},
                {select_optional(
                    pair_columns,
                    "timeframe_freshness_json",
                    "'{{}}'"
                )},
                {select_optional(
                    pair_columns,
                    "timeframe_directions_json",
                    "'{{}}'"
                )},
                {select_optional(
                    pair_columns,
                    "timeframe_scores_json",
                    "'{{}}'"
                )}
            FROM pair_context
            WHERE run_id = ?
            ORDER BY pair
        """

        pairs = [
            dict(row)
            for row in conn.execute(
                pair_query,
                (run["id"],),
            ).fetchall()
        ]

        return dict(run), pairs

    finally:
        conn.close()


def load_snapshot():
    if not SNAPSHOT_PATH.exists():
        raise RuntimeError(f"Snapshot not found: {SNAPSHOT_PATH}")

    try:
        snapshot = json.loads(
            SNAPSHOT_PATH.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Unable to read snapshot {SNAPSHOT_PATH}: "
            f"{type(exc).__name__}"
        ) from exc

    if not isinstance(snapshot, dict):
        raise RuntimeError("Snapshot must be a JSON object")

    return snapshot


def all_fresh(freshness):
    return isinstance(freshness, dict) and all(
        freshness.get(timeframe) == "FRESH"
        for timeframe in REQUIRED_TIMEFRAMES
    )


def validate_snapshot(snapshot, run):
    if snapshot.get("read_only") is not True:
        raise RuntimeError("SKIP: dashboard snapshot is not read_only")

    if snapshot.get("analysis_status") != "RESEARCH_ONLY":
        raise RuntimeError(
            "SKIP: dashboard snapshot analysis_status is not "
            "RESEARCH_ONLY"
        )

    snapshot_time = parse_utc(
        snapshot.get("generated_at_utc"),
        "dashboard snapshot generated_at_utc",
    )
    run_time = parse_utc(
        run.get("generated_at_utc"),
        "research run generated_at_utc",
    )

    snapshot_run_id = (
        snapshot.get("research_run_id")
        if snapshot.get("research_run_id") is not None
        else snapshot.get("run_id")
    )

    if (
        snapshot_run_id is not None
        and str(snapshot_run_id) != str(run["id"])
    ):
        raise RuntimeError(
            "SKIP: snapshot run identifier does not match DB run; "
            f"snapshot_run_id={snapshot_run_id!r} "
            f"db_run_id={run['id']!r}"
        )

    timestamp_delta_seconds = abs(
        (snapshot_time - run_time).total_seconds()
    )

    if timestamp_delta_seconds > MAX_SNAPSHOT_RUN_DELTA_SECONDS:
        raise RuntimeError(
            "SKIP: snapshot/DB timestamp delta exceeds allowed "
            f"{MAX_SNAPSHOT_RUN_DELTA_SECONDS:.3f}s; "
            f"delta={timestamp_delta_seconds:.6f}s, "
            f"snapshot={snapshot_time.isoformat()}, "
            f"run={run_time.isoformat()}"
        )

    snapshot_freshness = {
        timeframe: str(
            snapshot.get("timeframes", {})
            .get(timeframe, {})
            .get("freshness", "")
        )
        for timeframe in REQUIRED_TIMEFRAMES
    }

    if not all_fresh(snapshot_freshness):
        raise RuntimeError(
            "SKIP: dashboard snapshot freshness is not fully FRESH: "
            f"{snapshot_freshness}"
        )

    snapshot_pairs = {
        str(item.get("pair", ""))
        for item in snapshot.get("pairs", [])
    }

    if snapshot_pairs != EXPECTED_PAIRS:
        raise RuntimeError(
            "SKIP: dashboard universe does not match ledger universe; "
            f"missing={sorted(EXPECTED_PAIRS - snapshot_pairs)}, "
            f"unexpected={sorted(snapshot_pairs - EXPECTED_PAIRS)}"
        )

    return {
        "source_snapshot_file": SNAPSHOT_PATH.name,
        "source_snapshot_generated_at_utc": snapshot_time.isoformat(),
        "source_snapshot_run_id": snapshot_run_id,
        "source_db_generated_at_utc": run_time.isoformat(),
        "snapshot_db_timestamp_delta_ms": round(
            timestamp_delta_seconds * 1000,
            3,
        ),
        "snapshot_run_linkage": (
            "EXPLICIT_RUN_ID"
            if snapshot_run_id is not None
            else "TIMESTAMP_TOLERANCE_ONLY"
        ),
        "snapshot_timeframe_freshness": snapshot_freshness,
        "dashboard_pair_count": len(snapshot_pairs),
        "dashboard_pairs": sorted(snapshot_pairs),
    }


def existing_source_run_ids():
    if not LEDGER_PATH.exists():
        return set()

    run_ids = set()

    with LEDGER_PATH.open("r", encoding="utf-8") as ledger:
        for line_number, line in enumerate(ledger, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Invalid JSONL at {LEDGER_PATH}:{line_number}: {exc}"
                ) from exc

            source_run_id = record.get(
                "source",
                {},
            ).get("source_run_id")

            if source_run_id is not None:
                run_ids.add(source_run_id)

    return run_ids


def canonical_sha256(record_without_hash):
    canonical = json.dumps(
        record_without_hash,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_directions(pair_name, directions):
    if not isinstance(directions, dict):
        raise RuntimeError(
            f"{pair_name}: timeframe_directions must be an object"
        )

    if set(directions) != set(REQUIRED_TIMEFRAMES):
        raise RuntimeError(
            f"{pair_name}: timeframe_directions must contain exactly "
            f"{list(REQUIRED_TIMEFRAMES)}; found {sorted(directions)}"
        )

    allowed = {"BULLISH", "BEARISH", "NEUTRAL"}

    invalid = {
        timeframe: value
        for timeframe, value in directions.items()
        if value not in allowed
    }

    if invalid:
        raise RuntimeError(
            f"{pair_name}: invalid timeframe directions: {invalid}"
        )


def validate_scores(pair_name, scores):
    if not isinstance(scores, dict):
        raise RuntimeError(
            f"{pair_name}: timeframe_scores must be an object"
        )

    if set(scores) != set(REQUIRED_TIMEFRAMES):
        raise RuntimeError(
            f"{pair_name}: timeframe_scores must contain exactly "
            f"{list(REQUIRED_TIMEFRAMES)}; found {sorted(scores)}"
        )

    for timeframe, score in scores.items():
        if score is not None and (
            not isinstance(score, (int, float))
            or isinstance(score, bool)
        ):
            raise RuntimeError(
                f"{pair_name}: timeframe_scores[{timeframe}] "
                "must be numeric or null"
            )


def validate_and_build_record(run, raw_pairs, snapshot_provenance):
    run_id = run["id"]

    run_freshness = parse_json(
        run.get("timeframe_freshness_json")
    )
    data_quality_flags = parse_json(
        run.get("data_quality_flags_json"),
        default=[],
    )

    if not bool(run.get("research_only")):
        raise RuntimeError(
            f"SKIP run_id={run_id}: research_only is not true"
        )

    if not all_fresh(run_freshness):
        raise RuntimeError(
            f"SKIP run_id={run_id}: run timeframe freshness is not fully "
            f"FRESH: {run_freshness}"
        )

    if data_quality_flags:
        raise RuntimeError(
            f"SKIP run_id={run_id}: data_quality_flags is not empty: "
            f"{data_quality_flags}"
        )

    actual_pairs = [row.get("pair") for row in raw_pairs]
    actual_pair_set = set(actual_pairs)

    if (
        len(raw_pairs) != len(EXPECTED_PAIRS)
        or actual_pair_set != EXPECTED_PAIRS
    ):
        duplicates = sorted(
            pair
            for pair, count in Counter(actual_pairs).items()
            if count > 1
        )

        raise RuntimeError(
            f"SKIP run_id={run_id}: invalid ledger universe; "
            f"count={len(raw_pairs)}, "
            f"missing={sorted(EXPECTED_PAIRS - actual_pair_set)}, "
            f"unexpected={sorted(actual_pair_set - EXPECTED_PAIRS)}, "
            f"duplicates={duplicates}"
        )

    pairs = []

    for raw_pair in raw_pairs:
        pair_name = raw_pair["pair"]

        pair_freshness = parse_json(
            raw_pair.get("timeframe_freshness_json")
        )

        timestamps_present = bool(
            raw_pair.get("all_timeframe_timestamps_present")
        )

        if not timestamps_present:
            raise RuntimeError(
                f"SKIP run_id={run_id}: {pair_name} has missing "
                "timeframe timestamps"
            )

        if pair_freshness and not all_fresh(pair_freshness):
            raise RuntimeError(
                f"SKIP run_id={run_id}: {pair_name} timeframe freshness "
                f"is not fully FRESH: {pair_freshness}"
            )

        directions = parse_json(
            raw_pair.get("timeframe_directions_json")
        )
        scores = parse_json(
            raw_pair.get("timeframe_scores_json")
        )

        validate_directions(pair_name, directions)
        validate_scores(pair_name, scores)

        alignment_class = classify_timeframe_directions(directions)

        if alignment_class not in REQUIRED_ALIGNMENT_CLASSES:
            raise RuntimeError(
                f"SKIP run_id={run_id}: {pair_name} returned unsupported "
                f"alignment_class={alignment_class!r}"
            )

        pairs.append(
            {
                "pair": pair_name,
                "alignment": raw_pair.get("alignment"),
                "display_status": raw_pair.get("display_status"),
                "signal_quality": raw_pair.get("signal_quality"),
                "h1_score_diff": raw_pair.get("h1_score_diff"),
                "all_timeframe_timestamps_present": timestamps_present,
                "timeframe_freshness": (
                    pair_freshness or run_freshness
                ),
                "timeframe_directions": directions,
                "timeframe_scores": scores,
                "alignment_class": alignment_class,
            }
        )

    pairs.sort(key=lambda item: item["pair"])

    classification_summary = make_classification_summary(pairs)

    return {
        "schema_version": "1.2",
        "record_type": "research_context_capture",
        "captured_at_utc": run.get("generated_at_utc"),
        "source": {
            "database": DB_PATH.name,
            "source_run_id": run_id,
            "source_file": run.get("source_file"),
            **snapshot_provenance,
        },
        "universe": {
            "scope": LEDGER_SCOPE,
            "name": f"research_context_{run_id}",
            "expected_pairs": sorted(EXPECTED_PAIRS),
            "expected_pair_count": len(EXPECTED_PAIRS),
            "excluded_dashboard_pairs": [],
        },
        "run_context": {
            "generated_at_utc": run.get("generated_at_utc"),
            "market_session_utc": run.get("market_session_utc"),
            "research_only": bool(run.get("research_only")),
            "purpose": run.get("purpose"),
            "timeframe_freshness": run_freshness,
            "data_quality_flags": data_quality_flags,
        },
        "validation": {
            "expected_pair_count": len(EXPECTED_PAIRS),
            "actual_pair_count": len(pairs),
            "missing_pairs": [],
            "unexpected_pairs": [],
            "all_timeframes_fresh": True,
            "all_pairs_have_timeframe_evidence": True,
            "snapshot_run_same_cycle": True,
            "capture_status": "VALID",
        },
        "pairs": pairs,
        "classification_summary": classification_summary,
        "outcomes": None,
        "statistics": None,
    }


def main():
    run, raw_pairs = load_latest_run_and_pairs()
    run_id = run["id"]

    if run_id in existing_source_run_ids():
        print(
            f"SKIP run_id={run_id}: "
            f"already captured in {LEDGER_PATH.name}"
        )
        return

    snapshot = load_snapshot()
    snapshot_provenance = validate_snapshot(snapshot, run)

    record = validate_and_build_record(
        run,
        raw_pairs,
        snapshot_provenance,
    )

    record["record_sha256"] = canonical_sha256(record)

    line = json.dumps(
        record,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    with LEDGER_PATH.open(
        "a",
        encoding="utf-8",
        newline="\n",
    ) as ledger:
        ledger.write(line + "\n")

    print(
        f"CAPTURED run_id={run_id}: "
        f"one VALID JSONL record with {len(record['pairs'])} pairs"
    )


if __name__ == "__main__":
    main()