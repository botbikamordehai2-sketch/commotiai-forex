"""
Entry Monitor — מנטר הזדמנויות כניסה ושולח התראת טלגרם
רץ כל 15 דקות, שולח רק כשיש סיגנל אמיתי
"""
import sys
import asyncio
import os
import time
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
import yfinance as yf
import pandas as pd
from dotenv import load_dotenv

try:
    from risk_policy import RiskPolicy as _RiskPolicy
    _RISK_POLICY_AVAILABLE = True
except ImportError:
    _RISK_POLICY_AVAILABLE = False

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv(Path.home() / "tv_webhook" / ".env")

# FX universe note: signalforge is intentionally NOT importing core7_pairs.CORE7_PAIRS
# here. The full CORE-7 set (fx_strength source of truth) includes USDJPY, which was
# removed from this file by commit f2ef828 on perf grounds (3/51 = 6% WR, -4.58% P&L
# over 477 signals). Splatting **CORE7_PAIRS would silently reintroduce USDJPY and
# undo that decision. Add CORE-7 pairs one at a time here, after confirming each one
# passes local perf gating.
ASSETS = {
    # מדדים
    "US100":   {"symbol": "^NDX",     "group": "Indices"},
    "US500":   {"symbol": "^GSPC",    "group": "Indices"},
    # סחורות — XAGUSD (20% WR, -6.93%) ו-USOIL (19% WR, -12.49%) הוסרו
    "XAUUSD":  {"symbol": "GC=F",     "group": "Commodities"},
    # פורקס — עיקריים — USDJPY (6% WR, -4.58%) הוסר; NZDUSD חדש (אין דאטת perf, מנוטר)
    "EURUSD":  {"symbol": "EURUSD=X", "group": "Forex"},
    "GBPUSD":  {"symbol": "GBPUSD=X", "group": "Forex"},
    "USDCHF":  {"symbol": "USDCHF=X", "group": "Forex"},
    "USDCAD":  {"symbol": "USDCAD=X", "group": "Forex"},
    "AUDUSD":  {"symbol": "AUDUSD=X", "group": "Forex"},
    "NZDUSD":  {"symbol": "NZDUSD=X", "group": "Forex"},
    # פורקס — AUD crosses — AUDCHF (7% WR, -5.89%) ו-AUDJPY (4% WR, -4.26%) הוסרו
    "AUDNZD":  {"symbol": "AUDNZD=X", "group": "Forex"},
    "AUDCAD":  {"symbol": "AUDCAD=X", "group": "Forex"},
}

INTERVAL   = 15 * 60   # 15 דקות
CHAT_ID    = os.getenv("ALL_CHAT_ID", os.getenv("NASDAQ_CHAT_ID", "1246833993"))
TOKEN      = os.getenv("TELEGRAM_TOKEN")

# ── WhatsApp (CallMeBot) ───────────────────────────────────
# הגדרה: שלח "I allow callmebot to send me messages" ל-+34 644 65 21 91
# ותקבל API key חזרה בWhatsApp. הכנס ב-.env:
#   WHATSAPP_PHONE=972XXXXXXXXX   (כולל קידומת ללא +)
#   WHATSAPP_APIKEY=XXXXXXXX
WHATSAPP_PHONE  = os.getenv("WHATSAPP_PHONE")
WHATSAPP_APIKEY = os.getenv("WHATSAPP_APIKEY")

MT5_FILES  = r"C:\Users\gfdh5555\AppData\Roaming\MetaQuotes\Terminal\Common\Files"

MT5_SYMBOL_MAP = {
    "US100":  "US100.cash",
    "US500":  "US500.cash",
    "XAUUSD": "XAUUSD",
    "EURUSD": "EURUSD",
    "GBPUSD": "GBPUSD",
    "USDCHF": "USDCHF",
    "USDCAD": "USDCAD",
    "AUDUSD": "AUDUSD",
    "NZDUSD": "NZDUSD",
    "AUDNZD": "AUDNZD",
    "AUDCAD": "AUDCAD",
}

alerted = {}   # מניעת כפילויות: {asset: last_signal}
_news_cache = {"time": 0, "events": []}  # cache ל-15 דקות

