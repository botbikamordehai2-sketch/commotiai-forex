import MetaTrader5 as mt5
import datetime
import time
import requests
import json

# ==============================================================================
# ⚙️ הגדרות מערכת ואינטגרציות
# ==============================================================================
MONDAY_API_KEY = "eyJhbGciOiJIUzI1NiJ9.eyJ0aWQiOjcwMzMwMzQ4MiwiYWFpIjoxMSwidWlkIjoxMTYzMjY3NjIsImlhZCI6IjIwMjYtMDktMTNUMjE6MTQ6MDUuMDAwWiIsInBlciI6Im1lOndyaXRlIiwiYWN0aWQiOjM2ODc5OTU4LCJyZ24iOiJldWMxIn0.AQFJ6ap86GsMFhaAaQnlCAG9msUhphYwPr_50eXo7XU"
BOARD_ID = "5104102664"

TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""

MT5_LOGIN = 5055896172
MT5_PASSWORD = "@a1eHzTf"
MT5_SERVER = "MetaQuotes-Demo"

AUTO_TRADE = True
MAGIC_NUMBER = 777999

SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD", "US30", "NAS100"]

# ==============================================================================
# 🤖 פקודת מסחר דינמית ומותאמת נכס
# ==============================================================================
def has_open_position(symbol):
    positions = mt5.positions_get(symbol=symbol)
    return positions is not None and len(positions) > 0

def execute_mt5_trade(symbol, direction, entry, sl, tp1, strategy):
    if not AUTO_TRADE:
        return None
        
    if has_open_position(symbol):
        print(f"⏸️ כבר קיימת עסקה פתוחה על {symbol} - מדלג על ביצוע כפול.")
        return None

    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        print(f"⚠️ הנכס {symbol} לא נמצא בברוקר")
        return None
        
    if not symbol_info.visible:
        if not mt5.symbol_select(symbol, True):
            return None

    # התאמה דינמית של הלוט המינימלי לפי דרישות הברוקר עבור כל נכס
    min_volume = symbol_info.volume_min
    trade_volume = max(0.01, min_volume)

    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
    price = symbol_info.ask if direction == "BUY" else symbol_info.bid

    # ניסיון שליחה עם התאמת סוגי מילוי שונים (IOC / RETURN / FOK)
    filling_modes = [
        mt5.ORDER_FILLING_IOC,
        mt5.ORDER_FILLING_RETURN,
        mt5.ORDER_FILLING_FOK
    ]

    for filling_mode in filling_modes:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(trade_volume),
            "type": order_type,
            "price": price,
            "sl": float(sl),
            "tp": float(tp1),
            "deviation": 50,
            "magic": MAGIC_NUMBER,
            "comment": f"HOPE {strategy[:15]}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        result = mt5.order_send(request)
        if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"🎉 עסקה נפתחה בהצלחה ב-MT5! כרטיס: #{result.order} | {symbol} {direction} ({trade_volume} Lot) ב-{price} | SL: {sl} | TP: {tp1}")
            return result.order
            
    if result is not None:
        print(f"⚠️ פקודת מסחר נדחתה ב-MT5 ({symbol}): {result.comment} (קוד: {result.retcode})")
    return None

# ==============================================================================
# 📡 שידור ל-monday וטלגרם
# ==============================================================================
def send_telegram_alert(pair, direction, entry, sl, tp1, tp2, rr, strategy, session, quarter, trade_ticket):
    if not TELEGRAM_BOT_TOKEN:
        return
    emoji_dir = "🟢 BUY (לונג)" if direction == "BUY" else "🔴 SELL (שורט)"
    exec_status = f"✅ <b>בוצעה אוטומטית ב-MT5 (כרטיס: #{trade_ticket})</b>" if trade_ticket else "⚠️ איתות סריקה בלבד"
    
    msg = f"""⚡ <b>איתות מסחר וביצוע מוסדי בלייב</b> ⚡
{exec_status}

📊 <b>נכס:</b> <code>{pair}</code>
🎯 <b>כיוון:</b> {emoji_dir}
📌 <b>אסטרטגיה:</b> {strategy}
🕒 <b>סשן / רבע:</b> {session} | {quarter}

💵 <b>כניסה:</b> <code>{entry}</code>
🛑 <b>סטופ לוס (SL):</b> <code>{sl}</code>
🎯 <b>יעד 1 (TP1):</b> <code>{tp1}</code>
🎯 <b>יעד 2 (TP2):</b> <code>{tp2}</code>
⚖️ <b>יחס סיכון/סיכוי (R:R):</b> <code>1:{rr}</code>

🔗 <a href="https://motibotbika55s-team.monday.com/boards/{BOARD_ID}">צפה באיתות בלוח monday.com</a>"""
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"⚠️ שגיאה בטלגרם: {e}")

