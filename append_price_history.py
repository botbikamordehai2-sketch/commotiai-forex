from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent

SOURCES = {
    "D1": {
        "source": BASE_DIR / "pair_changes_1d.csv",
        "history": BASE_DIR / "price_history_1d.csv",
    },
    "H4": {
        "source": BASE_DIR / "pair_changes_4h.csv",
        "history": BASE_DIR / "price_history_4h.csv",
    },
    "H1": {
        "source": BASE_DIR / "pair_changes_1h.csv",
        "history": BASE_DIR / "price_history_1h.csv",
    },
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


def source_to_history(df: pd.DataFrame, label: str) -> pd.DataFrame:
    if not {"pair", "timestamp"}.issubset(df.columns):
        missing = sorted({"pair", "timestamp"} - set(df.columns))
        raise ValueError(f"{label}: missing columns: {missing}")

    if {"open", "close"}.issubset(df.columns):
        history = df[["pair", "timestamp", "open", "close"]].copy()
    elif {"previous_price", "latest_price"}.issubset(df.columns):
        history = df[
            ["pair", "timestamp", "previous_price", "latest_price"]
        ].rename(
            columns={
                "previous_price": "open",
                "latest_price": "close",
            }
        )
    else:
        raise ValueError(
            f"{label}: missing open/close or "
            "previous_price/latest_price columns"
        )

    history["pair"] = history["pair"].map(normalize_pair)
    history["timestamp"] = pd.to_datetime(
        history["timestamp"],
        utc=True,
        errors="coerce",
    )
    history["open"] = pd.to_numeric(history["open"], errors="coerce")
    history["close"] = pd.to_numeric(history["close"], errors="coerce")

    history = history.dropna(subset=["pair", "timestamp", "open", "close"])
    history = history[history["pair"].isin(EXPECTED_PAIRS)].copy()

    if history.empty:
        raise ValueError(f"{label}: no valid rows for expected pairs")

    return history


def update_history(label: str, source: Path, history_path: Path) -> None:
    if not source.exists():
        logging.warning("%s: source not found: %s", label, source.name)
        return

    current = source_to_history(pd.read_csv(source), label)

    if history_path.exists():
        previous = pd.read_csv(history_path)
        previous["pair"] = previous["pair"].map(normalize_pair)
        previous["timestamp"] = pd.to_datetime(
            previous["timestamp"],
            utc=True,
            errors="coerce",
        )
        combined = pd.concat([previous, current], ignore_index=True)
    else:
        combined = current

    combined = combined.dropna(subset=["pair", "timestamp", "open", "close"])
    combined = combined.drop_duplicates(
        subset=["pair", "timestamp"],
        keep="last",
    ).sort_values(["pair", "timestamp"])

    temporary = history_path.with_suffix(".tmp")
    combined.to_csv(temporary, index=False)
    temporary.replace(history_path)

    counts = combined.groupby("pair").size()
    logging.info(
        "%s: saved %s; total rows=%s; minimum per pair=%s",
        label,
        history_path.name,
        len(combined),
        int(counts.min()),
    )


def main() -> None:
    for label, config in SOURCES.items():
        update_history(label, config["source"], config["history"])


if __name__ == "__main__":
    main()
