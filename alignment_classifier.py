from collections import Counter

REQUIRED_TIMEFRAMES = ("W1", "D1", "H4", "H1")
VALID_DIRECTIONS = {"BULLISH", "BEARISH"}

CLASS_NAMES = (
    "FULL_4_OF_4",
    "HIGHER_3_OF_3_H1_OPPOSES",
    "THREE_OF_4_SAME",
    "TWO_VS_TWO",
    "INSUFFICIENT_OR_INVALID",
)


def normalize_direction(value):
    if not isinstance(value, str):
        return None

    normalized = value.strip().upper()

    if normalized in VALID_DIRECTIONS:
        return normalized

    return None


def classify_timeframe_directions(directions):
    """
    Classify one pair from its W1/D1/H4/H1 direction map.

    Expected input:
    {
        "W1": "BULLISH",
        "D1": "BULLISH",
        "H4": "BULLISH",
        "H1": "BEARISH"
    }
    """
    if not isinstance(directions, dict):
        return "INSUFFICIENT_OR_INVALID"

    normalized = {
        timeframe: normalize_direction(directions.get(timeframe))
        for timeframe in REQUIRED_TIMEFRAMES
    }

    if any(value is None for value in normalized.values()):
        return "INSUFFICIENT_OR_INVALID"

    w1 = normalized["W1"]
    d1 = normalized["D1"]
    h4 = normalized["H4"]
    h1 = normalized["H1"]

    if w1 == d1 == h4 == h1:
        return "FULL_4_OF_4"

    if w1 == d1 == h4 and h1 != w1:
        return "HIGHER_3_OF_3_H1_OPPOSES"

    counts = Counter(normalized.values())

    if 3 in counts.values() and 1 in counts.values():
        return "THREE_OF_4_SAME"

    if counts["BULLISH"] == 2 and counts["BEARISH"] == 2:
        return "TWO_VS_TWO"

    return "INSUFFICIENT_OR_INVALID"


def make_classification_summary(pair_records):
    """
    Receives iterable of records containing 'alignment_class'.
    Returns a stable summary with all expected class names.
    """
    summary = {class_name: 0 for class_name in CLASS_NAMES}

    for pair_record in pair_records:
        alignment_class = pair_record.get("alignment_class")

        if alignment_class not in summary:
            alignment_class = "INSUFFICIENT_OR_INVALID"

        summary[alignment_class] += 1

    return summary