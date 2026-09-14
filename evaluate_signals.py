import csv
import logging
import os
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

JOURNAL_FILE = "signals_journal.csv"
API_KEY = os.getenv("TWELVEDATA_API_KEY")
BASE_URL = "https://api.twelvedata.com/time_series"

TIMEFRAME_CONFIG = {
    "H1": {
        "interval": "1h",
        "bar_hours": 1,
    },
    "H4": {
        "interval": "4h",
        "bar_hours": 4,
    },
}

HORIZONS = {
    "4h": {
        "hours": 4,
        "status_column": "evaluation_4h_status",
        "price_column": "price_after_4h",
        "return_column": "return_4h_pct",
        "result_column": "result_4h",
    },
    "24h": {
        "hours": 24,
        "status_column": "evaluation_24h_status",
        "price_column": "price_after_24h",
        "return_column": "return_24h_pct",
        "result_column": "result_24h",
    },
}


def parse_utc(value: str) -> datetime:
    timestamp = pd.to_datetime(value, utc=True)

    if not isinstance(timestamp, pd.Timestamp):
        raise ValueError(f"Invalid timestamp: {value}")

    return timestamp.to_pydatetime()


def is_positive_float(value: str) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def load_journal() -> tuple[list[str], list[dict]]:
    if not os.path.exists(JOURNAL_FILE):
        raise RuntimeError(f"Missing journal file: {JOURNAL_FILE}")

    with open(JOURNAL_FILE, "r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        if not reader.fieldnames:
            raise RuntimeError(f"{JOURNAL_FILE} has no header")

        rows = list(reader)
        return reader.fieldnames, rows


def fetch_closed_prices(
    pairs: set[str],
    interval: str,
    bar_hours: int,
    start_utc: datetime,
    end_utc: datetime,
) -> tuple[dict[tuple[str, datetime], float], set[str]]:
    if not API_KEY:
        raise RuntimeError("TWELVEDATA_API_KEY is not set")

    params = {
        "symbol": ",".join(sorted(pairs)),
        "interval": interval,
        "start_date": start_utc.strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": end_utc.strftime("%Y-%m-%d %H:%M:%S"),
        "outputsize": 5000,
        "order": "desc",
        "timezone": "UTC",
        "format": "JSON",
        "apikey": API_KEY,
    }

    logging.info(
        "Requesting historical %s bars for %s pairs from %s to %s",
        interval,
        len(pairs),
        start_utc.isoformat(),
        end_utc.isoformat(),
    )

    response = requests.get(BASE_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    prices = {}
    failed_pairs = set()

    for pair in pairs:
        pair_data = data.get(pair)

        if not pair_data:
            logging.warning("%s %s -> No response object", interval, pair)
            failed_pairs.add(pair)
            continue

        if pair_data.get("status") == "error":
            logging.warning(
                "%s %s -> API error: %s",
                interval,
                pair,
                pair_data.get("message"),
            )
            failed_pairs.add(pair)
            continue

        values = pair_data.get("values")

        if not values:
            logging.warning("%s %s -> No historical values", interval, pair)
            failed_pairs.add(pair)
            continue

        for bar in values:
            try:
                bar_open = parse_utc(bar["datetime"])
                bar_close = bar_open + timedelta(hours=bar_hours)
                prices[(pair, bar_close)] = float(bar["close"])
            except (KeyError, TypeError, ValueError) as error:
                logging.warning(
                    "%s %s -> Skipped invalid bar: %s",
                    interval,
                    pair,
                    error,
                )

    return prices, failed_pairs


def directional_return_pct(
    signal: str,
    entry_price: float,
    exit_price: float,
) -> float:
    raw_return = (exit_price - entry_price) / entry_price

    if signal == "SHORT":
        raw_return = -raw_return

    return raw_return * 100.0


def classify_result(return_pct: float) -> str:
    if return_pct > 0:
        return "WIN"

    if return_pct < 0:
        return "LOSS"

    return "FLAT"


def save_journal(fieldnames: list[str], rows: list[dict]) -> None:
    directory = os.path.dirname(os.path.abspath(JOURNAL_FILE)) or "."

    with tempfile.NamedTemporaryFile(
        mode="w",
        newline="",
        encoding="utf-8",
        dir=directory,
        delete=False,
    ) as temp_file:
        temp_path = temp_file.name
        writer = csv.DictWriter(temp_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    os.replace(temp_path, JOURNAL_FILE)


def main() -> None:
    fieldnames, rows = load_journal()
    now_utc = datetime.now(timezone.utc)

    required_columns = {
        "signal_time",
        "pair",
        "timeframe",
        "signal",
        "entry_price",
        "entry_status",
        "evaluation_4h_status",
        "evaluation_24h_status",
        "price_after_4h",
        "price_after_24h",
        "return_4h_pct",
        "return_24h_pct",
        "result_4h",
        "result_24h",
    }

    missing_columns = sorted(required_columns - set(fieldnames))

    if missing_columns:
        raise RuntimeError(
            f"{JOURNAL_FILE} is missing required columns: {missing_columns}"
        )

    candidates = defaultdict(list)
    skipped_missing_entry = 0
    skipped_neutral = 0
    skipped_unknown_timeframe = 0
    waiting_for_time = 0

    for row_index, row in enumerate(rows):
        signal = row.get("signal", "").strip().upper()
        timeframe = row.get("timeframe", "").strip().upper()

        if signal == "NEUTRAL":
            skipped_neutral += 1
            continue

        if signal not in ("LONG", "SHORT"):
            continue

        if timeframe not in TIMEFRAME_CONFIG:
            skipped_unknown_timeframe += 1
            continue

        if (
            row.get("entry_status", "").strip() != "RECORDED"
            or not is_positive_float(row.get("entry_price", ""))
        ):
            skipped_missing_entry += 1
            continue

        signal_time = parse_utc(row["signal_time"])

        for horizon_name, horizon in HORIZONS.items():
            status = row.get(horizon["status_column"], "").strip().upper()

            if status == "COMPLETED":
                continue

            target_time = signal_time + timedelta(hours=horizon["hours"])

            if now_utc < target_time:
                waiting_for_time += 1
                continue

            candidates[timeframe].append({
                "row_index": row_index,
                "pair": row["pair"].strip(),
                "signal": signal,
                "target_time": target_time,
                "horizon_name": horizon_name,
            })

    updated_4h = 0
    updated_24h = 0
    pending_retry = 0

    for timeframe, items in candidates.items():
        config = TIMEFRAME_CONFIG[timeframe]
        pairs = {item["pair"] for item in items}
        earliest_target = min(item["target_time"] for item in items)

        start_utc = earliest_target - timedelta(
            hours=config["bar_hours"]
        )

        prices, failed_pairs = fetch_closed_prices(
            pairs=pairs,
            interval=config["interval"],
            bar_hours=config["bar_hours"],
            start_utc=start_utc,
            end_utc=now_utc,
        )

        for item in items:
            row = rows[item["row_index"]]
            horizon = HORIZONS[item["horizon_name"]]

            if item["pair"] in failed_pairs:
                pending_retry += 1
                continue

            exit_price = prices.get((item["pair"], item["target_time"]))

            if exit_price is None:
                logging.warning(
                    "%s %s -> Missing closed bar for target=%s",
                    timeframe,
                    item["pair"],
                    item["target_time"].isoformat(),
                )
                pending_retry += 1
                continue

            entry_price = float(row["entry_price"])
            return_pct = directional_return_pct(
                item["signal"],
                entry_price,
                exit_price,
            )

            row[horizon["price_column"]] = f"{exit_price:.10f}"
            row[horizon["return_column"]] = f"{return_pct:.6f}"
            row[horizon["result_column"]] = classify_result(return_pct)
            row[horizon["status_column"]] = "COMPLETED"

            if item["horizon_name"] == "4h":
                updated_4h += 1
            else:
                updated_24h += 1

    if updated_4h or updated_24h:
        save_journal(fieldnames, rows)
        logging.info("Updated %s", JOURNAL_FILE)
    else:
        logging.info("No completed evaluations to write")

    logging.info(
        "Evaluation summary: updated_4h=%s updated_24h=%s "
        "pending_retry=%s waiting_for_time=%s "
        "skipped_missing_entry=%s skipped_neutral=%s "
        "skipped_unknown_timeframe=%s",
        updated_4h,
        updated_24h,
        pending_retry,
        waiting_for_time,
        skipped_missing_entry,
        skipped_neutral,
        skipped_unknown_timeframe,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Signal evaluation failed")
        sys.exit(1)