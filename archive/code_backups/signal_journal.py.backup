import csv
import hashlib
import os
from datetime import datetime, timezone


SIGNAL_SOURCES = [
    {
        "signals_file": "signals_1h.csv",
        "prices_file": "pair_changes_1h.csv",
        "timeframe": "H1",
    },
    {
        "signals_file": "signals_4h.csv",
        "prices_file": "pair_changes_4h.csv",
        "timeframe": "H4",
    },
]

JOURNAL_FILE = "signals_journal.csv"

JOURNAL_COLUMNS = [
    "signal_id",
    "signal_time",
    "recorded_at_utc",
    "pair",
    "timeframe",
    "signal",
    "base_currency",
    "quote_currency",
    "pair_change",
    "base_score",
    "quote_score",
    "score_diff",
    "entry_price",
    "session_utc",
    "entry_status",
    "evaluation_4h_status",
    "evaluation_24h_status",
    "price_after_4h",
    "price_after_24h",
    "return_4h_pct",
    "return_24h_pct",
    "result_4h",
    "result_24h",
]


def parse_timestamp(value):
    value = str(value).strip().replace("Z", "+00:00")

    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def canonical_timestamp(value):
    return parse_timestamp(value).isoformat()


def utc_now_string():
    return datetime.now(timezone.utc).isoformat()


def get_session_utc(timestamp_string):
    hour = parse_timestamp(timestamp_string).hour

    if 0 <= hour < 7:
        return "ASIA"

    if 7 <= hour < 12:
        return "LONDON"

    if 12 <= hour < 16:
        return "LONDON_NY_OVERLAP"

    if 16 <= hour < 21:
        return "NEW_YORK"

    return "LATE_NY"


def create_signal_id(pair, timeframe, signal_time):
    raw_value = f"{pair}|{timeframe}|{canonical_timestamp(signal_time)}"
    return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()[:16]


def to_float_or_blank(value):
    if value is None:
        return ""

    value = str(value).strip()

    if value == "":
        return ""

    try:
        return float(value)
    except ValueError:
        return ""


def load_price_map(prices_file):
    price_map = {}

    if not os.path.exists(prices_file):
        print(f"Warning: missing price file: {prices_file}")
        return price_map

    with open(prices_file, "r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            pair = row.get("pair", "").strip()
            timestamp = row.get("timestamp", "").strip()
            close_price = to_float_or_blank(row.get("close"))

            if not pair or not timestamp or close_price == "":
                continue

            try:
                timestamp_key = canonical_timestamp(timestamp)
            except ValueError:
                print(f"Invalid timestamp in {prices_file}: {timestamp}")
                continue

            price_map[(pair, timestamp_key)] = close_price

    return price_map


def create_journal_if_needed():
    if os.path.exists(JOURNAL_FILE):
        return

    with open(JOURNAL_FILE, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=JOURNAL_COLUMNS)
        writer.writeheader()


def load_existing_signal_ids():
    existing_ids = set()

    if not os.path.exists(JOURNAL_FILE):
        return existing_ids

    with open(JOURNAL_FILE, "r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            signal_id = row.get("signal_id", "").strip()

            if signal_id:
                existing_ids.add(signal_id)

    return existing_ids


def build_journal_row(signal_row, timeframe, price_map):
    pair = signal_row.get("pair", "").strip()
    signal_time = signal_row.get("timestamp", "").strip()
    signal = signal_row.get("signal", "").strip().upper()

    signal_time_utc = canonical_timestamp(signal_time)
    signal_id = create_signal_id(pair, timeframe, signal_time)

    entry_price = price_map.get((pair, signal_time_utc), "")

    if signal == "NEUTRAL":
        entry_status = "NOT_TRACKED"
        evaluation_4h_status = "NOT_APPLICABLE"
        evaluation_24h_status = "NOT_APPLICABLE"
    elif entry_price == "":
        entry_status = "MISSING_ENTRY_PRICE"
        evaluation_4h_status = "PENDING_RETRY"
        evaluation_24h_status = "PENDING_RETRY"
    else:
        entry_status = "RECORDED"
        evaluation_4h_status = "PENDING"
        evaluation_24h_status = "PENDING"

    return {
        "signal_id": signal_id,
        "signal_time": signal_time_utc,
        "recorded_at_utc": utc_now_string(),
        "pair": pair,
        "timeframe": timeframe,
        "signal": signal,
        "base_currency": signal_row.get("base_currency", "").strip(),
        "quote_currency": signal_row.get("quote_currency", "").strip(),
        "pair_change": to_float_or_blank(signal_row.get("pair_change")),
        "base_score": to_float_or_blank(signal_row.get("base_score")),
        "quote_score": to_float_or_blank(signal_row.get("quote_score")),
        "score_diff": to_float_or_blank(signal_row.get("score_diff")),
        "entry_price": entry_price,
        "session_utc": get_session_utc(signal_time),
        "entry_status": entry_status,
        "evaluation_4h_status": evaluation_4h_status,
        "evaluation_24h_status": evaluation_24h_status,
        "price_after_4h": "",
        "price_after_24h": "",
        "return_4h_pct": "",
        "return_24h_pct": "",
        "result_4h": "",
        "result_24h": "",
    }


def process_source(source, existing_ids):
    signals_file = source["signals_file"]
    prices_file = source["prices_file"]
    timeframe = source["timeframe"]

    if not os.path.exists(signals_file):
        print(f"Missing signals file: {signals_file}")
        return []

    price_map = load_price_map(prices_file)
    new_rows = []

    with open(signals_file, "r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for signal_row in reader:
            pair = signal_row.get("pair", "").strip()
            signal_time = signal_row.get("timestamp", "").strip()
            signal = signal_row.get("signal", "").strip().upper()

            if not pair or not signal_time:
                continue

            if signal not in ("LONG", "SHORT", "NEUTRAL"):
                continue

            try:
                signal_id = create_signal_id(pair, timeframe, signal_time)
            except ValueError:
                print(f"Invalid signal timestamp: {signal_time}")
                continue

            if signal_id in existing_ids:
                continue

            new_rows.append(
                build_journal_row(signal_row, timeframe, price_map)
            )

    return new_rows


def main():
    create_journal_if_needed()

    existing_ids = load_existing_signal_ids()
    all_new_rows = []

    for source in SIGNAL_SOURCES:
        all_new_rows.extend(process_source(source, existing_ids))

    if not all_new_rows:
        print("No new signals to add. Journal is already up to date.")
        return

    with open(JOURNAL_FILE, "a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=JOURNAL_COLUMNS)

        for row in all_new_rows:
            writer.writerow(row)

    print(f"Added {len(all_new_rows)} new journal rows.")
    print(f"Saved to: {JOURNAL_FILE}")


if __name__ == "__main__":
    main()