# ── Circuit Breaker (HARD LOCK) ─────────────────────────────
MAX_DAILY_TRADES     = 2      # FTMO/CLAUDE.md: מקסימום 2 עסקאות ביום
DAILY_PROFIT_TARGET  = 100   # $ — עצור אם הרווח היומי הושג
DAILY_DRAWDOWN_LIMIT = 4.0   # % — Blueberry Funded: daily drawdown limit
LOCK_FILE            = Path(__file__).parent / "circuit_breaker.lock"
TRADES_TODAY_FILE    = Path(__file__).parent / "trades_today.txt"
DAILY_EQUITY_FILE    = Path(__file__).parent / "daily_start_equity.txt"
PID_FILE             = Path(__file__).parent / "entry_monitor.pid"
_circuit = {"date": None, "trades_today": 0}


def ensure_single_instance():
    """מונע הרצת יותר מ-instance אחד. Fix: באג 3 — ריבוי instances."""
    import os
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text(encoding="utf-8").strip())
            import psutil
            if psutil.pid_exists(old_pid):
                print(f"[ABORT] כבר רץ instance (PID {old_pid}). יוצא.")
                sys.exit(0)
        except Exception:
            pass  # PID ישן לא קיים — ממשיכים
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")


def cleanup_pid():
    if PID_FILE.exists():
        PID_FILE.unlink()

# ── Session Filter ─────────────────────────────────────────
# Month-end / Quarter-end rebalancing: חסום 15:00-17:00 UTC
# גם ביום רגיל — לא לסחור בגז טבעי (high vol) אחרי 21:00 UTC
BLOCKED_HOURS_UTC = (15, 16)  # tuple של שעות חסומות (UTC)


def session_filter_check() -> bool:
    """False = שעת Rebalancing / סגירת חודש — לא נכנסים."""
    hour = datetime.now(timezone.utc).hour
    day  = datetime.now().day
    month_end = day >= 28  # 28-31 לחודש = סיכון Rebalancing

    if month_end and hour in BLOCKED_HOURS_UTC:
        print(f"  [SESSION FILTER] {hour}:xx UTC | Month-end rebalancing window — נעול")
        return False
    return True


def circuit_breaker_check() -> bool:
    """Hard lock: מקסימום 2 עסקאות ביום. Fix: באג 1+2."""
    today = datetime.now().date().isoformat()

    # Fix באג 2: נקה קבצים רק אם הם מיום קודם (לא בכל startup)
    if _circuit["date"] != today:
        _circuit["date"] = today
        _circuit["trades_today"] = 0

        # Fix באג 1: שימוש ב-encoding="utf-8" מפורש לכל הקריאות/כתיבות
        if LOCK_FILE.exists():
            try:
                content = LOCK_FILE.read_text(encoding="utf-8")
                if today not in content:  # lock מיום אחר — מוחקים
                    LOCK_FILE.unlink()
            except (UnicodeDecodeError, UnicodeError):
                LOCK_FILE.unlink()  # קובץ פגום — מוחק
        if TRADES_TODAY_FILE.exists():
            try:
                content = TRADES_TODAY_FILE.read_text(encoding="utf-8").strip()
                if not content.startswith(today):
                    TRADES_TODAY_FILE.unlink()
            except (UnicodeDecodeError, UnicodeError):
                TRADES_TODAY_FILE.unlink()  # קובץ פגום — מוחק

    # Hard Lock — קיים ומיום היום
    if LOCK_FILE.exists():
        try:
            content = LOCK_FILE.read_text(encoding="utf-8")
        except (UnicodeDecodeError, UnicodeError):
            pass
        else:
            if today in content:
                print("  [CIRCUIT BREAKER — HARD LOCK] נעול. אין כניסות היום.")
                return False

    # קרא מונה מיום היום
    if TRADES_TODAY_FILE.exists():
        try:
            line = TRADES_TODAY_FILE.read_text(encoding="utf-8").strip()
            # פורמט: "2026-04-30:3"
            if ":" in line:
                file_date, count = line.split(":", 1)
                _circuit["trades_today"] = int(count) if file_date == today else 0
            else:
                _circuit["trades_today"] = int(line)
        except Exception:
            _circuit["trades_today"] = 0

    print(f"  [CB] עסקאות היום: {_circuit['trades_today']}/{MAX_DAILY_TRADES}")

    if _circuit["trades_today"] >= MAX_DAILY_TRADES:
        LOCK_FILE.write_text(f"LOCKED:{today}:{_circuit['trades_today']} trades", encoding="utf-8")
        print(f"  [CIRCUIT BREAKER — LOCKED] {_circuit['trades_today']}/{MAX_DAILY_TRADES} — נעול עד חצות")
        return False
    return True


