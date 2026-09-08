"""
Daily Review — ועדת חקירה יומית
רץ כל בוקר, מנתח ביצועי אתמול, שולח דוח לטלגרם
"""
import sys
import os
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
import yfinance as yf
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv(Path.home() / "tv_webhook" / ".env")

TOKEN   = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("ALL_CHAT_ID", "1246833993")

LOG_FILE = Path(__file__).parent / "signals_log.json"

ASSETS = {
    "US100":  {"sym": "^NDX",     "group": "Indices"},
    "US500":  {"sym": "^GSPC",    "group": "Indices"},
    "XAUUSD": {"sym": "GC=F",     "group": "Commodities"},
    "XAGUSD": {"sym": "SI=F",     "group": "Commodities"},
    "USOIL":  {"sym": "CL=F",     "group": "Commodities"},
    "EURUSD": {"sym": "EURUSD=X", "group": "Forex"},
    "GBPUSD": {"sym": "GBPUSD=X", "group": "Forex"},
    "USDJPY": {"sym": "JPY=X",    "group": "Forex"},
    "USDCHF": {"sym": "USDCHF=X", "group": "Forex"},
    "USDCAD": {"sym": "USDCAD=X", "group": "Forex"},
    "AUDUSD": {"sym": "AUDUSD=X", "group": "Forex"},
    "AUDNZD": {"sym": "AUDNZD=X", "group": "Forex"},
    "AUDCAD": {"sym": "AUDCAD=X", "group": "Forex"},
    "AUDCHF": {"sym": "AUDCHF=X", "group": "Forex"},
    "AUDJPY": {"sym": "AUDJPY=X", "group": "Forex"},
}


def compute_rsi(series, period=14):
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, 1e-9)
    return 100 - 100 / (1 + rs)


def load_log():
    if LOG_FILE.exists():
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_log(data):
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def log_signal(name, direction, entry, sl, tp):
    data = load_log()
    data.append({
        "date":      datetime.now().strftime("%Y-%m-%d %H:%M"),
        "name":      name,
        "direction": direction,
        "entry":     entry,
        "sl":        sl,
        "tp":        tp,
        "closed":    False,
        "result":    None,
        "pct":       None,
    })
    save_log(data)


def close_signals_auto():
    """
    Fix באג 8: סרוק את כל האיתותים הפתוחים, בדוק מול מחיר נוכחי
    וסמן כסגור אם SL או TP נפגע.
    """
    data = load_log()
    changed = False

    for s in data:
        if s.get("closed", False):
            continue

        name = s["name"]
        ticker_sym = ASSETS.get(name, {}).get("sym")
        if not ticker_sym:
            continue

        try:
            h = yf.Ticker(ticker_sym).history(period="1d", interval="15m")
            if h.empty or len(h) < 2:
                continue

            # בדוק את המחיר הנמוך/גבוה של היום מול SL/TP
            low_day  = round(h["Low"].min(), 4)
            high_day = round(h["High"].max(), 4)

            entry  = s["entry"]
            sl     = s["sl"]
            tp     = s["tp"]
            closed = False
            result = None
            pct    = None

            if s["direction"] == "LONG":
                if low_day <= sl:
                    closed = True
                    result = "LOSS"
                    pct = round((sl - entry) / entry * 100, 2)
                elif high_day >= tp:
                    closed = True
                    result = "WIN"
                    pct = round((tp - entry) / entry * 100, 2)
            else:  # SHORT
                if high_day >= sl:
                    closed = True
                    result = "LOSS"
                    pct = round((entry - sl) / entry * 100, 2)
                elif low_day <= tp:
                    closed = True
                    result = "WIN"
                    pct = round((entry - tp) / entry * 100, 2)

            if closed:
                s["closed"] = True
                s["result"] = result
                s["pct"]    = pct
                changed = True
                print(f"  [CLOSED] {s['date']} {name} {s['direction']} {result} {pct:+.2f}%")
        except Exception:
            pass

    if changed:
        save_log(data)
        print("  [AUTO-CLOSE] סגירת איתותים הושלמה")


