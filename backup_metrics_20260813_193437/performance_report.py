import logging
import sys

import pandas as pd

JOURNAL_FILE = "signals_journal.csv"
DETAIL_OUTPUT = "performance_detail.csv"
SUMMARY_OUTPUT = "performance_summary.csv"
MINIMUM_SAMPLE_SIZE = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

HORIZONS = {
    "4H": {
        "status_column": "evaluation_4h_status",
        "price_column": "price_after_4h",
        "return_column": "return_4h_pct",
        "result_column": "result_4h",
    },
    "24H": {
        "status_column": "evaluation_24h_status",
        "price_column": "price_after_24h",
        "return_column": "return_24h_pct",
        "result_column": "result_24h",
    },
}


def load_journal() -> pd.DataFrame:
    df = pd.read_csv(JOURNAL_FILE)

    required_columns = {
        "signal_id",
        "signal_time",
        "pair",
        "timeframe",
        "signal",
        "entry_status",
        "entry_price",
        "score_diff",
        "evaluation_4h_status",
        "evaluation_24h_status",
        "price_after_4h",
        "price_after_24h",
        "return_4h_pct",
        "return_24h_pct",
        "result_4h",
        "result_24h",
    }

    missing_columns = sorted(required_columns - set(df.columns))

    if missing_columns:
        raise RuntimeError(
            f"{JOURNAL_FILE} is missing required columns: {missing_columns}"
        )

    return df


def build_completed_records(
    journal_df: pd.DataFrame,
) -> pd.DataFrame:
    records = []

    for horizon_name, config in HORIZONS.items():
        subset = journal_df[
            (journal_df["signal"].isin(["LONG", "SHORT"]))
            & (journal_df["entry_status"] == "RECORDED")
            & (journal_df[config["status_column"]] == "COMPLETED")
        ].copy()

        if subset.empty:
            continue

        subset["entry_price"] = pd.to_numeric(
            subset["entry_price"],
            errors="coerce",
        )
        subset["exit_price"] = pd.to_numeric(
            subset[config["price_column"]],
            errors="coerce",
        )
        subset["return_pct"] = pd.to_numeric(
            subset[config["return_column"]],
            errors="coerce",
        )
        subset["result"] = subset[config["result_column"]].astype(str)

        subset = subset.dropna(
            subset=["entry_price", "exit_price", "return_pct"]
        )

        subset = subset[
            subset["result"].isin(["WIN", "LOSS", "FLAT"])
        ]

        if subset.empty:
            continue

        subset["horizon"] = horizon_name
        subset["abs_score_diff"] = pd.to_numeric(
            subset["score_diff"],
            errors="coerce",
        ).abs()

        records.append(
            subset[
                [
                    "signal_id",
                    "signal_time",
                    "pair",
                    "timeframe",
                    "signal",
                    "score_diff",
                    "abs_score_diff",
                    "entry_price",
                    "exit_price",
                    "return_pct",
                    "result",
                    "horizon",
                ]
            ]
        )

    if not records:
        return pd.DataFrame(
            columns=[
                "signal_id",
                "signal_time",
                "pair",
                "timeframe",
                "signal",
                "score_diff",
                "abs_score_diff",
                "entry_price",
                "exit_price",
                "return_pct",
                "result",
                "horizon",
            ]
        )

    detail_df = pd.concat(records, ignore_index=True)

    return detail_df.sort_values(
        ["horizon", "signal_time", "pair"]
    ).reset_index(drop=True)


def calculate_metrics(
    subset: pd.DataFrame,
) -> dict:
    total = len(subset)
    wins = int((subset["result"] == "WIN").sum())
    losses = int((subset["result"] == "LOSS").sum())
    flats = int((subset["result"] == "FLAT").sum())

    return {
        "signals": total,
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "win_rate_pct": round((wins / total) * 100, 2),
        "avg_return_pct": round(subset["return_pct"].mean(), 6),
        "median_return_pct": round(subset["return_pct"].median(), 6),
        "total_return_pct": round(subset["return_pct"].sum(), 6),
        "min_return_pct": round(subset["return_pct"].min(), 6),
        "max_return_pct": round(subset["return_pct"].max(), 6),
    }


def summarize(
    detail_df: pd.DataFrame,
    group_columns: list[str],
    scope: str,
) -> pd.DataFrame:
    if detail_df.empty:
        return pd.DataFrame()

    rows = []

    if group_columns:
        groups = detail_df.groupby(group_columns, dropna=False)
    else:
        groups = [(None, detail_df)]

    for group_key, subset in groups:
        row = {"scope": scope}

        if group_columns:
            if not isinstance(group_key, tuple):
                group_key = (group_key,)

            for column, value in zip(group_columns, group_key):
                row[column] = value

        row.update(calculate_metrics(subset))
        rows.append(row)

    return pd.DataFrame(rows)


def main() -> None:
    journal_df = load_journal()
    detail_df = build_completed_records(journal_df)

    if detail_df.empty:
        logging.warning(
            "No completed directional evaluations found yet"
        )
        return

    detail_df.to_csv(DETAIL_OUTPUT, index=False)

    summaries = [
        summarize(detail_df, ["horizon"], "overall_horizon"),
        summarize(
            detail_df,
            ["horizon", "timeframe"],
            "by_timeframe",
        ),
        summarize(
            detail_df,
            ["horizon", "pair"],
            "by_pair",
        ),
        summarize(
            detail_df,
            ["horizon", "signal"],
            "by_direction",
        ),
        summarize(
            detail_df,
            ["horizon", "timeframe", "pair"],
            "by_timeframe_pair",
        ),
    ]

    summary_df = pd.concat(
        [item for item in summaries if not item.empty],
        ignore_index=True,
    )

    summary_df.to_csv(SUMMARY_OUTPUT, index=False)

    logging.info(
        "Saved %s with %s evaluated records",
        DETAIL_OUTPUT,
        len(detail_df),
    )
    logging.info(
        "Saved %s with %s summary rows",
        SUMMARY_OUTPUT,
        len(summary_df),
    )

    print("\n=== PERFORMANCE: OVERALL BY HORIZON ===")
    overall = summary_df[
        summary_df["scope"] == "overall_horizon"
    ]
    print(overall.to_string(index=False))

    print("\n=== PERFORMANCE: BY TIMEFRAME ===")
    by_timeframe = summary_df[
        summary_df["scope"] == "by_timeframe"
    ]
    print(by_timeframe.to_string(index=False))

    sample_sizes = overall[["horizon", "signals"]]

    for _, row in sample_sizes.iterrows():
        if row["signals"] < MINIMUM_SAMPLE_SIZE:
            print(
                f"\nWARNING: {row['horizon']} has only "
                f"{row['signals']} completed directional signals. "
                f"Do not optimize thresholds before at least "
                f"{MINIMUM_SAMPLE_SIZE} signals."
            )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Performance report failed")
        sys.exit(1)