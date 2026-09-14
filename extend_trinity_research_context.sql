PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS research_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at_utc TEXT NOT NULL UNIQUE,
    research_only INTEGER NOT NULL CHECK (research_only IN (0, 1)),
    purpose TEXT,
    market_session_utc TEXT,
    timeframe_freshness_json TEXT NOT NULL,
    data_quality_flags_json TEXT NOT NULL,
    source_file TEXT NOT NULL,
    ingested_at_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pair_context (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    pair TEXT NOT NULL,
    alignment TEXT,
    display_status TEXT,
    signal_quality TEXT,
    h1_score_diff REAL,
    all_timeframe_timestamps_present INTEGER,
    timeframe_freshness_json TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES research_runs(id) ON DELETE CASCADE,
    UNIQUE (run_id, pair)
);

CREATE TABLE IF NOT EXISTS manual_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at_utc TEXT,
    event_time_utc TEXT,
    minutes_to_event REAL,
    event_window TEXT,
    currency TEXT,
    pair TEXT,
    category TEXT,
    severity TEXT,
    status TEXT,
    summary TEXT NOT NULL,
    source_url TEXT,
    verified_by TEXT,
    source_file TEXT NOT NULL,
    ingested_at_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (
        created_at_utc,
        event_time_utc,
        currency,
        pair,
        category,
        summary
    )
);

CREATE INDEX IF NOT EXISTS idx_pair_context_run_id
ON pair_context (run_id);

CREATE INDEX IF NOT EXISTS idx_pair_context_pair
ON pair_context (pair);

CREATE INDEX IF NOT EXISTS idx_manual_notes_event_time
ON manual_notes (event_time_utc);

CREATE INDEX IF NOT EXISTS idx_manual_notes_status
ON manual_notes (status);
