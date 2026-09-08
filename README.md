# commotiai-forex

Forex/Trading system — ICT/SMC methodology, RSI+MA20 EA, entry monitor, sim engine. Part of the [CommotiAI network](https://commotiai.com).

**Status:** 🏗️ Bootstrap (Wave 0). Code migration from `signalforge` in progress.

---

## Purpose

This repository holds the **trading** side of the CommotiAI network. Previously bundled with SEO/blog tooling inside `signalforge`, split out on 2026-09-08 so trading and content can evolve on independent CI, deployment, and permission models.

**In scope here:**

- `entry_monitor.py` — 11-asset RSI+MA20+MA50 scanner with Circuit Breaker (2 trades/day)
- `RSI_MA20_Bot.mq5` — MetaTrader 5 EA (FTMO / Blueberry Funded compliance)
- `sim_engine.py` / `sim_monitor.py` — 2-container paper trading system (Flask API on 5002)
- `daily_review.py` — post-close review committee
- `diamond_scanner.py`, `alert_engine.py`, `api_scan.py` — scanners and alerts
- `core7_pairs.py` — mirror of the fx_strength CORE-7 FX universe
- SMC strategies (Liquidity Sweep, MSS, FVG, Killzone)
- VIP funnel + Telegram bots for trading signals

**NOT in scope:** WordPress publishing, blog automation, SEO tools, general-purpose PR monitors, LinkedIn/Twitter bots — those stay in `signalforge` (and may split out further later).

---

## Repo status matrix

| Wave | Status | Contents |
|------|--------|----------|
| **0** — Bootstrap | 🏗️ in progress | Scaffolding, README, CI skeleton, .env.example, test harness |
| **1** — Core trading | ⏳ planned | `entry_monitor.py`, `test_entry_monitor.py`, `core7_pairs.py`, `RSI_MA20_Bot.mq5/ex5`, `run_checks.bat` |
| **2** — Scanners / agents | ⏳ planned | `diamond_scanner.py`, `sim_engine.py`, `sim_monitor.py`, `api_scan.py`, `alert_engine.py`, `strategies.py`, `multi_strategy.py`, `daily_review.py` |
| **3** — VIP / funnel | ⏳ planned | `telegram_vip.py`, `hatinok_server.py`, `hatinok.html`, `vip_funnel.py`, `welcome_bot.py`, `telegram_alerts.py`, `telegram_daily.py` |
| **4** — Docs / plans | ⏳ planned | `MASTER_PLAN.md`, `ICT_METHODOLOGY.md`, `DIAMOND_REPORT.md`, `NASDAQ_DAILY_BIAS.md`, `RESEARCH_REPORT.md`, `money_roadmap.md` |
| **5** — Signalforge cleanup | ⏳ planned | PR on `signalforge` removing what moved here |

Each Wave = one PR to review and merge. See [AGENTS.md](AGENTS.md) for the two-agent handoff protocol.

---

## Setup

Requires **Python 3.12+**.

```bash
git clone https://github.com/botbikamordehai2-sketch/commotiai-forex
cd commotiai-forex
python -m pip install -r requirements-dev.txt

# once Wave 1 lands:
python -m pip install -r requirements.txt
cp .env.example .env  # then fill in your keys
```

## Running checks

**On Linux/CI:**
```bash
ruff check .
pytest tests/ -n 1 -q
```

**On Windows (before touching a live MT5 account):**
```bat
run_checks.bat
```

Both must be green before any change reaches a live-money branch. See `CLAUDE.md` (once migrated) for the full rule set.

---

## Rules (do not violate)

- ⚠️ **Never run `mt5_bot.py`** (once migrated) — it disables AutoTrading on the terminal.
- ⚠️ **Never run `entry_monitor.py`** without a green `run_checks.bat` on the same commit.
- ⚠️ Circuit Breaker: **maximum 2 trades per day** enforced in `entry_monitor.py:79`.
- ⚠️ Blueberry / FTMO: max 1% risk/trade, max 3.8% daily DD, max 9% total DD — enforced in `RSI_MA20_Bot.mq5:17-19`.
- All file I/O uses `encoding="utf-8"` explicitly.

## Attribution

This repo is developed by two AI coding agents in coordination:

- **Claude Code** (Cloud) — architecture, cross-repo migration, PR authoring
- **Cline** (Local, on Windows) — local validation, `run_checks.bat` runs, live-MT5-adjacent testing

Every PR carries `[Claude Code]` or `[Cline]` in its title. Human review lives on the user (`@botbikamordehai2-sketch`).

## License

Currently unlicensed (All Rights Reserved). Decision on MIT/Apache pending — see issue tracker.
