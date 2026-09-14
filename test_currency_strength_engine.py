from __future__ import annotations

import math
from collections import Counter
from itertools import combinations
from statistics import fmean


CURRENCIES = (
    "AUD",
    "CAD",
    "CHF",
    "EUR",
    "GBP",
    "JPY",
    "NZD",
    "USD",
)


def build_strength_universe(
    currencies: tuple[str, ...] = CURRENCIES,
) -> tuple[str, ...]:
    return tuple(
        f"{base}/{quote}"
        for base, quote in combinations(currencies, 2)
    )


STRENGTH_UNIVERSE = build_strength_universe()


def parse_pair(pair: str) -> tuple[str, str]:
    if not isinstance(pair, str):
        raise ValueError(f"Pair must be a string, got {type(pair).__name__}")

    parts = pair.split("/")

    if len(parts) != 2 or not all(parts):
        raise ValueError(f"Invalid pair format: {pair!r}")

    base, quote = parts

    if base == quote:
        raise ValueError(f"Self-pair is not allowed: {pair}")

    if base not in CURRENCIES or quote not in CURRENCIES:
        raise ValueError(f"Unsupported currency in pair: {pair}")

    return base, quote


def validate_strength_universe(
    universe: tuple[str, ...] = STRENGTH_UNIVERSE,
) -> Counter:
    expected_crosses = len(CURRENCIES) * (len(CURRENCIES) - 1) // 2

    if len(universe) != expected_crosses:
        raise ValueError(
            f"Expected {expected_crosses} economic crosses, found {len(universe)}"
        )

    canonical_pairs: set[tuple[str, str]] = set()
    exposures: Counter = Counter()

    for pair in universe:
        base, quote = parse_pair(pair)
        canonical = tuple(sorted((base, quote)))

        if canonical in canonical_pairs:
            raise ValueError(f"Duplicate economic cross: {pair}")

        canonical_pairs.add(canonical)
        exposures[base] += 1
        exposures[quote] += 1

    expected_exposures = len(CURRENCIES) - 1

    for currency in CURRENCIES:
        count = exposures[currency]

        if count != expected_exposures:
            raise ValueError(
                f"{currency} expected {expected_exposures} exposures, found {count}"
            )

    return exposures


def validate_returns(
    returns: dict[str, float],
    universe: tuple[str, ...] = STRENGTH_UNIVERSE,
) -> None:
    validate_strength_universe(universe)

    expected_pairs = set(universe)
    actual_pairs = set(returns)

    missing = sorted(expected_pairs - actual_pairs)
    unexpected = sorted(actual_pairs - expected_pairs)

    if missing or unexpected or len(returns) != len(expected_pairs):
        raise ValueError(
            "Return set does not match the strength universe. "
            f"missing={missing}, unexpected={unexpected}, "
            f"rows={len(returns)}, expected_rows={len(expected_pairs)}"
        )

    for pair, value in returns.items():
        parse_pair(pair)

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{pair}: return must be numeric")

        if not math.isfinite(float(value)):
            raise ValueError(f"{pair}: return must be finite")


def normalize_returns(
    returns: dict[str, float],
) -> dict[str, float]:
    return {pair: float(value) for pair, value in returns.items()}


def pair_contributions(
    pair: str,
    normalized_return: float,
) -> dict[str, float]:
    base, quote = parse_pair(pair)
    value = float(normalized_return)

    if not math.isfinite(value):
        raise ValueError(f"{pair}: normalized return must be finite")

    return {
        base: value,
        quote: -value,
    }


def calculate_currency_strength(
    returns: dict[str, float],
    universe: tuple[str, ...] = STRENGTH_UNIVERSE,
) -> tuple[dict[str, float], dict[str, int]]:
    validate_returns(returns, universe)

    normalized_returns = normalize_returns(returns)

    contributions: dict[str, list[float]] = {
        currency: []
        for currency in CURRENCIES
    }

    for pair in universe:
        pair_values = pair_contributions(
            pair,
            normalized_returns[pair],
        )

        for currency, contribution in pair_values.items():
            contributions[currency].append(contribution)

    expected_exposures = len(CURRENCIES) - 1

    exposures = {
        currency: len(values)
        for currency, values in contributions.items()
    }

    for currency, count in exposures.items():
        if count != expected_exposures:
            raise ValueError(
                f"{currency} expected {expected_exposures} contributions, found {count}"
            )

    scores = {
        currency: fmean(values)
        for currency, values in contributions.items()
    }

    if set(scores) != set(CURRENCIES):
        raise ValueError("Currency score output is incomplete")

    total_score = sum(scores.values())

    if not math.isclose(total_score, 0.0, abs_tol=1e-12):
        raise ValueError(
            f"Currency scores must sum to approximately zero, got {total_score}"
        )

    return scores, exposures