import json

s = json.load(open("dashboard_snapshot_v2.json", encoding="utf-8"))

print("TOP LEVEL KEYS:")
print(sorted(s.keys()))

fields = [
    "generated_at_utc",
    "provider",
    "source",
    "timezone",
    "methodology",
    "methodology_version",
    "formula_version",
    "universe_version",
    "schema_version"
]

print("\nMETADATA:")
for field in fields:
    print(f"{field}={s.get(field)}")

print("\nTIMEFRAME DETAILS:")
for tf, data in s.get("timeframes", {}).items():
    print(tf, {
        "timestamp_utc": data.get("timestamp_utc"),
        "freshness": data.get("freshness"),
        "rows": data.get("rows"),
        "candle_state": data.get("candle_state"),
        "provider": data.get("provider")
    })