def send_signal_to_monday(pair, direction, entry, sl, tp1, tp2, rr, strategy, session, notes, trade_ticket):
    url = "https://api.monday.com/v2"
    headers = {
        "Authorization": MONDAY_API_KEY,
        "Content-Type": "application/json"
    }
    
    display_pair = pair
    if pair == "EURUSD": display_pair = "EUR/USD"
    elif pair == "GBPUSD": display_pair = "GBP/USD"
    elif pair == "USDJPY": display_pair = "USD/JPY"
    elif pair == "XAUUSD": display_pair = "XAU/USD"
    elif pair == "BTCUSD": display_pair = "BTC/USD"
    
    status_label = "פעיל" if trade_ticket else "חדש"
    ticket_note = f" [כרטיס MT5: #{trade_ticket}]" if trade_ticket else ""
    
    col_values = {
        "color_mm755n16": {"label": status_label},
        "color_mm75phj7": {"label": direction},
        "color_mm756vge": {"label": "SMC + ICT + תורת הרבעים"},
        "dropdown_mm75qvpy": {"labels": [display_pair]},
        "numeric_mm75vzjc": float(entry),
        "numeric_mm75xvzz": float(sl),
        "numeric_mm75z0r7": float(tp1),
        "numeric_mm75ar0d": float(tp2),
        "numeric_mm757s55": float(rr),
        "color_mm758g1m": {"label": session},
        "text_mm75vc2k": f"{notes}{ticket_note}",
        "date_mm754kz2": {"date": datetime.datetime.now().strftime("%Y-%m-%d"), "time": datetime.datetime.now().strftime("%H:%M:%S")}
    }
    
    item_name = f"{display_pair} - {direction} ({strategy})"
    
    query = """
    mutation ($boardId: ID!, $groupId: String!, $itemName: String!, $columnValues: JSON!) {
      create_item (
        board_id: $boardId,
        group_id: $groupId,
        item_name: $itemName,
        column_values: $columnValues
      ) {
        id
      }
    }
    """
    variables = {
        "boardId": BOARD_ID,
        "groupId": "group_mm7510j1",
        "itemName": item_name,
        "columnValues": json.dumps(col_values, ensure_ascii=False)
    }
    try:
        response = requests.post(url, json={"query": query, "variables": variables}, headers=headers, timeout=10)
        res_data = response.json()
        if "data" in res_data and res_data["data"]["create_item"]:
            print(f"✅ איתות שוגר ל-monday.com! מזהה: {res_data['data']['create_item']['id']}")
        else:
            print(f"❌ שגיאה ב-monday: {response.text}")
    except Exception as e:
        print(f"❌ שגיאת חיבור ל-monday: {e}")

