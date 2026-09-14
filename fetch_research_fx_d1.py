from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

BASE_URL = "https://api.twelvedata.com/time_series"
API_KEY = os.getenv("TWELVEDATA_API_KEY")

SOURCE = "Twelve Data"
ENGINE_VERSION = "m1.6c1_research_fx_d1_v1"
SYMBOLS = (
    "AUD/USD",
    "EUR/USD",
    "GBP/USD",
    "NZD/USD",
    "USD/CAD",
    "USD/CHF",
    "USD/JPY",
)
EXPECTED_PAIRS = set(SYMBOLS)
OUTPUT_FILE = Path("research_fx_d1_source_history.csv")
OUTPUT_SIZE = 5
MAX_BAR_AGE = timedelta(days=1, hours=2)

FIELDNAMES = (
    "snapshot_id",
    "captured_at_utc",
    "engine_version",
    "source",
    "pair",
    "fx_previous_close_timestamp_utc",
    "fx_latest_close_timestamp_utc",
    "previous_close",
    "latest_close",
    "return_pct",
    "timestamps_match",
    "closed_bar_valid",
    "data_status",
    "record_note",
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: str) -> datetime:
    parsed = pd.to_datetime(value, utc=True)
    if not isinstance(parsed, pd.Timestamp):
        raise ValueError(f"Invalid timestamp: {value!r}")
    return parsed.to_pydatetime()


def get_two_closed_bars(values: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    closed: list[dict[str, Any]] = []

    for bar in values:
        bar_open = parse_utc(str(bar["datetime"]))
        if bar_open + timedelta(days=1) <= now:
            closed.append(bar)

        if len(closed) == 2:
            return closed

    raise ValueError("Fewer than two closed D1 bars returned")


def parse_prices(
    pair: str,
    bars: list[dict[str, Any]],
    now: datetime,
) -> dict[str, str]:
    latest_bar, previous_bar = bars[0], bars[1]

    latest_open = parse_utc(str(latest_bar["datetime"]))
    previous_open = parse_utc(str(previous_bar["datetime"]))
    latest_close_time = latest_open + timedelta(days=1)
    previous_close_time = previous_open + timedelta(days=1)

    latest_close = float(latest_bar["close"])
    previous_close = float(previous_bar["close"])

    if latest_close <= 0 or previous_close <= 0:
        raise ValueError("Close prices must be positive")

    latest_age = now - latest_close_time
    if latest_age < timedelta(0):
        raise ValueError("Latest D1 bar is not closed")
    if latest_age > MAX_BAR_AGE:
        raise ValueError(f"Latest D1 bar is stale: age={latest_age}")

    return_pct = ((latest_close / previous_close) - 1.0) * 100.0

    return {
        "pair": pair,
        "fx_previous_close_timestamp_utc": iso_utc(previous_close_time),
        "fx_latest_close_timestamp_utc": iso_utc(latest_close_time),
        "previous_close": f"{previous_close:.10f}",
        "latest_close": f"{latest_close:.10f}",
        "return_pct": f"{return_pct:.10f}",
        "closed_bar_valid": "true",
        "data_status": "CLOSED_VALID",
        "record_note": "",
    }


def fetch_rows(now: datetime) -> list[dict[str, str]]:
    if not API_KEY:
        raise RuntimeError("TWELVEDATA_API_KEY is not set")

    params = {
        "symbol": ",".join(SYMBOLS),
        "interval": "1day",
        "outputsize": OUTPUT_SIZE,
        "order": "desc",
        "timezone": "UTC",
        "format": "JSON",
        "apikey": API_KEY,
    }

    try:
        response = requests.get(BASE_URL, params=params, timeout=30)
    except requests.RequestException as exc:
        raise RuntimeError(f"Request failed: {type(exc).__name__}") from None

    if response.status_code != 200:
        raise RuntimeError(f"API returned HTTP {response.status_code}")

    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError("API returned invalid JSON") from None

    rows: list[dict[str, str]] = []

    for pair in SYMBOLS:
        item = payload.get(pair)
        if not item:
            raise RuntimeError(f"{pair}: missing response object")
        if item.get("status") == "error":
            raise RuntimeError(f"{pair}: API error: {item.get('message')}")

        values = item.get("values")
        if not isinstance(values, list):
            raise RuntimeError(f"{pair}: missing values")

        try:
            bars = get_two_closed_bars(values, now)
            rows.append(parse_prices(pair, bars, now))
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"{pair}: invalid D1 input: {exc}") from None

    actual_pairs = {row["pair"] for row in rows}
    if actual_pairs != EXPECTED_PAIRS or len(rows) != len(EXPECTED_PAIRS):
        missing = sorted(EXPECTED_PAIRS - actual_pairs)
        unexpected = sorted(actual_pairs - EXPECTED_PAIRS)
        raise RuntimeError(
            f"Incomplete source set: missing={missing}, unexpected={unexpected}, "
            f"rows={len(rows)}"
        )

    latest_timestamps = {
        row["fx_latest_close_timestamp_utc"]
        for row in rows
    }
    previous_timestamps = {
        row["fx_previous_close_timestamp_utc"]
        for row in rows
    }

    if len(latest_timestamps) != 1 or len(previous_timestamps) != 1:
        raise RuntimeError(
            "D1 source timestamps do not match across all seven pairs"
        )

    for row in rows:
        row["timestamps_match"] = "true"

    return rows


