from currency_strength_engine import (
    CURRENCIES,
    STRENGTH_UNIVERSE,
    calculate_currency_strength,
)


def build_sample_returns() -> dict[str, float]:
    returns = {pair: 0.0 for pair in STRENGTH_UNIVERSE}

    for pair in STRENGTH_UNIVERSE:
        base, quote = pair.split("/")

        # USD חזק מול כל מטבע אחר.
        if base == "USD":
            returns[pair] = 1.0
        elif quote == "USD":
            returns[pair] = -1.0

        # JPY חלש מול כל מטבע אחר, מלבד USD שכבר נקבע לעיל.
        elif base == "JPY":
            returns[pair] = -1.0
        elif quote == "JPY":
            returns[pair] = 1.0

    return returns


def main() -> None:
    returns = build_sample_returns()

    scores, exposures = calculate_currency_strength(returns)

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)

    assert len(returns) == 28
    assert set(scores) == set(CURRENCIES)
    assert all(count == 7 for count in exposures.values())
    assert ranked[0][0] == "USD"
    assert ranked[-1][0] == "JPY"
    assert abs(sum(scores.values())) < 1e-12

    print("PASS: Currency-strength engine validated.")
    print()
    print("Currency strength ranking (strongest to weakest):")

    for currency, score in ranked:
        print(f"{currency}: {score:+.6f}")


if __name__ == "__main__":
    main()