from __future__ import annotations

import csv
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SNAPSHOT_PATH = BASE_DIR / "dashboard_snapshot_v2.json"
NOTES_PATH = BASE_DIR / "manual_research_notes.csv"
OUTPUT_PATH = BASE_DIR / "research_context.json"

TIMEFRAMES = ("W1", "D1", "H4", "H1")

PAIR_SET = {
    "AUD/USD",
    "EUR/USD",
    "GBP/USD",
    "NZD/USD",
    "USD/CAD",
    "USD/CHF",
    "USD/JPY",
}

EVIDENCE_TYPES = {"FACT", "OBSERVATION", "EVENT_RISK"}
VERIFICATION_STATUSES = {"VERIFIED", "PENDING", "UNVERIFIED"}
SOURCE_TIERS = {"PRIMARY", "SECONDARY", "CALENDAR", "USER_SUPPLIED"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def parse_utc(value: object) -> datetime | None:
    if value is None or str(value).strip() == "":
        return None

    timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    if timestamp.tzinfo is None:
        raise ValueError(f"Timestamp requires timezone: {value}")

    return timestamp.astimezone(timezone.utc)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def session_name(timestamp: datetime) -> str:
    hour = timestamp.hour

    if 0 <= hour < 7:
        return "ASIA"
    if 7 <= hour < 12:
        return "LONDON"
    if 12 <= hour < 17:
        return "LONDON_NEW_YORK_OVERLAP"
    if 17 <= hour < 22:
        return "NEW_YORK"

    return "OFF_HOURS"


def direction_from_signal(value: object) -> str:
    signal = str(value or "").strip().upper()

    if signal == "LONG":
        return "BULLISH"
    if signal == "SHORT":
        return "BEARISH"

    return "NEUTRAL"


def manual_notes(now: datetime) -> list[dict]:
    if not NOTES_PATH.exists():
        return []

    with NOTES_PATH.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        if reader.fieldnames is None:
            raise ValueError("manual_research_notes.csv has no header row")

        required = {
            "created_at_utc",
            "event_time_utc",
            "currency",
            "pair",
            "category",
            "severity",
            "status",
            "summary",
            "source_url",
            "verified_by",
            "evidence_type",
            "verification_status",
            "source_tier",
        }

        missing = required - set(reader.fieldnames)
        if missing:
            raise ValueError(
                "manual_research_notes.csv missing columns: "
                f"{sorted(missing)}"
            )

        rows = list(reader)

    output = []

    for row in rows:
        row = {
            key: "" if value is None else str(value)
            for key, value in row.items()
        }

        status = row["status"].strip().upper()
        if status not in {"ACTIVE", "PENDING"}:
            continue

        evidence_type = row["evidence_type"].strip().upper()
        verification_status = row["verification_status"].strip().upper()
        source_tier = row["source_tier"].strip().upper()

        if evidence_type not in EVIDENCE_TYPES:
            raise ValueError(
                "Invalid evidence_type in manual_research_notes.csv: "
                f"{evidence_type!r}"
            )

        if verification_status not in VERIFICATION_STATUSES:
            raise ValueError(
                "Invalid verification_status in manual_research_notes.csv: "
                f"{verification_status!r}"
            )

        if source_tier not in SOURCE_TIERS:
            raise ValueError(
                "Invalid source_tier in manual_research_notes.csv: "
                f"{source_tier!r}"
            )

        if evidence_type == "EVENT_RISK" and source_tier != "CALENDAR":
            raise ValueError(
                "EVENT_RISK notes must use source_tier=CALENDAR"
            )

        event_time = parse_utc(row["event_time_utc"])
        minutes_to_event = None
        event_window = "NO_SCHEDULED_EVENT"

        if event_time:
            minutes_to_event = round(
                (event_time - now).total_seconds() / 60,
                1,
            )
            severity = row["severity"].strip().upper()

            if severity == "HIGH" and -60 <= minutes_to_event <= 60:
                event_window = "HIGH_IMPACT_EVENT_WINDOW"
            elif severity == "MEDIUM" and -30 <= minutes_to_event <= 30:
                event_window = "MEDIUM_IMPACT_EVENT_WINDOW"
            elif minutes_to_event > 0:
                event_window = "UPCOMING_EVENT"
            else:
                event_window = "PAST_EVENT"

        output.append(
            {
                "created_at_utc": row["created_at_utc"],
                "event_time_utc": row["event_time_utc"],
                "minutes_to_event": minutes_to_event,
                "event_window": event_window,
                "currency": row["currency"].upper(),
                "pair": row["pair"].upper(),
                "category": row["category"],
                "severity": row["severity"].upper(),
                "status": status,
                "summary": row["summary"],
                "source_url": row["source_url"],
                "verified_by": row["verified_by"],
                "evidence_type": evidence_type,
                "verification_status": verification_status,
                "source_tier": source_tier,
            }
        )

    return sorted(
        output,
        key=lambda item: (
            item["event_time_utc"] == "",
            item["event_time_utc"],
            item["severity"],
        ),
    )


def build() -> dict:
    if not SNAPSHOT_PATH.exists():
        raise FileNotFoundError("dashboard_snapshot_v2.json was not found")

    snapshot_bytes = SNAPSHOT_PATH.read_bytes()
    snapshot = json.loads(snapshot_bytes.decode("utf-8-sig"))
    snapshot_sha256 = hashlib.sha256(snapshot_bytes).hexdigest()

    timeframe_timestamps_utc = {
        label: snapshot.get("timeframes", {})
        .get(label, {})
        .get("timestamp_utc")
        for label in TIMEFRAMES
    }

    now = utc_now()

    freshness = {}
    quality_flags = []

    for label in TIMEFRAMES:
        frame = snapshot.get("timeframes", {}).get(label, {})
        state = str(frame.get("freshness", "NO_DATA"))
        freshness[label] = state

        if state != "FRESH":
            quality_flags.append(
                {
                    "flag": f"{label}_{state}",
                    "severity": "HIGH" if state == "STALE" else "MEDIUM",
                    "summary": f"{label} data freshness is {state}.",
                }
            )

    pairs = []

    for row in snapshot.get("pairs", []):
        pair = str(row.get("pair", ""))
        if pair not in PAIR_SET:
            continue

        frames = row.get("timeframes", {})

        timestamps = [
            str(frames.get(label, {}).get("timestamp_utc", ""))
            for label in TIMEFRAMES
        ]

        timeframe_directions = {
            label: direction_from_signal(
                frames.get(label, {}).get("signal")
            )
            for label in TIMEFRAMES
        }

        timeframe_scores = {
            label: frames.get(label, {}).get("score_diff")
            for label in TIMEFRAMES
        }

        pairs.append(
            {
                "pair": pair,
                "alignment": row.get("alignment", "NO_DATA"),
                "display_status": row.get("display_status", "WAIT"),
                "signal_quality": row.get("signal_quality", "N/A"),
                "h1_score_diff": row.get("strength", {}).get("score_diff"),
                "all_timeframe_timestamps_present": all(timestamps),
                "timeframe_freshness": {
                    label: freshness.get(label, "NO_DATA")
                    for label in TIMEFRAMES
                },
                "timeframe_directions": timeframe_directions,
                "timeframe_scores": timeframe_scores,
            }
        )

    notes = manual_notes(now)

    return {
        "generated_at_utc": now.isoformat(),
        "source_snapshot_generated_at_utc": snapshot.get(
            "generated_at_utc"
        ),
        "source_snapshot_sha256": snapshot_sha256,
        "timeframe_timestamps_utc": timeframe_timestamps_utc,
        "research_only": True,
        "purpose": "Read-only research context. Not a trade instruction.",
        "market_session_utc": session_name(now),
        "timeframe_freshness": freshness,
        "data_quality_flags": quality_flags,
        "pair_context": pairs,
        "manual_notes": notes,
        "manual_note_template": {
            "allowed_status": ["ACTIVE", "PENDING", "ARCHIVED"],
            "allowed_severity": ["LOW", "MEDIUM", "HIGH"],
            "categories": [
                "CENTRAL_BANK",
                "INFLATION",
                "EMPLOYMENT",
                "GDP",
                "GEOPOLITICAL",
                "DATA_QUALITY",
                "NOTE",
            ],
            "evidence_types": [
                "FACT",
                "OBSERVATION",
                "EVENT_RISK",
            ],
            "verification_statuses": [
                "VERIFIED",
                "PENDING",
                "UNVERIFIED",
            ],
            "source_tiers": [
                "PRIMARY",
                "SECONDARY",
                "CALENDAR",
                "USER_SUPPLIED",
            ],
        },
    }


def main() -> None:
    context = build()
    temp = OUTPUT_PATH.with_suffix(".tmp")

    temp.write_text(
        json.dumps(context, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    temp.replace(OUTPUT_PATH)

    logging.info(
        "Saved %s with %s manual notes",
        OUTPUT_PATH.name,
        len(context["manual_notes"]),
    )


if __name__ == "__main__":
    main()