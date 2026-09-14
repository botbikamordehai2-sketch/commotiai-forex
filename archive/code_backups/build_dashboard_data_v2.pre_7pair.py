from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = BASE_DIR / "dashboard_snapshot_v2.json"
PERFORMANCE_REPORT = BASE_DIR / "performance_report.csv"
PERFORMANCE_DETAIL = BASE_DIR / "performance_detail.csv"

TIMEFRAMES = {
    "W1": {
        "path": BASE_DIR / "pair_changes_1w.csv",
        "max_age_minutes": 11520,
        "methodology": "weekly_pair_price_change",
    },
    "D1": {
        "path": BASE_DIR / "signals_1d.csv",
        "max_age_minutes": 1560,
        "methodology": "currency_strength_signal",
    },
    "H4": {
        "path": BASE_DIR / "signals_4h.csv",
        "max_age_minutes": 480,
        "methodology": "currency_strength_signal",
    },
    "H1": {
        "path": BASE_DIR / "signals_1h.csv",
        "max_age_minutes": 180,
        "methodology": "currency_strength_signal",
    },
}

EXPECTED_PAIRS = {"EUR/USD", "GBP/USD", "NZD/USD", "USD/CHF", "USD/JPY"}

REQUIRED_SIGNAL_COLUMNS = {
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def parse_timestamp(value: str, label: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
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


def classify_change(change: float) -> str:
    if change > 0:
        return "LONG"

    if change < 0:
        return "SHORT"

    return "NEUTRAL"


def validate_pairs(
    df: pd.DataFrame,
    label: str,
) -> pd.DataFrame:
    pairs = df["pair"].astype(str)

    if pairs.duplicated().any():
        duplicates = sorted(pairs[pairs.duplicated()].unique())
        raise ValueError(f"{label}: duplicate pairs: {duplicates}")

    display_df = df.loc[pairs.isin(EXPECTED_PAIRS)].copy()

    if len(display_df) != len(EXPECTED_PAIRS):
        found = sorted(display_df["pair"].astype(str).unique())
        raise ValueError(
            f"{label}: missing display pairs; "
            f"expected {sorted(EXPECTED_PAIRS)}, found {found}"
        )

    display_pairs = set(display_df["pair"].astype(str))
    if display_pairs != EXPECTED_PAIRS:
        raise ValueError(
            f"{label}: expected display pairs {sorted(EXPECTED_PAIRS)}, "
            f"found {sorted(display_pairs)}"
        )

    return display_df

def load_signal_timeframe(label: str, config: dict, df: pd.DataFrame) -> dict:
    missing = sorted(REQUIRED_SIGNAL_COLUMNS - set(df.columns))

    if missing:
        raise ValueError(f"{label}: missing columns: {missing}")

    df = validate_pairs(df, label)

    signals = set(df["signal"].astype(str))
    invalid = sorted(signals - VALID_SIGNALS)

    if invalid:
        raise ValueError(f"{label}: invalid signal values: {invalid}")

    timestamps = df["timestamp"].astype(str).unique().tolist()

    if len(timestamps) != 1:
        raise ValueError(
            f"{label}: expected one shared timestamp, found {timestamps}"
        )

    timestamp = parse_timestamp(timestamps[0], label)

    age_minutes = round(
        (datetime.now(timezone.utc) - timestamp).total_seconds() / 60,
        2,
    )

    if age_minutes < 0:
        raise ValueError(f"{label}: timestamp is in the future")

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
        "source_file": config["path"].name,
        "methodology": config["methodology"],
        "timestamp_utc": timestamp.isoformat(),
        "rows": len(df),
        "age_minutes": age_minutes,
        "max_age_minutes": config["max_age_minutes"],
        "freshness": freshness_state(age_minutes, config["max_age_minutes"]),
        "signals": rows,
    }


def load_weekly_timeframe(label: str, config: dict, df: pd.DataFrame) -> dict:
    required = {"pair", "timestamp", "change"}

    if not required.issubset(df.columns):
        raise ValueError(
            f"{label}: expected weekly columns {sorted(required)}, "
            f"found {sorted(df.columns)}"
        )

    validate_pairs(df, label)

    timestamps = df["timestamp"].astype(str).unique().tolist()

    if len(timestamps) != 1:
        raise ValueError(
            f"{label}: expected one shared timestamp, found {timestamps}"
        )

    timestamp = parse_timestamp(timestamps[0], label)

    age_minutes = round(
        (datetime.now(timezone.utc) - timestamp).total_seconds() / 60,
        2,
    )

    if age_minutes < 0:
        raise ValueError(f"{label}: timestamp is in the future")

    rows = {}

    for row in df.to_dict(orient="records"):
        pair = str(row["pair"])
        change = float(row["change"])
        base_currency, quote_currency = pair.split("/")

        rows[pair] = {
            "pair": pair,
            "timestamp_utc": timestamp.isoformat(),
            "signal": classify_change(change),
            "pair_change": change,
            "base_currency": base_currency,
            "quote_currency": quote_currency,
            "base_score": None,
            "quote_score": None,
            "score_diff": None,
        }

    return {
        "label": label,
        "source_file": config["path"].name,
        "methodology": config["methodology"],
        "timestamp_utc": timestamp.isoformat(),
        "rows": len(df),
        "age_minutes": age_minutes,
        "max_age_minutes": config["max_age_minutes"],
        "freshness": freshness_state(age_minutes, config["max_age_minutes"]),
        "signals": rows,
    }


def load_timeframe(label: str, config: dict) -> dict:
    path = config["path"]

    if not path.exists():
        raise FileNotFoundError(f"{label}: file not found: {path.name}")

    df = pd.read_csv(path)

    if label == "W1":
        return load_weekly_timeframe(label, config, df)

    return load_signal_timeframe(label, config, df)


def classify(
    w1: str,
    d1: str,
    h4: str,
    h1: str,
    freshness: dict,
) -> tuple[str, str, str]:
    if any(
        freshness[label] == "STALE"
        for label in ("W1", "D1", "H4", "H1")
    ):
        return "INSUFFICIENT_OR_STALE_DATA", "WAIT", "N/A"

    if any(
        freshness[label] == "AGING"
        for label in ("W1", "D1", "H4", "H1")
    ):
        return "AGING_DATA_WARNING", "MONITOR", "LOW"

    if w1 == d1 == h4 == h1 == "LONG":
        return "ALIGNED_LONG", "WATCH", "HIGH"

    if w1 == d1 == h4 == h1 == "SHORT":
        return "ALIGNED_SHORT", "WATCH", "HIGH"

    if w1 == d1 == h4 == h1 == "NEUTRAL":
        return "ALIGNED_NEUTRAL", "WAIT", "N/A"

    if w1 == d1 and w1 in {"LONG", "SHORT"} and h4 == h1 == w1:
        return "ALIGNED_MULTI_TIMEFRAME", "WATCH", "HIGH"

    if w1 == d1 and w1 in {"LONG", "SHORT"}:
        return "WEEKLY_DAILY_ALIGNED_INTRADAY_CONFLICT", "MONITOR", "MEDIUM"

    if d1 == h4 and d1 in {"LONG", "SHORT"} and h1 != d1:
        return "HIGHER_TIMEFRAME_ALIGNED_H1_CONFLICT", "MONITOR", "MEDIUM"

    if h1 == h4 and h1 in {"LONG", "SHORT"} and d1 != h1:
        return "INTRADAY_ALIGNED_D1_CONFLICT", "MONITOR", "MEDIUM"

    return "CONFLICT", "WAIT", "N/A"


def load_performance() -> dict:
    result = {
        "available": False,
        "mfe_mae_available": False,
        "summary_by_horizon": [],
        "completed_by_horizon_source": [],
        "notes": [],
    }

    if not PERFORMANCE_REPORT.exists() or not PERFORMANCE_DETAIL.exists():
        result["notes"].append("Performance files are unavailable.")
        return result

    report = pd.read_csv(PERFORMANCE_REPORT)
    detail = pd.read_csv(PERFORMANCE_DETAIL)

    required_report = {
        "scope",
        "horizon",
        "signals",
        "win_rate_pct",
        "avg_return_pct",
        "median_return_pct",
        "expectancy_pct",
        "minimum_sample_met",
    }

    required_detail = {"horizon", "status", "source"}

    if (
        not required_report.issubset(report.columns)
        or not required_detail.issubset(detail.columns)
    ):
        result["notes"].append("Performance files have an unsupported schema.")
        return result

    overall = report[report["scope"].astype(str) == "overall_horizon"].copy()

    fields = [
        "horizon",
        "signals",
        "wins",
        "losses",
        "flats",
        "win_rate_pct",
        "avg_return_pct",
        "median_return_pct",
        "total_return_pct",
        "expectancy_pct",
        "minimum_sample_met",
    ]

    fields = [field for field in fields if field in overall.columns]

    result["summary_by_horizon"] = (
        overall[fields].fillna("").to_dict(orient="records")
    )

    completed = detail[
        detail["status"].astype(str).str.upper() == "COMPLETED"
    ]

    composition = (
        completed.groupby(["horizon", "source"], dropna=False)
        .size()
        .reset_index(name="completed_outcomes")
    )

    result["completed_by_horizon_source"] = composition.to_dict(
        orient="records"
    )

    result["available"] = True

    result["notes"].append(
        "Performance is research-only. api and legacy_journal sources "
        "remain separately identified."
    )

    return result


def build_pairs(timeframes: dict) -> list[dict]:
    freshness = {
        label: timeframes[label]["freshness"]
        for label in TIMEFRAMES
    }

    pairs = []

    for pair in sorted(EXPECTED_PAIRS):
        w1 = timeframes["W1"]["signals"][pair]
        d1 = timeframes["D1"]["signals"][pair]
        h4 = timeframes["H4"]["signals"][pair]
        h1 = timeframes["H1"]["signals"][pair]

        alignment, display_status, quality = classify(
            w1["signal"],
            d1["signal"],
            h4["signal"],
            h1["signal"],
            freshness,
        )

        pairs.append(
            {
                "pair": pair,
                "w1_bias": w1["signal"],
                "d1_bias": d1["signal"],
                "h4_bias": h4["signal"],
                "h1_bias": h1["signal"],
                "alignment": alignment,
                "display_status": display_status,
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
                    "W1": w1,
                    "D1": d1,
                    "H4": h4,
                    "H1": h1,
                },
            }
        )

    return pairs


def main() -> None:
    timeframes = {
        label: load_timeframe(label, config)
        for label, config in TIMEFRAMES.items()
    }

    snapshot = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dashboard_version": "v2-w1",
        "read_only": True,
        "analysis_status": "RESEARCH_ONLY",
        "no_threshold_change_authorized": True,
        "timeframes": {
            label: {
                key: value
                for key, value in data.items()
                if key != "signals"
            }
            for label, data in timeframes.items()
        },
        "pairs": build_pairs(timeframes),
        "performance": load_performance(),
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
    except Exception:
        logging.exception("Dashboard snapshot build failed")
        sys.exit(1)