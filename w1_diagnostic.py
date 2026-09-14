import json

s = json.load(open("dashboard_snapshot_v2.json", encoding="utf-8"))

for pair in s.get("pairs", []):
    name = pair.get("pair")
    print(f"\n{name}")

    for tf in ["W1", "D1", "H4", "H1"]:
        row = pair.get("timeframes", {}).get(tf, {})
        print(tf, {
            "signal": row.get("signal"),
            "score_diff": row.get("score_diff"),
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": row.get("close"),
            "timestamp_utc": row.get("timestamp_utc"),
            "candle_state": row.get("candle_state"),
            "provider": row.get("provider"),
            "symbol": row.get("symbol")
        })