# ==============================================================================
# 🕒 סשנים ותורת הרבעים
# ==============================================================================
def get_current_quarter_and_session():
    now = datetime.datetime.now(datetime.timezone.utc)
    hour = now.hour
    
    if 7 <= hour < 12:
        session = "London Killzone"
    elif 12 <= hour < 17:
        session = "New York Killzone"
    elif 17 <= hour < 21:
        session = "Overlap"
    else:
        session = "Asian Session"
        
    minute_of_day = hour * 60 + now.minute
    q_num = ((minute_of_day // 360) % 4) + 1
    
    q_dict = {
        1: "Q1 - Accumulation (איסוף)",
        2: "Q2 - Manipulation (מניפולציה)",
        3: "Q3 - Distribution (הפצה מגמתית)",
        4: "Q4 - Reversal / Continuation (היפוך/המשכיות)"
    }
    return q_dict.get(q_num, "Q1"), session

# ==============================================================================
# 🧠 אלגוריתם הניתוח המוסדי
# ==============================================================================
def analyze_symbol(symbol):
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 30)
    if rates is None or len(rates) < 20:
        return None
        
    c = rates[-1]
    p1 = rates[-2]
    p3 = rates[-4]
    
    decimals = 3 if "JPY" in symbol else (2 if symbol in ["XAUUSD", "US30", "NAS100", "BTCUSD"] else 5)
    
    lowest_prev_low = min([r['low'] for r in rates[-15:-2]])
    if p1['low'] < lowest_prev_low and c['close'] > lowest_prev_low:
        entry = round(c['close'], decimals)
        sl = round(p1['low'] - (0.0004 if decimals == 5 else (15.0 if "US30" in symbol else 0.4)), decimals)
        risk = abs(entry - sl)
        if risk > 0:
            tp1 = round(entry + (risk * 2.0), decimals)
            tp2 = round(entry + (risk * 3.5), decimals)
            return {
                "direction": "BUY",
                "strategy": "Wyckoff Spring (Phase C)",
                "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "rr": 2.0,
                "notes": f"איסוף נזילות Wyckoff Spring מתחת ל-{lowest_prev_low} + חזרה מעל הטווח"
            }

    highest_prev_high = max([r['high'] for r in rates[-15:-2]])
    if p1['high'] > highest_prev_high and c['close'] < highest_prev_high:
        entry = round(c['close'], decimals)
        sl = round(p1['high'] + (0.0004 if decimals == 5 else (15.0 if "US30" in symbol else 0.4)), decimals)
        risk = abs(sl - entry)
        if risk > 0:
            tp1 = round(entry - (risk * 2.0), decimals)
            tp2 = round(entry - (risk * 3.5), decimals)
            return {
                "direction": "SELL",
                "strategy": "Wyckoff UTAD (Phase C)",
                "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "rr": 2.0,
                "notes": f"פריצת שווא Wyckoff UTAD מעל {highest_prev_high} + דחייה למטה"
            }

    if p1['low'] > p3['high'] and c['close'] > p1['open']:
        entry = round(c['close'], decimals)
        sl = round(p3['high'], decimals)
        risk = abs(entry - sl)
        if risk > 0 and (risk / entry) < 0.01:
            tp1 = round(entry + (risk * 2.0), decimals)
            tp2 = round(entry + (risk * 3.0), decimals)
            return {
                "direction": "BUY",
                "strategy": "Fair Value Gap (FVG)",
                "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "rr": 2.0,
                "notes": f"אישור פריצת FVG שורית בנר M5"
            }

    return None

def scan_and_trade():
    quarter, session = get_current_quarter_and_session()
    now_str = datetime.datetime.now().strftime('%H:%M:%S')
    print(f"[{now_str}] 🔎 סורק ומבצע... שלב: {quarter} | סשן: {session}")
    
    for symbol in SYMBOLS:
        signal = analyze_symbol(symbol)
        if signal:
            print(f"🔥 איתות זוהה: {symbol} {signal['direction']} ({signal['strategy']})")
            trade_ticket = execute_mt5_trade(
                symbol, signal['direction'], signal['entry'], 
                signal['sl'], signal['tp1'], signal['strategy']
            )
            send_signal_to_monday(
                symbol, signal['direction'], signal['entry'], signal['sl'], 
                signal['tp1'], signal['tp2'], signal['rr'], signal['strategy'], 
                session, signal['notes'], trade_ticket
            )
            send_telegram_alert(
                symbol, signal['direction'], signal['entry'], signal['sl'], 
                signal['tp1'], signal['tp2'], signal['rr'], signal['strategy'], 
                session, quarter, trade_ticket
            )

def main():
    print(f"מתחבר ל-MT5 (חשבון {MT5_LOGIN})...")
    if not mt5.initialize():
        if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
            print("❌ חיבור ל-MT5 נכשל:", mt5.last_error())
            return
            
    if not mt5.login(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
        print("⚠️ נשאר מחובר לחשבון הקיים בטרמינל.")
        
    print(f"🟢 מחובר בהצלחה לחשבון {MT5_LOGIN}! מנוע המסחר האוטומטי בלייב פועל...")
    try:
        while True:
            scan_and_trade()
            time.sleep(60)
    except KeyboardInterrupt:
        print("עוצר סריקה ומסחר...")
    finally:
        mt5.shutdown()

if __name__ == "__main__":
    main()
