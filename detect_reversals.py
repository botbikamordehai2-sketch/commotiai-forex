from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = BASE_DIR / "reversal_signals.json"

TIMEFRAMES = {
    "D1": BASE_DIR / "price_history_1d.csv",
    "H4": BASE_DIR / "price_history_4h.csv",
    "H1": BASE_DIR / "price_history_1h.csv",
}

EXPECTED_PAIRS = {
    "AUD/USD",
    "EUR/USD",
    "GBP/USD",
    "NZD/USD",
    "USD/CAD",
    "USD/CHF",
    "USD/JPY",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def normalize_pair(value: object) -> str:
    return str(value).replace("=", "").strip().upper()


def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)

    average_gain = gains.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False,
    ).mean()
    average_loss = losses.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False,
    ).mean()

    rs = average_gain / average_loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def choose_price_columns(df: pd.DataFrame) -> tuple[str, str]:
    if {"previous_price", "latest_price"}.issubset(df.columns):
        return "previous_price", "latest_price"

    if {"open", "close"}.issubset(df.columns):
        return "open", "close"

    raise ValueError(
        "Expected price columns previous_price/latest_price "
        "or open/close."
    )


def reversal_for_pair(pair_df: pd.DataFrame, timeframe: str) -> dict:
    pair_df = pair_df.copy()

    timestamp_column = "timestamp"
    if timestamp_column not in pair_df.columns:
        raise ValueError(f"{timeframe}: timestamp column is missing")

    _, close_column = choose_price_columns(pair_df)

    pair_df[timestamp_column] = pd.to_datetime(
        pair_df[timestamp_column],
        utc=True,
        errors="coerce",
    )
    pair_df[close_column] = pd.to_numeric(
        pair_df[close_column],
        errors="coerce",
    )

    pair_df = pair_df.dropna(
        subset=[timestamp_column, close_column]
    ).sort_values(timestamp_column)

    if len(pair_df) < 55:
        return {
            "signal": "INSUFFICIENT_HISTORY",
            "score": 0,
            "reason": f"{len(pair_df)} rows available; need at least 55",
        }

    close = pair_df[close_column]
    ema_20 = close.ewm(span=20, adjust=False).mean()
    ema_50 = close.ewm(span=50, adjust=False).mean()
    rsi_14 = calculate_rsi(close)

    latest = -1
    previous = -2

    bullish_cross = (
        close.iloc[previous] <= ema_20.iloc[previous]
        and close.iloc[latest] > ema_20.iloc[latest]
    )
    bearish_cross = (
        close.iloc[previous] >= ema_20.iloc[previous]
        and close.iloc[latest] < ema_20.iloc[latest]
    )

    bullish_trend = ema_20.iloc[latest] > ema_50.iloc[latest]
    bearish_trend = ema_20.iloc[latest] < ema_50.iloc[latest]

    bullish_rsi = (
        pd.notna(rsi_14.iloc[previous])
        and pd.notna(rsi_14.iloc[latest])
        and rsi_14.iloc[previous] < 50 <= rsi_14.iloc[latest]
    )
    bearish_rsi = (
        pd.notna(rsi_14.iloc[previous])
        and pd.notna(rsi_14.iloc[latest])
        and rsi_14.iloc[previous] > 50 >= rsi_14.iloc[latest]
    )

    recent_close = close.tail(20)
    recent_high = float(recent_close.iloc[:-1].max())
    recent_low = float(recent_close.iloc[:-1].min())
    latest_close = float(close.iloc[latest])

    bullish_structure = latest_close > recent_high
    bearish_structure = latest_close < recent_low

    bullish_score = (
        35 * int(bullish_structure)
        + 25 * int(bullish_cross)
        + 20 * int(bullish_rsi)
        + 20 * int(bullish_trend)
    )
    bearish_score = (
        35 * int(bearish_structure)
        + 25 * int(bearish_cross)
        + 20 * int(bearish_rsi)
        + 20 * int(bearish_trend)
    )

    if bullish_score > bearish_score and bullish_score >= 40:
        signal = "BULLISH_REVERSAL_WATCH"
        score = bullish_score
    elif bearish_score > bullish_score and bearish_score >= 40:
        signal = "BEARISH_REVERSAL_WATCH"
        score = bearish_score
    else:
        signal = "NO_CONFIRMED_REVERSAL"
        score = max(bullish_score, bearish_score)

    return {
        "signal": signal,
        "score": int(score),
        "latest_close": round(latest_close, 6),
        "ema_20": round(float(ema_20.iloc[latest]), 6),
        "ema_50": round(float(ema_50.iloc[latest]), 6),
        "rsi_14": (
            round(float(rsi_14.iloc[latest]), 2)
            if pd.notna(rsi_14.iloc[latest])
            else None
        ),
        "structure": (
            "BULLISH_BREAKOUT"
            if bullish_structure
            else "BEARISH_BREAKDOWN"
            if bearish_structure
            else "NO_BREAK"
        ),
        "timestamp": pair_df[timestamp_column].iloc[latest].isoformat(),
    }


def load_timeframe(timeframe: str, path: Path) -> dict:
    if not path.exists():
        return {
            pair: {
                "signal": "MISSING_INPUT",
                "score": 0,
                "reason": f"Missing file: {path.name}",
            }
            for pair in sorted(EXPECTED_PAIRS)
        }

    df = pd.read_csv(path)

    if "pair" not in df.columns:
        raise ValueError(f"{timeframe}: pair column is missing")

    df["pair"] = df["pair"].map(normalize_pair)

    results = {}
    for pair in sorted(EXPECTED_PAIRS):
        pair_df = df[df["pair"] == pair]
        if pair_df.empty:
            results[pair] = {
                "signal": "MISSING_PAIR",
                "score": 0,
                "reason": f"{pair} not found in {path.name}",
            }
        else:
            results[pair] = reversal_for_pair(pair_df, timeframe)

    return results


def main() -> None:
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "analysis_status": "RESEARCH_ONLY",
        "read_only": True,
        "methodology": (
            "EMA20_EMA50_RSI14_and_20_bar_price_structure; "
            "not a trading instruction"
        ),
        "timeframes": {
            timeframe: load_timeframe(timeframe, path)
            for timeframe, path in TIMEFRAMES.items()
        },
    }

    temp_path = OUTPUT_PATH.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(OUTPUT_PATH)

    logging.info("Saved %s", OUTPUT_PATH.name)


if __name__ == "__main__":
    main()

