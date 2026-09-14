import csv
import os
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

SIGNALS_FILES = [
    ("signals_1h.csv", "H1"),
    ("signals_4h.csv", "H4"),
]

OUTPUT_LOG_FILE = "signals_log.csv"

PAIR_LIST = [
    "EUR/USD",
    "GBP/USD",
    "NZD/USD",
    "USD/CHF",
    "USD/JPY",
]

X_SHORT_HOURS = 4
X_LONG_HOURS = 24

TWELVE_DATA_KEY = os.getenv("TWELVE_DATA_KEY")
TWELVE_URL = "https://api.twelvedata.com/time_series"

price_cache = {}


def parse_timestamp(value):
    value = value.strip().replace("Z", "+00:00")

    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def fetch_pair_bars(pair):
    if pair in price_cache:
        return price_cache[pair]

    params = {
        "symbol": pair,
        "interval": "1h",
        "outputsize": 100,
        "order": "asc",
        "timezone": "UTC",
        "apikey": TWELVE_DATA_KEY,
    }

    try:
        response = requests.get(TWELVE_URL, params=params, timeout=20)
        data = response.json()
    except Exception as error:
        print(f"Request error for {pair}: {error}")
        price_cache[pair] = []
        return []

    if "values" not in data:
        print(f"No data for {pair}: {data}")
        price_cache[pair] = []
        return []

    bars = []

    for item in data["values"]:
        try:
            bars.append({
                "time": parse_timestamp(item["datetime"]),
                "close": float(item["close"]),
            })
        except (KeyError, TypeError, ValueError):
            continue

    price_cache[pair] = bars

    print(f"Downloaded {len(bars)} H1 bars for {pair}")

    time.sleep(1.5)

    return bars


def closest_close(pair, target_time):
    bars = fetch_pair_bars(pair)

    if not bars:
        return None

    closest_bar = min(
        bars,
        key=lambda bar: abs((bar["time"] - target_time).total_seconds())
    )

    difference_hours = abs(
        (closest_bar["time"] - target_time).total_seconds()
    ) / 3600

    if difference_hours > 1.1:
        print(
            f"No close enough candle for {pair} at "
            f"{target_time.isoformat()}"
        )
        return None

    return closest_bar["close"]


def evaluate(signal, entry_price, future_price):
    if entry_price is None or future_price is None:
        return "NO_DATA"

    if signal == "LONG":
        return "WIN" if future_price > entry_price else "LOSS"

    if signal == "SHORT":
        return "WIN" if future_price < entry_price else "LOSS"

    return "NEUTRAL"


def percent_return(signal, entry_price, future_price):
    if entry_price is None or future_price is None:
        return ""

    value = ((future_price - entry_price) / entry_price) * 100

    if signal == "SHORT":
        value = -value

    return round(value, 5)


def read_signals():
    signals = []

    for filename, timeframe in SIGNALS_FILES:
        if not os.path.exists(filename):
            print(f"Missing file: {filename}")
            continue

        with open(filename, "r", newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)

            for row in reader:
                pair = row.get("pair", "").strip()
                signal = row.get("signal", "").strip().upper()
                timestamp = row.get("timestamp", "").strip()

                if pair not in PAIR_LIST:
                    continue

                if signal not in ("LONG", "SHORT"):
                    continue

                if not timestamp:
                    continue

                signals.append({
                    "pair": pair,
                    "timeframe": timeframe,
                    "signal_time": timestamp,
                    "signal": signal,
                })

    return signals


def create_output_file():
    with open(OUTPUT_LOG_FILE, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)

        writer.writerow([
            "pair",
            "timeframe",
            "signal_time",
            "signal",
            "entry_price",
            "price_after_4h",
            "price_after_24h",
            "return_4h_pct",
            "return_24h_pct",
            "result_4h",
            "result_24h",
        ])


def main():
    if not TWELVE_DATA_KEY:
        print("TWELVE_DATA_KEY is not set in .env. Stopping.")
        return

    signals = read_signals()

    if not signals:
        print("No LONG or SHORT signals found.")
        return

    print(f"Found {len(signals)} LONG/SHORT signals.")
    print("Downloading one H1 history request per unique pair.")

    unique_pairs = sorted({item["pair"] for item in signals})

    for pair in unique_pairs:
        fetch_pair_bars(pair)

    create_output_file()

    with open(OUTPUT_LOG_FILE, "a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)

        for item in signals:
            pair = item["pair"]
            signal = item["signal"]
            signal_time = parse_timestamp(item["signal_time"])

            entry_price = closest_close(pair, signal_time)

            price_after_4h = closest_close(
                pair,
                signal_time + timedelta(hours=X_SHORT_HOURS)
            )

            price_after_24h = closest_close(
                pair,
                signal_time + timedelta(hours=X_LONG_HOURS)
            )

            result_4h = evaluate(signal, entry_price, price_after_4h)
            result_24h = evaluate(signal, entry_price, price_after_24h)

            return_4h = percent_return(
                signal,
                entry_price,
                price_after_4h
            )

            return_24h = percent_return(
                signal,
                entry_price,
                price_after_24h
            )

            writer.writerow([
                pair,
                item["timeframe"],
                item["signal_time"],
                signal,
                entry_price if entry_price is not None else "",
                price_after_4h if price_after_4h is not None else "",
                price_after_24h if price_after_24h is not None else "",
                return_4h,
                return_24h,
                result_4h,
                result_24h,
            ])

            print(
                f"Logged: {pair} {item['timeframe']} {signal} | "
                f"4h={result_4h} | 24h={result_24h}"
            )

    print(f"Done. Results saved to {OUTPUT_LOG_FILE}")


if __name__ == "__main__":
    main()