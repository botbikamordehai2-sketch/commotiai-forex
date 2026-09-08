"""
risk_policy.py — Hard-limit Risk Policy for SignalForge
=========================================================
Evaluates current market state and returns a RiskDecision:
  ALLOW  — entry permitted under current conditions
  WARN   — entry permitted but with caveats
  BLOCK  — entry forbidden (hard rule violated)

Rules enforced (in priority order):
  1. Circuit Breaker locked              → BLOCK
  2. Daily drawdown >= 3.8%             → BLOCK  (FTMO/Blueberry)
  3. HIGH-impact news within 2h          → BLOCK
  4. BIAS killzone_advice == "AVOID"    → BLOCK
  5. BIAS confidence < 0.4              → WARN
  6. BIAS killzone_advice == "WAIT"     → WARN
  7. Instrument not in bias focus list  → WARN   (when confidence >= 0.6)
  8. All rules pass                     → ALLOW

Usage:
  from risk_policy import RiskPolicy, RiskDecision
  policy = RiskPolicy.from_adk_tools()
  decision = policy.evaluate(instrument="EURUSD")
  if decision.action == "BLOCK":
      print(decision.reason)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

load_dotenv(Path.home() / "tv_webhook" / ".env")

# ── Thresholds (mirrors entry_monitor.py + CLAUDE.md) ────────────────────────
MAX_DAILY_DRAWDOWN_PCT = float(os.getenv("MAX_DAILY_DRAWDOWN_PCT", "3.8"))
NEWS_BLOCK_HOURS       = int(os.getenv("NEWS_BLOCK_HOURS", "2"))
MIN_BIAS_CONFIDENCE    = float(os.getenv("MIN_BIAS_CONFIDENCE", "0.4"))
FOCUS_CONFIDENCE_THRESHOLD = float(os.getenv("FOCUS_CONFIDENCE_THRESHOLD", "0.6"))


@dataclass
class RiskDecision:
    action:     str          # "ALLOW" | "WARN" | "BLOCK"
    reason:     str          # human-readable explanation
    rules_hit:  list[str] = field(default_factory=list)
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%H:%M UTC"))

    @property
    def allowed(self) -> bool:
        return self.action in ("ALLOW", "WARN")

    @property
    def blocked(self) -> bool:
        return self.action == "BLOCK"

    def to_dict(self) -> dict:
        return {
            "action":       self.action,
            "reason":       self.reason,
            "rules_hit":    self.rules_hit,
            "evaluated_at": self.evaluated_at,
        }


class RiskPolicy:
    """
    Evaluates hard-limit trading rules against live system state.

    State is provided via injected callables so the policy is fully
    testable without network calls or file I/O.
    """

    def __init__(
        self,
        get_circuit_breaker:    Callable[[], dict],
        get_current_bias:       Callable[[], dict],
        check_news_filter:      Callable[[int], dict],
        get_drawdown_pct:       Callable[[], float | None],
        get_polymarket_regime:  Callable[[], dict] | None = None,
    ) -> None:
        self._cb         = get_circuit_breaker
        self._bias       = get_current_bias
        self._news       = check_news_filter
        self._drawdown   = get_drawdown_pct
        self._polymarket = get_polymarket_regime

    # ── factory ──────────────────────────────────────────────────────────────

    @classmethod
    def from_adk_tools(cls) -> "RiskPolicy":
        """Wire up the policy against the live ADK tool functions."""
        from adk_agent import (
            get_circuit_breaker,
            get_current_bias,
            check_news_filter,
        )
        try:
            from polymarket_adapter import polymarket_macro_guard
            _poly = polymarket_macro_guard
        except ImportError:
            _poly = None

        return cls(
            get_circuit_breaker   = get_circuit_breaker,
            get_current_bias      = get_current_bias,
            check_news_filter     = lambda h: check_news_filter(within_hours=h),
            get_drawdown_pct      = _read_drawdown_from_mt5,
            get_polymarket_regime = _poly,
        )

    # ── public ───────────────────────────────────────────────────────────────

    def evaluate(self, instrument: str | None = None) -> RiskDecision:
        """
        Run all rules and return the most restrictive RiskDecision.

        Args:
            instrument: Optional symbol to check focus-list rule (e.g. "EURUSD").
        """
        rules_hit: list[str] = []

        # ── Rule 1: Circuit Breaker ───────────────────────────────────────
        try:
            cb = self._cb()
            if cb.get("locked"):
                return RiskDecision(
                    action    = "BLOCK",
                    reason    = f"Circuit Breaker locked — {cb.get('lock_reason') or str(cb.get('trades_today')) + '/' + str(cb.get('max_daily')) + ' trades today'}",
                    rules_hit = ["circuit_breaker"],
                )
            rules_hit.append(f"CB ok ({cb.get('trades_today',0)}/{cb.get('max_daily',2)} trades)")
        except Exception as exc:
            rules_hit.append(f"CB check failed: {exc}")

        # ── Rule 2: Daily Drawdown ────────────────────────────────────────
        try:
            dd = self._drawdown()
            if dd is not None and dd >= MAX_DAILY_DRAWDOWN_PCT:
                return RiskDecision(
                    action    = "BLOCK",
                    reason    = f"Daily drawdown {dd:.1f}% >= limit {MAX_DAILY_DRAWDOWN_PCT}% (FTMO/Blueberry)",
                    rules_hit = rules_hit + ["drawdown_limit"],
                )
            if dd is not None:
                rules_hit.append(f"DD ok ({dd:.1f}%)")
        except Exception as exc:
            rules_hit.append(f"DD check failed: {exc}")

        # ── Rule 3: Polymarket Macro Guard ───────────────────────────────
        if self._polymarket:
            try:
                poly = self._polymarket()
                regime = poly.get("regime", "UNKNOWN")
                if regime == "RISK_BLOCK":
                    score = poly.get("score", 0)
                    return RiskDecision(
                        action    = "BLOCK",
                        reason    = f"Polymarket macro consensus extreme negative ({score:.0%}) — RISK_BLOCK",
                        rules_hit = rules_hit + ["polymarket_macro"],
                    )
                if regime == "RISK_OFF":
                    score = poly.get("score", 0)
                    rules_hit.append(f"Polymarket RISK_OFF ({score:.0%})")
                    warn_reasons_poly = [f"Polymarket macro RISK_OFF ({score:.0%})"]
                else:
                    rules_hit.append(f"Polymarket {regime}")
            except Exception as exc:
                rules_hit.append(f"Polymarket check failed: {exc}")

        # ── Rule 4: High-Impact News ──────────────────────────────────────
        try:
            news = self._news(NEWS_BLOCK_HOURS)
            if news.get("blocked"):
                return RiskDecision(
                    action    = "BLOCK",
                    reason    = f"HIGH-impact news in {NEWS_BLOCK_HOURS}h: {news.get('event')} @ {news.get('event_time','')}",
                    rules_hit = rules_hit + ["news_filter"],
                )
            rules_hit.append("news ok")
        except Exception as exc:
            rules_hit.append(f"news check failed: {exc}")

        # ── Rules 5–8: BIAS ───────────────────────────────────────────────
        warn_reasons: list[str] = []
        # carry over polymarket RISK_OFF warn if set
        try:
            warn_reasons.extend(warn_reasons_poly)  # type: ignore[name-defined]
        except NameError:
            pass
        try:
            bias = self._bias()

            # Rule 4: AVOID killzone
            if bias.get("killzone_advice") == "AVOID":
                return RiskDecision(
                    action    = "BLOCK",
                    reason    = f"BIAS killzone = AVOID — {bias.get('reasoning', '')[:120]}",
                    rules_hit = rules_hit + ["bias_avoid"],
                )

            # Rule 5: low confidence
            conf = float(bias.get("confidence", 1.0))
            if conf < MIN_BIAS_CONFIDENCE:
                warn_reasons.append(f"BIAS confidence low ({conf:.0%})")

            # Rule 6: WAIT killzone
            if bias.get("killzone_advice") == "WAIT":
                warn_reasons.append("BIAS killzone = WAIT")

            # Rule 7: instrument not in focus list
            if instrument and conf >= FOCUS_CONFIDENCE_THRESHOLD:
                focus = [p.upper() for p in bias.get("pairs_to_focus", [])]
                if focus and instrument.upper() not in focus:
                    warn_reasons.append(
                        f"{instrument} not in BIAS focus list {focus}"
                    )

            rules_hit.append(f"BIAS {bias.get('bias','?')} conf={conf:.0%} advice={bias.get('killzone_advice','?')}")

        except Exception as exc:
            rules_hit.append(f"BIAS check failed: {exc}")

        if warn_reasons:
            return RiskDecision(
                action    = "WARN",
                reason    = " | ".join(warn_reasons),
                rules_hit = rules_hit,
            )

        return RiskDecision(
            action    = "ALLOW",
            reason    = "All risk rules passed",
            rules_hit = rules_hit,
        )

    def evaluate_batch(self, instruments: list[str]) -> dict[str, RiskDecision]:
        """Evaluate a list of instruments. Shared state (CB, news, BIAS, Polymarket) is fetched once."""
        try:
            cb_state   = self._cb()
            bias_state = self._bias()
            news_state = self._news(NEWS_BLOCK_HOURS)
            dd_val     = self._drawdown()
            poly_state = self._polymarket() if self._polymarket else None
        except Exception:
            return {inst: self.evaluate(inst) for inst in instruments}

        static_policy = RiskPolicy(
            get_circuit_breaker   = lambda: cb_state,
            get_current_bias      = lambda: bias_state,
            check_news_filter     = lambda _h: news_state,
            get_drawdown_pct      = lambda: dd_val,
            get_polymarket_regime = (lambda: poly_state) if poly_state is not None else None,
        )
        return {inst: static_policy.evaluate(inst) for inst in instruments}


# ── MT5 drawdown helper ───────────────────────────────────────────────────────

def _read_drawdown_from_mt5() -> float | None:
    """Read daily drawdown % from MetaTrader5 API. Returns None if unavailable."""
    from pathlib import Path
    from datetime import date

    equity_file = Path(__file__).parent / "daily_start_equity.txt"
    today = date.today().isoformat()

    try:
        import MetaTrader5 as mt5
        if mt5.initialize():
            info = mt5.account_info()
            mt5.shutdown()
            if info:
                current = info.equity
                start = current
                if equity_file.exists():
                    content = equity_file.read_text(encoding="utf-8").strip()
                    if ":" in content:
                        file_date, val = content.split(":", 1)
                        if file_date == today:
                            start = float(val)
                if start > 0:
                    return round((start - current) / start * 100, 2)
    except Exception:
        pass

    if equity_file.exists():
        try:
            content = equity_file.read_text(encoding="utf-8").strip()
            if ":" in content:
                file_date, val = content.split(":", 1)
                if file_date == today:
                    return None  # have start equity but no current — can't compute
        except Exception:
            pass

    return None  # MT5 not available — don't block


# ── ADK tool wrapper ──────────────────────────────────────────────────────────

def evaluate_risk(instrument: str = "") -> dict:
    """
    ADK tool: evaluate risk policy for a given instrument.

    Args:
        instrument: Symbol to check (e.g. "EURUSD"). Empty string = no focus check.

    Returns:
        Dict with keys: action, reason, rules_hit, evaluated_at, allowed, blocked.
    """
    policy   = RiskPolicy.from_adk_tools()
    decision = policy.evaluate(instrument or None)
    return {**decision.to_dict(), "allowed": decision.allowed, "blocked": decision.blocked}
