from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = BASE_DIR / "dashboard_snapshot.json"

TIMEFRAMES = {
    "D1": {
        "path": BASE_DIR / "signals_1d.csv",
        "max_age_minutes": 1560,
    },
    "H4": {
        "path": BASE_DIR / "signals_4h.csv",
        "max_age_minutes": 480,
    },
    "H1": {
        "path": BASE_DIR / "signals_1h.csv",
        "max_age_minutes": 180,
    },
}

EXPECTED_PAIRS = {
    "EUR/USD",
    "GBP/USD",
    "NZD/USD",
    "USD/CHF",
    "USD/JPY",
}

REQUIRED_COLUMNS = {
    "pair",
    "timestamp",
    "pair_change",
    "base_currency",
    "quote_currency",
    "base_score",
    "quote_score",
    "score_diff",
    "signal",
}

VALID_SIGNALS = {"LONG", "SHORT", "NEUTRAL"}


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )


def parse_timestamp(value: str, label: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label}: invalid timestamp: {value}") from exc

    if timestamp.tzinfo is None:
        raise ValueError(f"{label}: timestamp must include timezone: {value}")

    return timestamp.astimezone(timezone.utc)


def freshness_state(age_minutes: float, max_age_minutes: int) -> str:
    if age_minutes <= max_age_minutes:
        return "FRESH"
    if age_minutes <= max_age_minutes * 2:
        return "AGING"
    return "STALE"


def load_timeframe(label: str, config: dict) -> dict:
    path = config["path"]

    if not path.exists():
        raise FileNotFoundError(f"{label}: file not found: {path.name}")

    df = pd.read_csv(path)

    missing_columns = sorted(REQUIRED_COLUMNS - set(df.columns))
    if missing_columns:
        raise ValueError(f"{label}: missing columns: {missing_columns}")

    if len(df) != len(EXPECTED_PAIRS):
        raise ValueError(
            f"{label}: expected {len(EXPECTED_PAIRS)} rows, found {len(df)}"
        )

    duplicate_pairs = sorted(
        df.loc[df["pair"].duplicated(), "pair"].astype(str).unique().tolist()
    )
    if duplicate_pairs:
        raise ValueError(f"{label}: duplicate pairs: {duplicate_pairs}")

    actual_pairs = set(df["pair"].astype(str))
    missing_pairs = sorted(EXPECTED_PAIRS - actual_pairs)
    unexpected_pairs = sorted(actual_pairs - EXPECTED_PAIRS)

    if missing_pairs or unexpected_pairs:
        raise ValueError(
            f"{label}: invalid pairs; missing={missing_pairs}, "
            f"unexpected={unexpected_pairs}"
        )

    signals = set(df["signal"].astype(str))
    invalid_signals = sorted(signals - VALID_SIGNALS)
    if invalid_signals:
        raise ValueError(f"{label}: invalid signal values: {invalid_signals}")

    timestamps = df["timestamp"].astype(str).unique().tolist()
    if len(timestamps) != 1:
        raise ValueError(
            f"{label}: expected one shared timestamp, found {timestamps}"
        )

    timestamp_utc = parse_timestamp(timestamps[0], label)
    now_utc = datetime.now(timezone.utc)
    age_minutes = round((now_utc - timestamp_utc).total_seconds() / 60, 2)

    if age_minutes < 0:
        raise ValueError(f"{label}: timestamp is in the future: {timestamps[0]}")

    rows = {}
    for row in df.to_dict(orient="records"):
        pair = str(row["pair"])
        rows[pair] = {
            "pair": pair,
            "timestamp_utc": str(row["timestamp"]),
            "signal": str(row["signal"]),
            "pair_change": float(row["pair_change"]),
            "base_currency": str(row["base_currency"]),
            "quote_currency": str(row["quote_currency"]),
            "base_score": float(row["base_score"]),
            "quote_score": float(row["quote_score"]),
            "score_diff": float(row["score_diff"]),
        }

    return {
        "label": label,
        "source_file": path.name,
        "timestamp_utc": timestamp_utc.isoformat(),
        "rows": len(df),
        "age_minutes": age_minutes,
        "max_age_minutes": config["max_age_minutes"],
        "freshness": freshness_state(age_minutes, config["max_age_minutes"]),
        "signals": rows,
    }


def alignment_status(d1: str, h4: str, h1: str) -> tuple[str, str, str]:
    signals = [d1, h4, h1]

    if signals == ["LONG", "LONG", "LONG"]:
        return "ALIGNED_LONG", "LONG", "HIGH"

    if signals == ["SHORT", "SHORT", "SHORT"]:
        return "ALIGNED_SHORT", "SHORT", "HIGH"

    if signals == ["NEUTRAL", "NEUTRAL", "NEUTRAL"]:
        return "ALIGNED_NEUTRAL", "WAIT", "N/A"

    return "CONFLICT", "WAIT", "N/A"


def build_pairs(timeframes: dict) -> list[dict]:
    pairs = []

    for pair in sorted(EXPECTED_PAIRS):
        d1 = timeframes["D1"]["signals"][pair]
        h4 = timeframes["H4"]["signals"][pair]
        h1 = timeframes["H1"]["signals"][pair]

        alignment, final_status, quality = alignment_status(
            d1["signal"],
            h4["signal"],
            h1["signal"],
        )

        pairs.append(
            {
                "pair": pair,
                "d1_bias": d1["signal"],
                "h4_bias": h4["signal"],
                "h1_bias": h1["signal"],
                "alignment": alignment,
                "final_status": final_status,
                "signal_quality": quality,
                "strength": {
                    "base_currency": h1["base_currency"],
                    "base_score": h1["base_score"],
                    "quote_currency": h1["quote_currency"],
                    "quote_score": h1["quote_score"],
                    "score_diff": h1["score_diff"],
                    "source_timeframe": "H1",
                },
                "timeframes": {
                    "D1": d1,
                    "H4": h4,
                    "H1": h1,
                },
            }
        )

    return pairs


def main() -> None:
    configure_logging()

    timeframes = {
        label: load_timeframe(label, config)
        for label, config in TIMEFRAMES.items()
    }

    snapshot = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dashboard_version": "v1",
        "read_only": True,
        "timeframes": {
            label: {
                key: value
                for key, value in data.items()
                if key != "signals"
            }
            for label, data in timeframes.items()
        },
        "pairs": build_pairs(timeframes),
    }

    temp_path = OUTPUT_PATH.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temp_path.replace(OUTPUT_PATH)

    logging.info(
        "Saved %s with %s pairs",
        OUTPUT_PATH.name,
        len(snapshot["pairs"]),
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logging.error("Dashboard snapshot build failed: %s", exc)
        sys.exit(1)