def increment_trade_counter():
    """Fix באג 1: עדכן מונה + כתוב קובץ עם תאריך."""
    today = datetime.now().date().isoformat()
    _circuit["trades_today"] += 1
    # שמור עם תאריך כדי שהבדיקה תזהה יום חדש נכון
    TRADES_TODAY_FILE.write_text(f"{today}:{_circuit['trades_today']}", encoding="utf-8")
    print(f"  [CB] מונה עודכן: {_circuit['trades_today']}/{MAX_DAILY_TRADES}")

    if _circuit["trades_today"] >= MAX_DAILY_TRADES:
        LOCK_FILE.write_text(f"LOCKED:{today}:{_circuit['trades_today']} trades", encoding="utf-8")
        print(f"  [CIRCUIT BREAKER — LOCKED] {_circuit['trades_today']}/{MAX_DAILY_TRADES} — נעול עד חצות")


def drawdown_check() -> bool:
    """Blueberry Funded: עצור אם daily drawdown הגיע ל-4%.
    קורא equity ישירות מ-MetaTrader5 API."""
    today = datetime.now().date().isoformat()
    current_equity = None

    try:
        import MetaTrader5 as mt5
        if mt5.initialize():
            info = mt5.account_info()
            mt5.shutdown()
            if info:
                current_equity = info.equity
    except Exception:
        pass

    if current_equity is None:
        return True  # לא נגיש — לא חוסמים

    # שמור/טען equity בתחילת היום
    start_equity = current_equity
    if DAILY_EQUITY_FILE.exists():
        try:
            content = DAILY_EQUITY_FILE.read_text(encoding="utf-8").strip()
            if ":" in content:
                file_date, val = content.split(":", 1)
                if file_date == today:
                    start_equity = float(val)
                else:
                    DAILY_EQUITY_FILE.write_text(f"{today}:{current_equity:.2f}", encoding="utf-8")
        except (UnicodeDecodeError, UnicodeError):
            DAILY_EQUITY_FILE.write_text(f"{today}:{current_equity:.2f}", encoding="utf-8")
    else:
        DAILY_EQUITY_FILE.write_text(f"{today}:{current_equity:.2f}", encoding="utf-8")

    if start_equity <= 0:
        return True

    dd_pct = (start_equity - current_equity) / start_equity * 100
    print(f"  [DD] Drawdown יומי: -{dd_pct:.2f}% (גבול: {DAILY_DRAWDOWN_LIMIT}%)")

    if dd_pct >= DAILY_DRAWDOWN_LIMIT:
        print(f"  [DRAWDOWN BLOCK] -{dd_pct:.1f}% — עוצר מסחר להיום! (Blueberry limit)")
        return False
    return True


def get_high_impact_news(within_hours: int = 2) -> str | None:
    """מחזיר שם האירוע אם יש HIGH impact event ב-N שעות הקרובות, אחרת None"""
    global _news_cache
    now_ts = time.time()

    # cache — מרענן כל 15 דקות
    if now_ts - _news_cache["time"] > 900:
        try:
            r = requests.get(
                "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
                timeout=5
            )
            _news_cache = {"time": now_ts, "events": r.json()}
        except:
            return None  # אם API נכשל — לא חוסמים

    now_utc = datetime.now(timezone.utc)
    cutoff  = now_utc + timedelta(hours=within_hours)

    for ev in _news_cache["events"]:
        if ev.get("impact") != "High":
            continue
        try:
            ev_time = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
            if now_utc <= ev_time <= cutoff:
                return ev.get("title", "HIGH NEWS")
        except:
            continue
    return None


