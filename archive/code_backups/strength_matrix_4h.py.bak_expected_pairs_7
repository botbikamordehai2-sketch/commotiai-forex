import logging
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

INPUT_PATH = Path("pair_changes_4h.csv")
OUTPUT_PATH = Path("signals_4h.csv")

EXPECTED_PAIRS = {
    "EUR/USD",
    "USD/CHF",
    "NZD/USD",
    "GBP/USD",
    "USD/JPY",
}

EXPECTED_CURRENCIES = {
    "EUR",
    "USD",
    "CHF",
    "NZD",
    "GBP",
    "JPY",
}

REQUIRED_COLUMNS = {
    "pair",
    "timestamp",
    "change",
}

MAX_4H_DATA_AGE = timedelta(hours=8)
SIGNAL_THRESHOLD = 0.0005


def fail(message: str) -> None:
    raise RuntimeError(message)


def load_and_validate_pair_changes() -> pd.DataFrame:
    if not INPUT_PATH.is_file():
        fail(f"{INPUT_PATH} not found")

    try:
        df = pd.read_csv(INPUT_PATH)
    except (OSError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        fail(f"Could not read {INPUT_PATH}: {type(exc).__name__}")

    if df.empty:
        fail(f"{INPUT_PATH} is empty")

    missing_columns = sorted(REQUIRED_COLUMNS - set(df.columns))
    if missing_columns:
        fail(
            f"{INPUT_PATH} missing required columns: {missing_columns}"
        )

    df = df.copy()
    df["pair"] = df["pair"].astype(str).str.strip()

    if df["pair"].duplicated().any():
        duplicates = sorted(
            df.loc[df["pair"].duplicated(), "pair"].unique()
        )
        fail(f"Duplicate pairs in {INPUT_PATH}: {duplicates}")

    actual_pairs = set(df["pair"])
    missing_pairs = sorted(EXPECTED_PAIRS - actual_pairs)
    unexpected_pairs = sorted(actual_pairs - EXPECTED_PAIRS)

    if (
        missing_pairs
        or unexpected_pairs
        or len(df) != len(EXPECTED_PAIRS)
    ):
        fail(
            "Invalid 4H pair set: "
            f"missing={missing_pairs}, "
            f"unexpected={unexpected_pairs}, "
            f"rows={len(df)}, "
            f"expected_rows={len(EXPECTED_PAIRS)}"
        )

    try:
        df["timestamp"] = pd.to_datetime(
            df["timestamp"],
            utc=True,
            errors="raise",
        )
    except (TypeError, ValueError) as exc:
        fail(
            f"Invalid timestamp in {INPUT_PATH}: "
            f"{type(exc).__name__}"
        )

    if df["timestamp"].isna().any():
        fail(f"Missing timestamp in {INPUT_PATH}")

    timestamps = df["timestamp"].drop_duplicates()
    if len(timestamps) != 1:
        formatted = sorted(ts.isoformat() for ts in timestamps)
        fail(f"4H timestamps are inconsistent: {formatted}")

    try:
        df["change"] = pd.to_numeric(
            df["change"],
            errors="raise",
        )
    except (TypeError, ValueError) as exc:
        fail(
            f"Invalid change value in {INPUT_PATH}: "
            f"{type(exc).__name__}"
        )

    if not df["change"].map(math.isfinite).all():
        fail(f"Non-finite change value in {INPUT_PATH}")

    for pair in df["pair"]:
        try:
            base, quote = pair.split("/")
        except ValueError:
            fail(f"Invalid pair format in {INPUT_PATH}: {pair!r}")

        if (
            base not in EXPECTED_CURRENCIES
            or quote not in EXPECTED_CURRENCIES
        ):
            fail(f"Unexpected currency in pair: {pair}")

    return df.sort_values("pair").reset_index(drop=True)


def validate_freshness(df: pd.DataFrame) -> None:
    now_utc = datetime.now(timezone.utc)
    data_timestamp = df["timestamp"].iloc[0].to_pydatetime()
    age = now_utc - data_timestamp

    logging.info(
        "4H input timestamp=%s age=%s rows=%s",
        data_timestamp.isoformat(),
        age,
        len(df),
    )

    if age < timedelta(0):
        fail(
            "4H input timestamp is in the future: "
            f"{data_timestamp.isoformat()}"
        )

    if age > MAX_4H_DATA_AGE:
        fail(
            "STALE DATA (4H): "
            f"timestamp={data_timestamp.isoformat()}, "
            f"age={age}, max_age={MAX_4H_DATA_AGE}"
        )


def compute_currency_strength(df: pd.DataFrame) -> pd.DataFrame:
    records = []

    for row in df.itertuples(index=False):
        base, quote = row.pair.split("/")
        records.append({"currency": base, "change": row.change})
        records.append({"currency": quote, "change": -row.change})

    strength_df = (
        pd.DataFrame(records)
        .groupby("currency", as_index=False)["change"]
        .mean()
        .rename(columns={"change": "strength"})
        .sort_values("strength", ascending=False)
        .reset_index(drop=True)
    )

    actual_currencies = set(strength_df["currency"])
    if actual_currencies != EXPECTED_CURRENCIES:
        fail(
            "Invalid currency set after calculation: "
            f"missing={sorted(EXPECTED_CURRENCIES - actual_currencies)}, "
            f"unexpected={sorted(actual_currencies - EXPECTED_CURRENCIES)}"
        )

    return strength_df


def compute_strength_matrix(
    strength_df: pd.DataFrame,
) -> pd.DataFrame:
    scores = dict(
        zip(strength_df["currency"], strength_df["strength"])
    )
    currencies = strength_df["currency"].tolist()
    matrix = []

    for base in currencies:
        row = {"currency": base}

        for quote in currencies:
            row[quote] = (
                0.0
                if base == quote
                else scores[base] - scores[quote]
            )

        matrix.append(row)

    return pd.DataFrame(matrix).set_index("currency")


def generate_signals(
    df_pairs: pd.DataFrame,
    strength_df: pd.DataFrame,
) -> pd.DataFrame:
    scores = dict(
        zip(strength_df["currency"], strength_df["strength"])
    )
    rows = []

    for row in df_pairs.itertuples(index=False):
        base, quote = row.pair.split("/")

        if base not in scores or quote not in scores:
            fail(f"Missing strength score for {row.pair}")

        diff = scores[base] - scores[quote]

        if diff >= SIGNAL_THRESHOLD:
            signal = "LONG"
        elif diff <= -SIGNAL_THRESHOLD:
            signal = "SHORT"
        else:
            signal = "NEUTRAL"

        rows.append(
            {
                "pair": row.pair,
                "timestamp": row.timestamp.isoformat(),
                "pair_change": row.change,
                "base_currency": base,
                "quote_currency": quote,
                "base_score": scores[base],
                "quote_score": scores[quote],
                "score_diff": diff,
                "signal": signal,
            }
        )

    signals_df = (
        pd.DataFrame(rows)
        .sort_values("pair")
        .reset_index(drop=True)
    )

    if len(signals_df) != len(EXPECTED_PAIRS):
        fail(
            "Signal generation incomplete: "
            f"rows={len(signals_df)}"
        )

    return signals_df


def save_signals_atomic(signals_df: pd.DataFrame) -> None:
    temp_path = OUTPUT_PATH.with_suffix(".tmp")
    signals_df.to_csv(temp_path, index=False)
    temp_path.replace(OUTPUT_PATH)

    logging.info(
        "Saved %s with %s rows",
        OUTPUT_PATH,
        len(signals_df),
    )


def main() -> None:
    df_pairs = load_and_validate_pair_changes()
    validate_freshness(df_pairs)

    strength_df = compute_currency_strength(df_pairs)
    logging.info(
        "4H Currency Strength:\n%s",
        strength_df.to_string(index=False),
    )

    matrix_df = compute_strength_matrix(strength_df)
    logging.info(
        "4H Base/Quote Strength Matrix:\n%s",
        matrix_df.to_string(),
    )

    signals_df = generate_signals(df_pairs, strength_df)
    logging.info(
        "4H Signals:\n%s",
        signals_df[
            ["pair", "score_diff", "signal"]
        ].to_string(index=False),
    )

    save_signals_atomic(signals_df)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logging.error("4H strength matrix failed: %s", exc)
        sys.exit(1)