"""core7_pairs.py — local mirror of the fx_strength CORE-7 FX universe.

Source of truth is the ``fx_strength`` project. This file is a MANUAL mirror
kept in ``signalforge`` so scanners/agents here can reference the same set of
pairs without either repo importing the other. There is no automated sync —
update by hand when fx_strength's CORE-7 changes, and record the source
revision in the commit that touches this file.

CORE-7 pairs: AUD/USD, EUR/USD, GBP/USD, NZD/USD, USD/CAD, USD/CHF, USD/JPY.

Yahoo Finance ticker suffix ``=X`` is preserved for tools that consume this
dict via yfinance. Consumers that talk to MT5 (broker-side symbol names) must
maintain their own name → broker-symbol map (see ``entry_monitor.MT5_SYMBOL_MAP``).
"""

CORE7_PAIRS = {
    "AUDUSD": {"symbol": "AUDUSD=X", "group": "Forex"},
    "EURUSD": {"symbol": "EURUSD=X", "group": "Forex"},
    "GBPUSD": {"symbol": "GBPUSD=X", "group": "Forex"},
    "NZDUSD": {"symbol": "NZDUSD=X", "group": "Forex"},
    "USDCAD": {"symbol": "USDCAD=X", "group": "Forex"},
    "USDCHF": {"symbol": "USDCHF=X", "group": "Forex"},
    "USDJPY": {"symbol": "JPY=X",    "group": "Forex"},
}