def send_whatsapp_alert(entries: list):
    """שולח התראת WhatsApp דרך CallMeBot API (HTTP בלבד, ללא browser)."""
    if not WHATSAPP_PHONE or not WHATSAPP_APIKEY:
        return  # לא מוגדר — מדלג בשקט
    try:
        now = datetime.now().strftime("%H:%M")
        lines = [f"ENTRY ALERT {now}"]
        for e in entries:
            arrow = "BUY" if e["direction"] == "LONG" else "SELL"
            lines.append(f"{arrow} {e['name']} | RSI:{e['rsi']} | IN:{e['price']} SL:{e['sl']} TP:{e['tp']}")
        text = "\n".join(lines)

        requests.get(
            "https://api.callmebot.com/whatsapp.php",
            params={"phone": WHATSAPP_PHONE, "text": text, "apikey": WHATSAPP_APIKEY},
            timeout=10,
        )
        print(f"  [WHATSAPP] נשלח ל-{WHATSAPP_PHONE}")
    except Exception as ex:
        print(f"  [WHATSAPP] שגיאה: {ex}")


def write_mt5_signal(name: str, direction: str):
    mt5_sym = MT5_SYMBOL_MAP.get(name)
    if not mt5_sym:
        return
    path = os.path.join(MT5_FILES, f"signal_{mt5_sym}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"{direction},{int(time.time())}")
    print(f"  [MT5 BRIDGE] {mt5_sym} {direction} → {path}")


def compute_rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, 1e-9)
    return round(100 - 100 / (1 + rs.iloc[-1]), 1)


def _fetch_with_retry(symbol: str, period: str = "5d", interval: str = "15m", retries: int = 3) -> "pd.DataFrame":
    for attempt in range(retries):
        try:
            h = yf.Ticker(symbol).history(period=period, interval=interval)
            if not h.empty:
                return h
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(2 ** attempt)
    return pd.DataFrame()