def analyze_yesterday():
    data   = load_log()
    today  = datetime.now().date()
    yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")

    yesterday_signals = [s for s in data if s["date"].startswith(yesterday)]

    results = []
    wins = 0

    for s in yesterday_signals:
        try:
            ticker = ASSETS.get(s["name"], {}).get("sym")
            if not ticker:
                continue
            h = yf.Ticker(ticker).history(period="2d", interval="1h")
            if len(h) < 2:
                continue

            entry     = s["entry"]
            now_price = round(h["Close"].iloc[-1], 4)
            diff      = now_price - entry
            if s["direction"] == "SHORT":
                diff = -diff
            pct    = round(diff / entry * 100, 2)
            result = "WIN" if diff > 0 else "LOSS"
            if diff > 0:
                wins += 1

            results.append({**s, "now": now_price, "result": result, "pct": pct})
        except:
            pass

    return results, wins


def get_vix():
    try:
        return round(yf.Ticker("^VIX").history(period="1d")["Close"].iloc[-1], 1)
    except:
        return None


def get_today_bias():
    bias = {}
    for name, info in ASSETS.items():
        try:
            h     = yf.Ticker(info["sym"]).history(period="5d", interval="1h")
            close = h["Close"]
            rsi   = compute_rsi(close).iloc[-1]
            ma50  = close.rolling(50).mean().iloc[-1]
            price = close.iloc[-1]
            trend = "BULL" if price > ma50 else "BEAR"
            bias[name] = {"rsi": round(rsi, 1), "trend": trend, "price": round(price, 4)}
        except:
            pass
    return bias


async def send_review(results, wins, vix, bias):
    import telegram
    bot = telegram.Bot(token=TOKEN)
    today = datetime.now().strftime("%d/%m/%Y")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%d/%m")

    total = len(results)
    rate  = round(wins / total * 100) if total else 0

    msg  = f"📋 *ועדת חקירה יומית — {today}*\n"
    msg += f"_ניתוח ביצועי {yesterday}_\n\n"

    if total == 0:
        msg += "אין איתותים מאתמול לניתוח.\n\n"
    else:
        msg += f"*ביצועי אתמול:* {wins}/{total} הצלחות ({rate}%)\n"
        msg += "─" * 28 + "\n"
        for r in results:
            icon = "✅" if r["result"] == "WIN" else "❌"
            msg += f"{icon} {r['direction']:5} {r['name']:7} | {r['pct']:+.2f}%\n"
        msg += "\n"

    # VIX
    if vix:
        vix_status = "🟢 רגיל" if vix < 20 else ("🟡 זהירות" if vix < 30 else "🔴 פאניקה")
        msg += f"*VIX:* {vix} — {vix_status}\n\n"

    # BIAS היום
    msg += "*BIAS להיום:*\n"
    for name, b in bias.items():
        trend_icon = "📈" if b["trend"] == "BULL" else "📉"
        msg += f"  {trend_icon} {name:7} RSI {b['rsi']:5} | {b['trend']}\n"

    # המלצות שיפור
    msg += "\n*המלצות:*\n"
    if vix and vix > 25:
        msg += "⚠️ VIX גבוה — אל תיכנס LONG על מדדים\n"
    bear_count = sum(1 for b in bias.values() if b["trend"] == "BEAR")
    if bear_count > 4:
        msg += "⚠️ רוב הנכסים בטרנד יורד — העדף SHORT\n"
    if rate < 50 and total > 3:
        msg += "⚠️ אחוז הצלחה נמוך — שקול להחמיר תנאי כניסה\n"
    if rate >= 60:
        msg += "✅ ביצועים טובים — המשך באותה אסטרטגיה\n"

    msg += "\n_DYOR — Not financial advice_"

    await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
    print(f"[REVIEW] דוח יומי נשלח | {wins}/{total} הצלחות ({rate}%)")


def run():
    print(f"[{datetime.now().strftime('%H:%M')}] ועדת חקירה יומית מתחילה...")

    # סגור אוטומטית signals שהגיעו ל-SL/TP לפני הניתוח
    close_signals_auto()

    results, wins = analyze_yesterday()
    vix           = get_vix()
    bias          = get_today_bias()

    print(f"  ביצועי אתמול: {wins}/{len(results)}")
    print(f"  VIX: {vix}")

    asyncio.run(send_review(results, wins, vix, bias))


if __name__ == "__main__":
    run()
