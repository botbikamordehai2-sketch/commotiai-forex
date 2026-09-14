import csv
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

JOURNAL_FILE = "signals_journal.csv"
OUTCOMES_FILE = "signal_outcomes.csv"
API_KEY = os.getenv("TWELVEDATA_API_KEY")
BASE_URL = "https://api.twelvedata.com/time_series"

HORIZONS = {"1H": 1, "4H": 4, "24H": 24}
OUTCOME_COLUMNS = [
    "signal_id", "horizon", "signal_time", "pair", "timeframe", "signal",
    "score_diff", "entry_price", "target_time_utc", "exit_price", "return_pct",
    "result", "status", "source", "evaluated_at_utc",
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def parse_utc(value):
    timestamp = pd.to_datetime(value, utc=True)
    if not isinstance(timestamp, pd.Timestamp):
        raise ValueError(f"Invalid timestamp: {value}")
    return timestamp.to_pydatetime()


def utc_now():
    return datetime.now(timezone.utc)


def positive_float(value):
    try:
        value = float(value)
        return value if value > 0 else None
    except (TypeError, ValueError):
        return None


def return_pct(signal, entry_price, exit_price):
    value = ((exit_price - entry_price) / entry_price) * 100.0
    return -value if signal == "SHORT" else value


def result_for(value):
    return "WIN" if value > 0 else "LOSS" if value < 0 else "FLAT"


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_outcomes(rows):
    rows.sort(key=lambda row: (row["signal_time"], row["pair"], row["horizon"]))
    with open(OUTCOMES_FILE, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTCOME_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def legacy_outcome(row, horizon):
    suffix = horizon.lower()
    if horizon not in ("4H", "24H"):
        return None
    status = row.get(f"evaluation_{suffix}_status", "").strip().upper()
    entry = positive_float(row.get("entry_price"))
    exit_price = positive_float(row.get(f"price_after_{suffix}"))
    try:
        value = float(row.get(f"return_{suffix}_pct", ""))
    except (TypeError, ValueError):
        value = None
    result = row.get(f"result_{suffix}", "").strip().upper()
    if status != "COMPLETED" or entry is None or exit_price is None or value is None or result not in ("WIN", "LOSS", "FLAT"):
        return None
    signal_time = parse_utc(row["signal_time"])
    return {
        "signal_id": row["signal_id"].strip(), "horizon": horizon,
        "signal_time": signal_time.isoformat(), "pair": row["pair"].strip(),
        "timeframe": row["timeframe"].strip().upper(), "signal": row["signal"].strip().upper(),
        "score_diff": row.get("score_diff", ""), "entry_price": f"{entry:.10f}",
        "target_time_utc": (signal_time + timedelta(hours=HORIZONS[horizon])).isoformat(),
        "exit_price": f"{exit_price:.10f}", "return_pct": f"{value:.6f}",
        "result": result, "status": "COMPLETED", "source": "legacy_journal",
        "evaluated_at_utc": utc_now().isoformat(),
    }


def fetch_hourly_closes(pairs, start_utc, end_utc):
    if not API_KEY:
        raise RuntimeError("TWELVEDATA_API_KEY is not set")
    params = {
        "symbol": ",".join(sorted(pairs)), "interval": "1h",
        "start_date": start_utc.strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": end_utc.strftime("%Y-%m-%d %H:%M:%S"),
        "outputsize": 5000, "order": "desc", "timezone": "UTC",
        "format": "JSON", "apikey": API_KEY,
    }
    response = requests.get(BASE_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    prices, failed = {}, set()
    for pair in pairs:
        payload = data.get(pair)
        if not payload or payload.get("status") == "error" or not payload.get("values"):
            failed.add(pair)
            logging.warning("1h %s -> unavailable: %s", pair, payload.get("message") if payload else "no response")
            continue
        for bar in payload["values"]:
            try:
                close_time = parse_utc(bar["datetime"]) + timedelta(hours=1)
                prices[(pair, close_time)] = float(bar["close"])
            except (KeyError, TypeError, ValueError):
                logging.warning("1h %s -> skipped invalid bar", pair)
    return prices, failed


def build_pending(row, horizon, status, source="api"):
    signal_time = parse_utc(row["signal_time"])
    entry = positive_float(row.get("entry_price"))
    return {
        "signal_id": row["signal_id"].strip(), "horizon": horizon,
        "signal_time": signal_time.isoformat(), "pair": row["pair"].strip(),
        "timeframe": row["timeframe"].strip().upper(), "signal": row["signal"].strip().upper(),
        "score_diff": row.get("score_diff", ""), "entry_price": f"{entry:.10f}" if entry else "",
        "target_time_utc": (signal_time + timedelta(hours=HORIZONS[horizon])).isoformat(),
        "exit_price": "", "return_pct": "", "result": "", "status": status,
        "source": source, "evaluated_at_utc": "",
    }


def main():
    journal_rows = read_csv(JOURNAL_FILE)
    if not journal_rows:
        raise RuntimeError(f"Missing or empty {JOURNAL_FILE}")
    existing = {(row.get("signal_id", ""), row.get("horizon", "")): row for row in read_csv(OUTCOMES_FILE)}
    now = utc_now()
    candidates = []

    for row in journal_rows:
        signal = row.get("signal", "").strip().upper()
        entry = positive_float(row.get("entry_price"))
        if not row.get("signal_id", "").strip() or signal not in ("LONG", "SHORT") or entry is None:
            continue
        for horizon in HORIZONS:
            key = (row["signal_id"].strip(), horizon)
            legacy = legacy_outcome(row, horizon)
            if key not in existing and legacy:
                existing[key] = legacy
            current = existing.get(key)
            if current and current.get("status", "").upper() == "COMPLETED":
                continue
            pending = build_pending(row, horizon, "PENDING")
            target = parse_utc(pending["target_time_utc"])
            if now < target:
                existing[key] = pending
            else:
                candidates.append((key, pending, target))

    if candidates:
        pairs = {item[1]["pair"] for item in candidates}
        earliest = min(item[2] for item in candidates) - timedelta(hours=1)
        prices, failed_pairs = fetch_hourly_closes(pairs, earliest, now)
        for key, outcome, target in candidates:
            if outcome["pair"] in failed_pairs:
                outcome["status"] = "PENDING_RETRY"
            else:
                exit_price = prices.get((outcome["pair"], target))
                if exit_price is None:
                    outcome["status"] = "PENDING_RETRY"
                else:
                    value = return_pct(outcome["signal"], float(outcome["entry_price"]), exit_price)
                    outcome.update({
                        "exit_price": f"{exit_price:.10f}", "return_pct": f"{value:.6f}",
                        "result": result_for(value), "status": "COMPLETED",
                        "source": "api", "evaluated_at_utc": utc_now().isoformat(),
                    })
            existing[key] = outcome

    write_outcomes(list(existing.values()))
    completed = sum(row.get("status", "").upper() == "COMPLETED" for row in existing.values())
    logging.info("Saved %s with %s rows; completed=%s", OUTCOMES_FILE, len(existing), completed)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Outcome evaluation failed")
        sys.exit(1)