def check_entry(name: str, info: dict) -> dict | None:
    try:
        h    = _fetch_with_retry(info["symbol"])
        if h.empty or len(h) < 50:
            return None

        close = h["Close"]
        price = round(close.iloc[-1], 4)
        rsi   = compute_rsi(close)
        ma20  = close.rolling(20).mean()
        ma50  = close.rolling(50).mean()
        ma20v = round(ma20.iloc[-1], 4)
        ma50v = round(ma50.iloc[-1], 4)

        # פילטר טרנד MA50
        trend_up   = price > ma50v
        trend_down = price < ma50v

        # ── Fix באג 4: Anti-trend momentum filter ──────────────
        # בדוק אם 3 נרות אחרונים באותו כיוון (בלי reversal)
        last3 = close.iloc[-3:].values
        last3_bullish = all(last3[i] > last3[i-1] for i in range(1, len(last3)))
        last3_bearish = all(last3[i] < last3[i-1] for i in range(1, len(last3)))

        # RSI כיוון (rising/falling) — חישוב RSI וקטורי מלא
        delta2 = close.diff()
        gain2  = delta2.clip(lower=0)
        loss2  = (-delta2.clip(upper=0))
        avg_gain = gain2.rolling(14).mean()
        avg_loss = loss2.rolling(14).mean()
        rs2 = avg_gain / avg_loss.replace(0, 1e-9)
        rsi_series = (100 - 100 / (1 + rs2)).dropna()
        rsi_rising  = len(rsi_series) >= 4 and rsi_series.iloc[-1] > rsi_series.iloc[-3]
        rsi_falling = len(rsi_series) >= 4 and rsi_series.iloc[-1] < rsi_series.iloc[-3]

        signals = []
        direction = None

        # ── LONG signals (רק עם טרנד עולה + מומנטום) ──────────
        if trend_up:
            # Fix באג 5: חסום LONG אם 3 נרות אחרונים דוביים (trend momentum reversal)
            if last3_bearish:
                pass  # no LONG signals on bearish momentum
            elif rsi < 30 and rsi_rising:
                signals.append(f"RSI {rsi} Oversold + Rising — ריבאונד?")
                direction = "LONG"
            elif 50 < rsi < 65 and price > ma20v and rsi_rising:
                signals.append(f"RSI {rsi} מומנטום + מעל MA20 + RSI Rising")
                direction = "LONG"
            elif 30 <= rsi <= 50 and rsi_rising and price > ma20v:
                signals.append(f"RSI {rsi} מתאושש + מעל MA20")
                direction = "LONG"
            prev_below = close.iloc[-3] < ma20.iloc[-3]
            if prev_below and price > ma20v and rsi < 65 and not last3_bearish:
                signals.append("Cross above MA20")
                direction = "LONG"

        # ── SHORT signals (רק עם טרנד יורד + מומנטום) ──────────
        if trend_down:
            # Fix באג 5: חסום SHORT אם 3 נרות אחרונים שוריים (trend momentum reversal)
            if last3_bullish:
                pass  # no SHORT signals on bullish momentum
            elif rsi > 70 and rsi_falling:
                signals.append(f"RSI {rsi} Overbought + Falling")
                direction = "SHORT"
            elif 35 < rsi < 52 and price < ma20v and rsi_falling:
                signals.append(f"RSI {rsi} מומנטום שלילי + מתחת MA20 + RSI Falling")
                direction = "SHORT"
            elif 50 <= rsi <= 70 and rsi_falling and price < ma20v:
                signals.append(f"RSI {rsi} נחלש + מתחת MA20")
                direction = "SHORT"
            prev_above = close.iloc[-3] > ma20.iloc[-3]
            if prev_above and price < ma20v and rsi > 35 and not last3_bullish:
                signals.append("Cross below MA20")
                direction = "SHORT"

        if not signals or not direction:
            return None

        # מניעת כפילות — אותו סיגנל לא ישלח פעמיים ב-2 שעות
        key = f"{name}_{direction}"
        last = alerted.get(key, 0)
        if time.time() - last < 7200:
            return None

        alerted[key] = time.time()

        # פילטר חדשות — HIGH impact event ב-2 שעות הקרובות → חסום לגמרי
        news_event = get_high_impact_news(within_hours=2)
        if news_event:
            print(f"  [NEWS BLOCK] {name} — חדשות HIGH: {news_event}")
            alerted.pop(key, None)  # מאפס כדי שיישלח אחרי החדשות
            return None

        # חישוב ATR לקביעת SL/TP
        high  = h["High"]
        low   = h["Low"]
        atr   = (high - low).rolling(14).mean().iloc[-1]
        atr   = round(atr, 4)

        if direction == "LONG":
            sl = round(price - atr * 1.5, 4)
            tp = round(price + atr * 3.0, 4)
        else:
            sl = round(price + atr * 1.5, 4)
            tp = round(price - atr * 3.0, 4)

        return {
            "name":      name,
            "group":     info["group"],
            "direction": direction,
            "price":     price,
            "rsi":       rsi,
            "sl":        sl,
            "tp":        tp,
            "atr":       atr,
            "signals":   signals,
        }

    except Exception:
        return None


async def _dispatch_alerts(entries: list):
    """שולח לטלגרם + VIP בקריאה א-סינכרונית אחת (מונע ריבוי event loops)."""
    await send_alert(entries)
    try:
        from telegram_vip import send_signal_to_channels, BOT as _vip_bot
        if _vip_bot:
            for e in entries:
                await send_signal_to_channels(_vip_bot, e)
    except Exception:
        pass


async def send_alert(entries: list):
    import telegram
    bot = telegram.Bot(token=TOKEN)
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    msg = f"*ENTRY ALERT — {now}*\n"
    msg += f"_{len(entries)} הזדמנות{'ות' if len(entries)>1 else ''} נמצאה_\n\n"

    for e in entries:
        arrow = "BUY" if e["direction"] == "LONG" else "SELL"
        emoji = "🟢" if e["direction"] == "LONG" else "🔴"

        # סטטוס כניסה לפי RSI
        rsi = e["rsi"]
        if e["direction"] == "LONG":
            if rsi < 30:
                status = "✅ מוכן לכניסה עכשיו"
            elif rsi < 40:
                status = "⏳ המתן לאישור — RSI מתקרב"
            else:
                status = f"⏳ המתן למחיר {e['sl']} לפני כניסה"
        else:
            if rsi > 70:
                status = "✅ מוכן לכניסה עכשיו"
            elif rsi > 60:
                status = "⏳ המתן לאישור — RSI מתקרב"
            else:
                status = f"⏳ המתן למחיר {e['sl']} לפני כניסה"

        msg += f"{emoji} *{e['name']}* — {arrow}\n"
        msg += f"   {status}\n"
        msg += f"   💰 כניסה: `{e['price']}`\n"
        msg += f"   🛑 SL: `{e['sl']}`\n"
        msg += f"   🎯 TP: `{e['tp']}`\n"
        msg += f"   📊 RSI: {rsi}\n"
        for s in e["signals"]:
            msg += f"   • {s}\n"
        msg += "\n"

    msg += "_DYOR — Not financial advice_"

    await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
    print(f"[ALERT] נשלח! {[e['name'] for e in entries]}")