def validate_history_schema(path: Path) -> None:
    if not path.exists():
        return

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)

    if header != list(FIELDNAMES):
        raise RuntimeError(
            f"{path.name}: header does not match approved research schema"
        )


def snapshot_exists(path: Path, snapshot_id: str) -> bool:
    if not path.exists():
        return False

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return any(row.get("snapshot_id") == snapshot_id for row in reader)


def atomic_append(path: Path, rows: list[dict[str, str]]) -> None:
    existing = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    temp_path = path.with_suffix(".tmp")

    with temp_path.open("w", encoding="utf-8", newline="") as handle:
        if existing:
            handle.write(existing)
            if not existing.endswith("\n"):
                handle.write("\n")

        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        if not existing:
            writer.writeheader()

        writer.writerows(rows)

    temp_path.replace(path)


def print_audit(
    snapshot_id: str,
    rows: list[dict[str, str]],
    write_mode: str,
) -> None:
    print("RESEARCH FX D1 SOURCE AUDIT")
    print(f"snapshot_id: {snapshot_id}")
    print(f"engine_version: {ENGINE_VERSION}")
    print(f"source_pairs: {len(rows)}")
    print(f"latest_d1_timestamp: {rows[0]['fx_latest_close_timestamp_utc']}")
    print(f"previous_d1_timestamp: {rows[0]['fx_previous_close_timestamp_utc']}")
    print(f"timestamps_match: {rows[0]['timestamps_match']}")
    print(f"closed_bars_valid: {all(row['closed_bar_valid'] == 'true' for row in rows)}")
    print(f"write_mode: {write_mode}")
    print("production_impact: NONE")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Research-only D1 source fetcher for FX Strength."
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append validated rows to research_fx_d1_source_history.csv.",
    )
    args = parser.parse_args()

    captured_at = utc_now()
    snapshot_id = (
        f"fxsrc_{captured_at.strftime('%Y%m%dT%H%M%SZ')}_"
        f"{uuid.uuid4().hex[:8]}"
    )

    rows = fetch_rows(captured_at)

    for row in rows:
        row["snapshot_id"] = snapshot_id
        row["captured_at_utc"] = iso_utc(captured_at)
        row["engine_version"] = ENGINE_VERSION
        row["source"] = SOURCE

    validate_history_schema(OUTPUT_FILE)

    if args.append:
        if snapshot_exists(OUTPUT_FILE, snapshot_id):
            raise RuntimeError(f"Duplicate snapshot_id: {snapshot_id}")

        atomic_append(OUTPUT_FILE, rows)
        print_audit(snapshot_id, rows, "APPEND")
    else:
        print_audit(snapshot_id, rows, "DRY RUN")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logging.error("Research FX D1 fetch failed: %s", exc)
        sys.exit(1)