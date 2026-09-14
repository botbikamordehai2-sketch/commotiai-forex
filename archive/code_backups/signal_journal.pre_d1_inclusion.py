import csv
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone

SIGNAL_SOURCES = [
    {"signals_file": "signals_1h.csv", "prices_file": "pair_changes_1h.csv", "timeframe": "H1"},
    {"signals_file": "signals_4h.csv", "prices_file": "pair_changes_4h.csv", "timeframe": "H4"},
]

JOURNAL_FILE = "signals_journal.csv"
JOURNAL_LOCK_DIR = "journal.lock"
JOURNAL_LOCK_INFO_FILE = "owner.json"
JOURNAL_LOCK_TTL_SECONDS = 600.0

JOURNAL_COLUMNS = [
    "signal_id", "signal_time", "recorded_at_utc", "pair", "timeframe", "signal",
    "base_currency", "quote_currency", "pair_change", "base_score", "quote_score",
    "score_diff", "entry_price", "session_utc", "entry_status",
    "evaluation_4h_status", "evaluation_24h_status", "price_after_4h",
    "price_after_24h", "return_4h_pct", "return_24h_pct", "result_4h", "result_24h",
]


class JournalLockBusy(RuntimeError):
    pass


def parse_timestamp(value):
    value = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def canonical_timestamp(value):
    return parse_timestamp(value).isoformat()


def utc_now_string():
    return datetime.now(timezone.utc).isoformat()


def get_session_utc(timestamp_string):
    hour = parse_timestamp(timestamp_string).hour
    if hour < 7:
        return "ASIA"
    if hour < 12:
        return "LONDON"
    if hour < 16:
        return "LONDON_NY_OVERLAP"
    if hour < 21:
        return "NEW_YORK"
    return "LATE_NY"


def create_signal_id(pair, timeframe, signal_time):
    raw_value = f"{pair}|{timeframe}|{canonical_timestamp(signal_time)}"
    return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()[:16]


def to_float_or_blank(value):
    if value is None or str(value).strip() == "":
        return ""
    try:
        return float(str(value).strip())
    except ValueError:
        return ""


def lock_age_seconds():
    if not os.path.isdir(JOURNAL_LOCK_DIR):
        return None
    return max(0.0, datetime.now().timestamp() - os.path.getmtime(JOURNAL_LOCK_DIR))


def acquire_journal_lock():
    try:
        os.mkdir(JOURNAL_LOCK_DIR)
    except FileExistsError:
        age = lock_age_seconds()
        if age is not None and age > JOURNAL_LOCK_TTL_SECONDS:
            try:
                shutil.rmtree(JOURNAL_LOCK_DIR)
                print(f"JOURNAL_LOCK_STALE_REMOVED age_seconds={round(age, 1)}")
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise JournalLockBusy(f"journal lock stale but could not be removed: {exc}") from exc
            return acquire_journal_lock()
        raise JournalLockBusy(
            f"JOURNAL_LOCK_BUSY action=SKIP age_seconds={round(age or 0.0, 1)} "
            f"max_age_seconds={int(JOURNAL_LOCK_TTL_SECONDS)}"
        )

    owner_path = os.path.join(JOURNAL_LOCK_DIR, JOURNAL_LOCK_INFO_FILE)
    with open(owner_path, "w", encoding="utf-8") as file:
        json.dump({"pid": os.getpid(), "acquired_at_utc": utc_now_string()}, file)
    print(f"JOURNAL_LOCK_ACQUIRED pid={os.getpid()}")


def release_journal_lock():
    try:
        shutil.rmtree(JOURNAL_LOCK_DIR)
        print(f"JOURNAL_LOCK_RELEASED pid={os.getpid()}")
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(f"Warning: unable to release journal lock: {exc}")


