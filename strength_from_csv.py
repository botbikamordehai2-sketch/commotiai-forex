import csv
from pathlib import Path

from currency_strength_engine import (
    STRENGTH_UNIVERSE,
    calculate_currency_strength,
)


def load_returns_from_csv(csv_path: Path) -> dict[str, float]:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    returns: dict[str, float] = {}

    with csv_path.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        required_columns = {
            "pair",
            "previous_price",
            "latest_price",
        }

        if reader.fieldnames is None or not required_columns.issubset(reader.fieldnames):
            raise ValueError(
                "CSV must contain columns: "
                "pair,previous_price,latest_price"
            )

        for row_number, row in enumerate(reader, start=2):
            pair = row["pair"].strip()

            if pair in returns:
                raise ValueError(
                    f"Duplicate pair on CSV row {row_number}: {pair}"
                )

            try:
                previous = float(row["previous_price"])
                latest = float(row["latest_price"])
            except ValueError as error:
                raise ValueError(
                    f"Invalid price on CSV row {row_number}"
                ) from error

            if previous <= 0 or latest <= 0:
                raise ValueError(
                    f"Prices must be positive on CSV row {row_number}: {pair}"
                )

            returns[pair] = (latest / previous) - 1.0

    expected_pairs = set(STRENGTH_UNIVERSE)
    actual_pairs = set(returns)

    missing = sorted(expected_pairs - actual_pairs)
    unexpected = sorted(actual_pairs - expected_pairs)

    if missing or unexpected or len(returns) != len(expected_pairs):
        raise ValueError(
            "CSV pairs do not match the strength universe. "
            f"missing={missing}, unexpected={unexpected}, "
            f"rows={len(returns)}, expected_rows={len(expected_pairs)}"
        )

    return returns


def main() -> None:
    csv_path = Path(__file__).with_name("prices.csv")
    returns = load_returns_from_csv(csv_path)

    scores, exposures = calculate_currency_strength(returns)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)

    print("Currency strength from CSV price returns:")
    print()

    for currency, score in ranked:
        print(f"{currency}: {score:+.6%}")

    print()
    print(f"Pairs processed: {len(returns)}")
    print(f"Exposure check: {exposures}")


if __name__ == "__main__":
    main()