def _print_performance_summary():
    """מדפיס סיכום ביצועים מ-signals_log.json בתחילת כל ריצה."""
    log_file = Path(__file__).parent / "signals_log.json"
    if not log_file.exists():
        return
    try:
        import json
        signals = json.loads(log_file.read_text(encoding="utf-8"))
        closed = [s for s in signals if s.get("closed")]
        if not closed:
            return
        wins   = sum(1 for s in closed if s.get("result") == "WIN")
        losses = sum(1 for s in closed if s.get("result") == "LOSS")
        total  = wins + losses
        wr     = wins / total * 100 if total else 0
        pcts   = [s["pct"] for s in closed if s.get("pct") is not None]
        avg_pct = sum(pcts) / len(pcts) if pcts else 0
        print(f"  [PERF] {total} סיגנלים סגורים | WR: {wr:.0f}% | ממוצע P&L: {avg_pct:+.2f}%")
    except Exception:
        pass


def run_once():
    print(f"\n[{datetime.now().strftime('%H:%M')}] סורק כניסות...")
    _print_performance_summary()

    if not circuit_breaker_check():
        return
    if not drawdown_check():
        return
    if not session_filter_check():
        return

    # ── Risk Policy (ADK layer — bias + focus list) ──────────
    risk_decisions: dict = {}
    if _RISK_POLICY_AVAILABLE:
        try:
            _policy = _RiskPolicy.from_adk_tools()
            risk_decisions = _policy.evaluate_batch(list(ASSETS.keys()))
            # Check for a global hard block (news / bias AVOID)
            _global = _policy.evaluate()
            if _global.blocked:
                print(f"  [RISK POLICY — BLOCK] {_global.reason}")
                return
            if _global.action == "WARN":
                print(f"  [RISK POLICY — WARN] {_global.reason}")
        except Exception as _exc:
            print(f"  [RISK POLICY] unavailable: {_exc}")

    entries = []
    for name, info in ASSETS.items():
        dec = risk_decisions.get(name)
        if dec and dec.blocked:
            print(f"  {name:10} — RISK BLOCK: {dec.reason}")
            continue
        if dec and dec.action == "WARN":
            print(f"  {name:10} — RISK WARN:  {dec.reason}")
        result = check_entry(name, info)
        if result:
            entries.append(result)
            print(f"  SIGNAL: {name} {result['direction']} | RSI:{result['rsi']}")
        else:
            print(f"  {name:10} — אין סיגנל")

    if entries:
        for e in entries:
            write_mt5_signal(e["name"], e["direction"])
            increment_trade_counter()  # Fix באג 1: עדכן מונה לאחר כל signal
            try:
                from daily_review import log_signal
                log_signal(e["name"], e["direction"], e["price"], e["sl"], e["tp"])
            except Exception:
                pass

        asyncio.run(_dispatch_alerts(entries))
        send_whatsapp_alert(entries)
    else:
        print(f"  -> אין כניסות כרגע. הבא: {INTERVAL//60} דקות")


if __name__ == "__main__":
    ensure_single_instance()  # Fix באג 3: מונע ריבוי instances
    import atexit
    atexit.register(cleanup_pid)

    print("="*50)
    print(f"Entry Monitor פעיל — כל {INTERVAL//60} דקות")
    print(f"נכסים: {len(ASSETS)} | Chat: {CHAT_ID}")
    print(f"PID: {Path('entry_monitor.pid').read_text(encoding='utf-8') if Path('entry_monitor.pid').exists() else 'N/A'}")
    print("="*50)
    while True:
        run_once()
        time.sleep(INTERVAL)
