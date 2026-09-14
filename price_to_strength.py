from currency_strength_engine import (
    STRENGTH_UNIVERSE,
    calculate_currency_strength,
)


def calculate_returns(
    previous_prices: dict[str, float],
    latest_prices: dict[str, float],
) -> dict[str, float]:
    returns: dict[str, float] = {}

    for pair in STRENGTH_UNIVERSE:
        previous = previous_prices[pair]
        latest = latest_prices[pair]

        if previous <= 0 or latest <= 0:
            raise ValueError(f"{pair}: prices must be positive")

        returns[pair] = (latest / previous) - 1.0

    return returns


def main() -> None:
    previous_prices = {
        pair: 100.0
        for pair in STRENGTH_UNIVERSE
    }

    latest_prices = {
        pair: 100.0
        for pair in STRENGTH_UNIVERSE
    }

    # מחירי דוגמה: USD מתחזק מול כל המטבעות האחרים.
    for pair in STRENGTH_UNIVERSE:
        base, quote = pair.split("/")

        if base == "USD":
            latest_prices[pair] = 101.0
        elif quote == "USD":
            latest_prices[pair] = 99.0

    returns = calculate_returns(previous_prices, latest_prices)
    scores, exposures = calculate_currency_strength(returns)

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)

    print("Currency strength from price returns:")
    print()

    for currency, score in ranked:
        print(f"{currency}: {score:+.6%}")

    print()
    print(f"Pairs processed: {len(returns)}")
    print(f"Exposure check: {exposures}")


if __name__ == "__main__":
    main()