def load_price_map(prices_file):
    price_map = {}
    if not os.path.exists(prices_file):
        print(f"Warning: missing price file: {prices_file}")
        return price_map
    with open(prices_file, "r", newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            pair = row.get("pair", "").strip()
            timestamp = row.get("timestamp", "").strip()
            close_price = to_float_or_blank(row.get("close"))
            if not pair or not timestamp or close_price == "":
                continue
            try:
                price_map[(pair, canonical_timestamp(timestamp))] = close_price
            except ValueError:
                print(f"Invalid timestamp in {prices_file}: {timestamp}")
    return price_map


def create_journal_if_needed():
    if os.path.exists(JOURNAL_FILE):
        return
    with open(JOURNAL_FILE, "w", newline="", encoding="utf-8") as file:
        csv.DictWriter(file, fieldnames=JOURNAL_COLUMNS).writeheader()


def load_existing_signal_ids():
    ids = set()
    if not os.path.exists(JOURNAL_FILE):
        return ids
    with open(JOURNAL_FILE, "r", newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            signal_id = row.get("signal_id", "").strip()
            if signal_id:
                ids.add(signal_id)
    return ids


def build_journal_row(signal_row, timeframe, price_map):
    pair = signal_row.get("pair", "").strip()
    signal_time = signal_row.get("timestamp", "").strip()
    signal = signal_row.get("signal", "").strip().upper()
    signal_time_utc = canonical_timestamp(signal_time)
    entry_price = price_map.get((pair, signal_time_utc), "")

    if signal == "NEUTRAL":
        entry_status, evaluation_4h_status, evaluation_24h_status = "NOT_TRACKED", "NOT_APPLICABLE", "NOT_APPLICABLE"
    elif entry_price == "":
        entry_status, evaluation_4h_status, evaluation_24h_status = "MISSING_ENTRY_PRICE", "PENDING_RETRY", "PENDING_RETRY"
    else:
        entry_status, evaluation_4h_status, evaluation_24h_status = "RECORDED", "PENDING", "PENDING"

    return {
        "signal_id": create_signal_id(pair, timeframe, signal_time),
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
        "price_after_4h": "", "price_after_24h": "", "return_4h_pct": "",
        "return_24h_pct": "", "result_4h": "", "result_24h": "",
    }


def process_source(source, existing_ids):
    signals_file = source["signals_file"]
    if not os.path.exists(signals_file):
        print(f"Missing signals file: {signals_file}")
        return []

    rows = []
    price_map = load_price_map(source["prices_file"])
    with open(signals_file, "r", newline="", encoding="utf-8") as file:
        for signal_row in csv.DictReader(file):
            pair = signal_row.get("pair", "").strip()
            signal_time = signal_row.get("timestamp", "").strip()
            signal = signal_row.get("signal", "").strip().upper()
            if not pair or not signal_time or signal not in ("LONG", "SHORT", "NEUTRAL"):
                continue
            try:
                signal_id = create_signal_id(pair, source["timeframe"], signal_time)
            except ValueError:
                print(f"Invalid signal timestamp: {signal_time}")
                continue
            if signal_id in existing_ids:
                continue
            existing_ids.add(signal_id)
            rows.append(build_journal_row(signal_row, source["timeframe"], price_map))
    return rows


def print_summary(rows):
    directional = sum(row["signal"] in ("LONG", "SHORT") for row in rows)
    neutral = sum(row["signal"] == "NEUTRAL" for row in rows)
    recorded = sum(row["entry_status"] == "RECORDED" for row in rows)
    missing = sum(row["entry_status"] == "MISSING_ENTRY_PRICE" for row in rows)
    print(f"Added {len(rows)} new journal rows.")
    print(f"Directional signals: {directional}")
    print(f"Neutral signals: {neutral}")
    print(f"Recorded entry prices: {recorded}")
    print(f"Missing entry prices: {missing}")
    print(f"Saved to: {JOURNAL_FILE}")


def main():
    try:
        acquire_journal_lock()
    except JournalLockBusy as exc:
        print(exc)
        return

    try:
        create_journal_if_needed()
        existing_ids = load_existing_signal_ids()
        all_new_rows = []
        for source in SIGNAL_SOURCES:
            all_new_rows.extend(process_source(source, existing_ids))
        if not all_new_rows:
            print("No new signals to add. Journal is already up to date.")
            return
        with open(JOURNAL_FILE, "a", newline="", encoding="utf-8") as file:
            csv.DictWriter(file, fieldnames=JOURNAL_COLUMNS).writerows(all_new_rows)
        print_summary(all_new_rows)
    finally:
        release_journal_lock()


if __name__ == "__main__":
    main()
