import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://api.twelvedata.com/time_series"
API_KEY = os.getenv("TWELVEDATA_API_KEY")

SYMBOLS = [
    "AUD/USD",
    "EUR/USD",
    "GBP/USD",
    "NZD/USD",
    "USD/CAD",
    "USD/CHF",
    "USD/JPY",
]
EXPECTED_PAIRS = set(SYMBOLS)
OUTPUT_SIZE_4H = 5
MAX_4H_BAR_AGE = timedelta(hours=4, minutes=20)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def parse_bar_datetime(dt_str: str) -> datetime:
    dt = pd.to_datetime(dt_str, utc=True)
    if isinstance(dt, pd.Timestamp):
        return dt.to_pydatetime()
    raise ValueError(f"Invalid datetime value: {dt_str}")


def get_last_closed_bar(
    values: list,
    now_utc: datetime,
    interval_hours: int = 4,
) -> dict | None:
    for bar in values:
        bar_open_utc = parse_bar_datetime(bar["datetime"])
        if bar_open_utc + timedelta(hours=interval_hours) <= now_utc:
            return bar
    return None


def validate_complete_results(results: list[dict]) -> None:
    actual_pairs = {row["pair"] for row in results}
    missing_pairs = sorted(EXPECTED_PAIRS - actual_pairs)
    unexpected_pairs = sorted(actual_pairs - EXPECTED_PAIRS)

    if missing_pairs or unexpected_pairs or len(results) != len(EXPECTED_PAIRS):
        raise RuntimeError(
            "4H fetch incomplete; pair_changes_4h.csv was not updated. "
            f"missing={missing_pairs}, "
            f"unexpected={unexpected_pairs}, "
            f"rows={len(results)}, "
            f"expected_rows={len(EXPECTED_PAIRS)}"
        )


def fetch_4h() -> pd.DataFrame:
    if not API_KEY:
        raise RuntimeError("TWELVEDATA_API_KEY is not set")

    now_utc = datetime.now(timezone.utc)
    params = {
        "symbol": ",".join(SYMBOLS),
        "interval": "4h",
        "outputsize": OUTPUT_SIZE_4H,
        "order": "desc",
        "timezone": "UTC",
        "format": "JSON",
        "apikey": API_KEY,
    }

    logging.info("Requesting interval=4h, outputsize=%s", OUTPUT_SIZE_4H)

    try:
        response = requests.get(BASE_URL, params=params, timeout=30)
    except requests.RequestException as exc:
        raise RuntimeError(f"4H request failed: {type(exc).__name__}") from None

    if response.status_code != 200:
        raise RuntimeError(f"4H API returned HTTP {response.status_code}")

    try:
        data = response.json()
    except ValueError:
        raise RuntimeError("4H API returned invalid JSON") from None

    results = []

    for symbol in SYMBOLS:
        symbol_data = data.get(symbol)
        if not symbol_data:
            logging.warning("4H %s -> No response object", symbol)
            continue

        if symbol_data.get("status") == "error":
            logging.warning("4H %s -> API error: %s", symbol, symbol_data.get("message"))
            continue

        values = symbol_data.get("values")
        if not values:
            logging.warning("4H %s -> No values returned", symbol)
            continue

        try:
            closed_bar = get_last_closed_bar(values, now_utc, interval_hours=4)
        except (KeyError, TypeError, ValueError) as exc:
            logging.warning("4H %s -> Invalid bar datetime: %s", symbol, type(exc).__name__)
            continue

        if not closed_bar:
            logging.warning("4H %s -> No closed 4H bar found", symbol)
            continue

        try:
            bar_open_utc = parse_bar_datetime(closed_bar["datetime"])
            open_price = float(closed_bar["open"])
            close_price = float(closed_bar["close"])
        except (KeyError, TypeError, ValueError) as exc:
            logging.warning("4H %s -> Invalid OHLC data: %s", symbol, type(exc).__name__)
            continue

        if open_price <= 0 or close_price <= 0:
            logging.warning("4H %s -> Non-positive price data", symbol)
            continue

        bar_close_utc = bar_open_utc + timedelta(hours=4)
        bar_age = now_utc - bar_close_utc

        if bar_age < timedelta(0):
            logging.warning("4H %s -> Selected bar is not closed", symbol)
            continue

        if bar_age > MAX_4H_BAR_AGE:
            logging.warning(
                "4H %s -> Stale closed bar: bar_close=%s age=%s",
                symbol,
                bar_close_utc.isoformat(),
                bar_age,
            )
            continue

        ret = (close_price - open_price) / open_price
        results.append(
            {
                "symbol": symbol.replace("/", ""),
                "pair": symbol,
                "timestamp": bar_close_utc,
                "open": open_price,
                "close": close_price,
                "change": ret,
            }
        )

        logging.info(
            "4H %s -> bar_open=%s bar_close=%s age=%s open=%s close=%s change=%.6f",
            symbol,
            bar_open_utc.isoformat(),
            bar_close_utc.isoformat(),
            bar_age,
            open_price,
            close_price,
            ret,
        )

    validate_complete_results(results)

    df = pd.DataFrame(results)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values(["timestamp", "pair"]).reset_index(drop=True)
    df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return df


def main() -> None:
    df_4h = fetch_4h()
    output_path = Path("pair_changes_4h.csv")
    temp_path = output_path.with_suffix(".tmp")
    df_4h.to_csv(temp_path, index=False)
    temp_path.replace(output_path)
    logging.info("Saved pair_changes_4h.csv with %s rows", len(df_4h))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logging.error("4H fetch failed: %s", exc)
        sys.exit(1)

