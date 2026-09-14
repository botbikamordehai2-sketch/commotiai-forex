import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

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
OUTPUT_SIZE_1W = 5
MAX_1W_BAR_AGE = timedelta(days=9)
EXCHANGE_TZ = ZoneInfo("America/New_York")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def parse_weekly_bar_datetime(dt_str: str) -> datetime:
    raw = pd.to_datetime(dt_str)

    if not isinstance(raw, pd.Timestamp) or pd.isna(raw):
        raise ValueError(f"Invalid datetime value: {dt_str}")

    if raw.tzinfo is not None:
        return raw.tz_convert(EXCHANGE_TZ).to_pydatetime()

    return raw.to_pydatetime().replace(tzinfo=EXCHANGE_TZ)


def get_last_closed_weekly_bar(values: list, now_utc: datetime) -> dict | None:
    for bar in values:
        bar_open_exchange = parse_weekly_bar_datetime(bar["datetime"])
        bar_close_exchange = bar_open_exchange + timedelta(days=7)
        bar_close_utc = bar_close_exchange.astimezone(timezone.utc)

        if bar_close_utc <= now_utc:
            return bar

    return None


def validate_complete_results(results: list[dict]) -> None:
    actual_pairs = {row["pair"] for row in results}
    missing_pairs = sorted(EXPECTED_PAIRS - actual_pairs)
    unexpected_pairs = sorted(actual_pairs - EXPECTED_PAIRS)

    if missing_pairs or unexpected_pairs or len(results) != len(EXPECTED_PAIRS):
        raise RuntimeError(
            "1W fetch incomplete; pair_changes_1w.csv was not updated. "
            f"missing={missing_pairs}, "
            f"unexpected={unexpected_pairs}, "
            f"rows={len(results)}, "
            f"expected_rows={len(EXPECTED_PAIRS)}"
        )

    timestamps = {row["timestamp"] for row in results}
    if len(timestamps) != 1:
        raise RuntimeError(
            "1W fetch timestamps differ across pairs; "
            "pair_changes_1w.csv was not updated."
        )


def fetch_1w() -> pd.DataFrame:
    if not API_KEY:
        raise RuntimeError("TWELVEDATA_API_KEY is not set")

    now_utc = datetime.now(timezone.utc)

    params = {
        "symbol": ",".join(SYMBOLS),
        "interval": "1week",
        "outputsize": OUTPUT_SIZE_1W,
        "order": "desc",
        "format": "JSON",
        "apikey": API_KEY,
    }

    logging.info("Requesting interval=1week, outputsize=%s", OUTPUT_SIZE_1W)

    try:
        response = requests.get(BASE_URL, params=params, timeout=30)
    except requests.RequestException as exc:
        raise RuntimeError(f"1W request failed: {type(exc).__name__}") from None

    if response.status_code != 200:
        try:
            api_error = response.json().get("message", "No API message")
        except ValueError:
            api_error = "Non-JSON response"

        raise RuntimeError(
            f"1W API returned HTTP {response.status_code}: {api_error}"
        )

    try:
        data = response.json()
    except ValueError:
        raise RuntimeError("1W API returned invalid JSON") from None

    results = []

    for symbol in SYMBOLS:
        symbol_data = data.get(symbol)

        if not symbol_data:
            logging.warning("1W %s -> No response object", symbol)
            continue

        if symbol_data.get("status") == "error":
            logging.warning("1W %s -> API error: %s", symbol, symbol_data.get("message"))
            continue

        values = symbol_data.get("values")
        if not values:
            logging.warning("1W %s -> No values returned", symbol)
            continue

        try:
            closed_bar = get_last_closed_weekly_bar(values, now_utc)
        except (KeyError, TypeError, ValueError) as exc:
            logging.warning("1W %s -> Invalid bar datetime: %s", symbol, type(exc).__name__)
            continue

        if not closed_bar:
            logging.warning("1W %s -> No closed 1W bar found", symbol)
            continue

        try:
            bar_open_exchange = parse_weekly_bar_datetime(closed_bar["datetime"])
            open_price = float(closed_bar["open"])
            close_price = float(closed_bar["close"])
        except (KeyError, TypeError, ValueError) as exc:
            logging.warning("1W %s -> Invalid OHLC data: %s", symbol, type(exc).__name__)
            continue

        if open_price <= 0 or close_price <= 0:
            logging.warning("1W %s -> Non-positive price data", symbol)
            continue

        bar_close_exchange = bar_open_exchange + timedelta(days=7)
        bar_close_utc = bar_close_exchange.astimezone(timezone.utc)
        bar_age = now_utc - bar_close_utc

        if bar_age < timedelta(0):
            logging.warning("1W %s -> Selected bar is not closed", symbol)
            continue

        if bar_age > MAX_1W_BAR_AGE:
            logging.warning(
                "1W %s -> Stale closed bar: close_utc=%s age=%s",
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
            "1W %s -> raw=%s open_exchange=%s close_exchange=%s "
            "close_utc=%s age=%s open=%s close=%s change=%.6f",
            symbol,
            closed_bar["datetime"],
            bar_open_exchange.isoformat(),
            bar_close_exchange.isoformat(),
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
    df_1w = fetch_1w()
    output_path = Path("pair_changes_1w.csv")
    temp_path = output_path.with_suffix(".tmp")
    df_1w.to_csv(temp_path, index=False)
    temp_path.replace(output_path)
    logging.info("Saved pair_changes_1w.csv with %s rows", len(df_1w))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logging.error("1W fetch failed: %s", exc)
        sys.exit(1)
