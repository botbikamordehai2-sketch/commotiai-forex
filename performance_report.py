import logging
import os
import sys

import pandas as pd

OUTCOMES_FILE = "signal_outcomes.csv"
DETAIL_OUTPUT = "performance_detail.csv"
REPORT_OUTPUT = "performance_report.csv"
MINIMUM_SAMPLE_SIZE = 30

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def load_outcomes():
    if not os.path.exists(OUTCOMES_FILE):
        raise RuntimeError(f"Missing {OUTCOMES_FILE}; run evaluate_signal_outcomes.py first")
    df = pd.read_csv(OUTCOMES_FILE)
    required = {
        "signal_id", "horizon", "signal_time", "pair", "timeframe", "signal",
        "score_diff", "entry_price", "exit_price", "return_pct", "result", "status",
    }
    missing = sorted(required - set(df.columns))
    if missing:
        raise RuntimeError(f"{OUTCOMES_FILE} is missing required columns: {missing}")
    return df


def score_bucket(value):
    if pd.isna(value):
        return "UNKNOWN"
    value = abs(float(value))
    if value < 0.0005:
        return "<0.0005"
    if value < 0.0010:
        return "0.0005-0.0010"
    if value < 0.0020:
        return "0.0010-0.0020"
    return ">=0.0020"


def metrics(subset):
    total = len(subset)
    wins = int((subset["result"] == "WIN").sum())
    losses = int((subset["result"] == "LOSS").sum())
    flats = int((subset["result"] == "FLAT").sum())
    win_rate = (wins / total * 100.0) if total else 0.0
    avg_win = subset.loc[subset["result"] == "WIN", "return_pct"].mean()
    avg_loss = subset.loc[subset["result"] == "LOSS", "return_pct"].mean()
    expectancy = subset["return_pct"].mean()
    return {
        "signals": total, "wins": wins, "losses": losses, "flats": flats,
        "win_rate_pct": round(win_rate, 2),
        "avg_return_pct": round(expectancy, 6),
        "median_return_pct": round(subset["return_pct"].median(), 6),
        "total_return_pct": round(subset["return_pct"].sum(), 6),
        "avg_win_pct": round(avg_win, 6) if pd.notna(avg_win) else None,
        "avg_loss_pct": round(avg_loss, 6) if pd.notna(avg_loss) else None,
        "expectancy_pct": round(expectancy, 6),
        "min_return_pct": round(subset["return_pct"].min(), 6),
        "max_return_pct": round(subset["return_pct"].max(), 6),
        "minimum_sample_met": total >= MINIMUM_SAMPLE_SIZE,
    }


def summarize(detail, columns, scope):
    rows = []
    groups = detail.groupby(columns, dropna=False) if columns else [(None, detail)]
    for key, subset in groups:
        row = {"scope": scope}
        if columns:
            if not isinstance(key, tuple):
                key = (key,)
            row.update(dict(zip(columns, key)))
        row.update(metrics(subset))
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    outcomes = load_outcomes()
    detail = outcomes[
        (outcomes["status"].astype(str).str.upper() == "COMPLETED")
        & (outcomes["signal"].astype(str).str.upper().isin(["LONG", "SHORT"]))
        & (outcomes["result"].astype(str).str.upper().isin(["WIN", "LOSS", "FLAT"]))
    ].copy()

    if detail.empty:
        logging.warning("No completed directional outcomes found")
        return

    for column in ["entry_price", "exit_price", "return_pct", "score_diff"]:
        detail[column] = pd.to_numeric(detail[column], errors="coerce")
    detail = detail.dropna(subset=["entry_price", "exit_price", "return_pct"])
    detail["abs_score_diff"] = detail["score_diff"].abs()
    detail["score_diff_bucket"] = detail["abs_score_diff"].apply(score_bucket)
    detail = detail.sort_values(["horizon", "signal_time", "pair"]).reset_index(drop=True)
    detail.to_csv(DETAIL_OUTPUT, index=False)

    report_parts = [
        summarize(detail, ["horizon"], "overall_horizon"),
        summarize(detail, ["horizon", "timeframe"], "by_timeframe"),
        summarize(detail, ["horizon", "pair"], "by_pair"),
        summarize(detail, ["horizon", "signal"], "by_direction"),
        summarize(detail, ["horizon", "score_diff_bucket"], "by_score_diff_bucket"),
        summarize(detail, ["horizon", "timeframe", "pair"], "by_timeframe_pair"),
    ]
    report = pd.concat(report_parts, ignore_index=True, sort=False)
    report.to_csv(REPORT_OUTPUT, index=False)

    overall = report[report["scope"] == "overall_horizon"]
    print("\n=== PERFORMANCE: OVERALL BY HORIZON ===")
    print(overall.to_string(index=False))
    for _, row in overall.iterrows():
        if row["signals"] < MINIMUM_SAMPLE_SIZE:
            print(f"\nWARNING: {row['horizon']} has only {row['signals']} completed directional signals. Do not optimize thresholds before {MINIMUM_SAMPLE_SIZE} signals.")
    logging.info("Saved %s with %s evaluated records", DETAIL_OUTPUT, len(detail))
    logging.info("Saved %s with %s summary rows", REPORT_OUTPUT, len(report))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Performance report failed")
        sys.exit(1)
