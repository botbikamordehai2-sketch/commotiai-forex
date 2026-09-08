//+------------------------------------------------------------------+
//| RSI_MA20_Bot.mq5 — Blueberry Funded                             |
//| אסטרטגיה: RSI(14) + MA20 על M15                                 |
//| LONG: RSI<30 | SHORT: RSI>70 | ריסק: 1% לעסקה                  |
//+------------------------------------------------------------------+
#property copyright "RSI Bot"
#property version   "1.00"
#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//--- פרמטרים
input string InpStrategyFolder = "s1_classic"; // Strategy folder (s1_classic / s2_aggressive / s3_momentum / s4_no_rsi_dir / s5_trend_follow)
input double InpRisk         = 1.0;    // ריסק לעסקה (%)
input int    InpRSIPeriod    = 14;     // RSI Period
input int    InpMAPeriod     = 20;     // MA Period
input int    InpMA50Period   = 50;     // MA50 Period (טרנד)
input int    InpSLPips       = 30;     // Stop Loss (pips)
input double InpMaxDailyLoss = 3.8;   // מקסימום הפסד יומי (%) — Blueberry limit 4%
input double InpMaxDrawdown  = 9.0;   // מקסימום drawdown (%) — Blueberry static
input double InpMinMarginPct = 150.0; // מינימום Margin Level (%) — Blueberry rule
input int    InpMagic        = 202600; // Magic Number
input int    InpSessionStart = 0;      // סשן התחלה (UTC)
input int    InpSessionEnd   = 24;     // סשן סיום (UTC)

CTrade        trade;
CPositionInfo pos;

double g_InitialBalance  = 0;
double g_DailyBalance    = 0;
datetime g_LastDay       = 0;

//+------------------------------------------------------------------+
int OnInit()
{
    trade.SetExpertMagicNumber(InpMagic);
    trade.SetDeviationInPoints(20);
    trade.SetTypeFilling(ORDER_FILLING_IOC);

    g_InitialBalance = AccountInfoDouble(ACCOUNT_BALANCE);
    g_DailyBalance   = g_InitialBalance;
    g_LastDay        = TimeCurrent();

    EventSetTimer(5);  // בדיקת bridge כל 5 שניות

    Print("=== RSI+MA20 Bot מופעל ===");
    Print("בלנס: ", g_InitialBalance, " | ריסק: ", InpRisk, "% | FTMO guard: ", InpMaxDailyLoss, "%/", InpMaxDrawdown, "%");
    return INIT_SUCCEEDED;
}

void OnTimer()
{
    static int tick = 0;
    tick++;
    if(tick % 6 == 1) Print("[TIMER] alive #", tick, " | trade_allowed=", (bool)TerminalInfoInteger(TERMINAL_TRADE_ALLOWED));
    if(!FTMOGuard()) return;
    CheckBridgeSignal(_Symbol);
}

void OnDeinit(const int reason)
{
    EventKillTimer();
}

//+------------------------------------------------------------------+
//| בדיקת חוקי FTMO                                                  |
//+------------------------------------------------------------------+
bool FTMOGuard()
{
    double balance = AccountInfoDouble(ACCOUNT_BALANCE);
    double equity  = AccountInfoDouble(ACCOUNT_EQUITY);

    // איפוס יומי
    MqlDateTime now, last;
    TimeToStruct(TimeCurrent(), now);
    TimeToStruct(g_LastDay, last);
    if(now.day != last.day)
    {
        g_DailyBalance = balance;
        g_LastDay      = TimeCurrent();
        Print("יום חדש — בלנס יומי מאופס: ", g_DailyBalance);
    }

    // הפסד יומי
    double dailyLoss = (g_DailyBalance - equity) / g_InitialBalance * 100.0;
    if(dailyLoss >= InpMaxDailyLoss)
    {
        Print("FTMO STOP: הפסד יומי ", DoubleToString(dailyLoss,2), "% — לא סוחרים היום!");
        return false;
    }

    // מקסימום drawdown
    double dd = (g_InitialBalance - equity) / g_InitialBalance * 100.0;
    if(dd >= InpMaxDrawdown)
    {
        Print("BLUEBERRY STOP: Drawdown ", DoubleToString(dd,2), "% — עוצר הבוט!");
        return false;
    }

    // בדיקת Margin Level — Blueberry דורשים > 150%
    double marginLevel = AccountInfoDouble(ACCOUNT_MARGIN_LEVEL);
    if(marginLevel > 0 && marginLevel < InpMinMarginPct)
    {
        Print("BLUEBERRY STOP: Margin Level ", DoubleToString(marginLevel,1), "% — מתחת ל-", InpMinMarginPct, "%!");
        return false;
    }

    return true;
}

//+------------------------------------------------------------------+
//| חישוב lot size לפי % ריסק                                        |
//+------------------------------------------------------------------+
double CalcLot(string sym, int slPips)
{
    double balance    = AccountInfoDouble(ACCOUNT_BALANCE);
    double riskMoney  = balance * InpRisk / 100.0;
    double point      = SymbolInfoDouble(sym, SYMBOL_POINT);
    double tickVal    = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
    double tickSz     = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
    int    digits     = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);

    double slDist = slPips * point * (digits == 3 || digits == 5 ? 10 : 1);
    if(tickSz == 0 || tickVal == 0) return SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);

    double lot = riskMoney / (slDist / tickSz * tickVal);

    double minL = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
    double maxL = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
    double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
    lot = MathRound(lot / step) * step;
    return MathMax(minL, MathMin(maxL, lot));
}

//+------------------------------------------------------------------+
//| בדיקה אם יש פוזיציה פתוחה                                        |
//+------------------------------------------------------------------+
bool HasPosition(string sym)
{
    for(int i = PositionsTotal()-1; i >= 0; i--)
        if(pos.SelectByIndex(i) && pos.Symbol() == sym && pos.Magic() == InpMagic)
            return true;
    return false;
}

//+------------------------------------------------------------------+
//| לוגיקת כניסה                                                     |
//+------------------------------------------------------------------+
void CheckSignal(string sym)
{
    if(HasPosition(sym)) return;

    // פילטר סשן — רק לונדון + NY (UTC)
    MqlDateTime t;
    TimeToStruct(TimeGMT(), t);
    if(t.hour < InpSessionStart || t.hour >= InpSessionEnd) return;

    int hRSI = iRSI(sym, PERIOD_M15, InpRSIPeriod, PRICE_CLOSE);
    int hMA  = iMA (sym, PERIOD_M15, InpMAPeriod,  0, MODE_SMA, PRICE_CLOSE);
    int hMA50= iMA (sym, PERIOD_M15, InpMA50Period, 0, MODE_SMA, PRICE_CLOSE);
    if(hRSI == INVALID_HANDLE || hMA == INVALID_HANDLE || hMA50 == INVALID_HANDLE) return;

    double rsi[], ma[], ma50[];
    ArraySetAsSeries(rsi,  true);
    ArraySetAsSeries(ma,   true);
    ArraySetAsSeries(ma50, true);
    if(CopyBuffer(hRSI, 0, 0, 3, rsi)  < 3) { IndicatorRelease(hRSI); IndicatorRelease(hMA); IndicatorRelease(hMA50); return; }
    if(CopyBuffer(hMA,  0, 0, 3, ma)   < 3) { IndicatorRelease(hRSI); IndicatorRelease(hMA); IndicatorRelease(hMA50); return; }
    if(CopyBuffer(hMA50,0, 0, 3, ma50) < 3) { IndicatorRelease(hRSI); IndicatorRelease(hMA); IndicatorRelease(hMA50); return; }

    int    digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
    double point  = SymbolInfoDouble(sym, SYMBOL_POINT);
    double mult   = (digits == 3 || digits == 5) ? 10.0 : 1.0;
    double slDist = InpSLPips * point * mult;
    double tpDist = slDist * 2.0;
    double lot    = CalcLot(sym, InpSLPips);

    double rsiVal = rsi[1];
    double maVal  = ma[1];
    double ma50Val= ma50[1];
    double price  = SymbolInfoDouble(sym, SYMBOL_BID);

    // פילטר טרנד MA50 — RSI קיצוני (<25 או >75) עוקף את הפילטר
    bool trendUp   = price > ma50Val;
    bool trendDown = price < ma50Val;
    bool extremeLong  = rsiVal < 25;
    bool extremeShort = rsiVal > 75;

    bool isLong  = (extremeLong) ||
                   (trendUp   && ((rsiVal < 30) || (rsiVal >= 48 && rsiVal <= 65 && price > maVal)));
    bool isShort = (extremeShort) ||
                   (trendDown && ((rsiVal > 70) || (rsiVal >= 35 && rsiVal <= 52 && price < maVal)));

    // ── LONG ─────────────────────────────────────────────
    if(isLong)
    {
        double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
        double sl  = NormalizeDouble(ask - slDist, digits);
        double tp  = NormalizeDouble(ask + tpDist, digits);
        if(trade.Buy(lot, sym, ask, sl, tp, "RSI-Bot LONG"))
            Print("LONG  ", sym, " | RSI:", DoubleToString(rsiVal,1), " | MA:", DoubleToString(maVal,digits), " | lot:", lot, " | SL:", sl, " | TP:", tp);
        else
            Print("FAIL LONG  ", sym, " | error:", trade.ResultRetcode(), " - ", trade.ResultRetcodeDescription());
    }
    // ── SHORT ────────────────────────────────────────────
    else if(isShort)
    {
        double bid = SymbolInfoDouble(sym, SYMBOL_BID);
        double sl  = NormalizeDouble(bid + slDist, digits);
        double tp  = NormalizeDouble(bid - tpDist, digits);
        if(trade.Sell(lot, sym, bid, sl, tp, "RSI-Bot SHORT"))
            Print("SHORT ", sym, " | RSI:", DoubleToString(rsiVal,1), " | MA:", DoubleToString(maVal,digits), " | lot:", lot, " | SL:", sl, " | TP:", tp);
        else
            Print("FAIL SHORT ", sym, " | error:", trade.ResultRetcode(), " - ", trade.ResultRetcodeDescription());
    }

    IndicatorRelease(hRSI);
    IndicatorRelease(hMA);
    IndicatorRelease(hMA50);
}

//+------------------------------------------------------------------+
//| קריאת איתות מ-Python bridge                                      |
//+------------------------------------------------------------------+
void CheckBridgeSignal(string sym)
{
    if(HasPosition(sym)) return;

    string filename = InpStrategyFolder + "\\signal_" + sym + ".txt";
    int handle = FileOpen(filename, FILE_READ|FILE_COMMON|FILE_TXT|FILE_ANSI);
    if(handle == INVALID_HANDLE) return;

    string content = FileReadString(handle);
    FileClose(handle);
    FileDelete(filename, FILE_COMMON);

    string parts[];
    int count = StringSplit(content, ',', parts);
    if(count < 2) return;

    string direction = parts[0];
    long   sigTime   = StringToInteger(parts[1]);
    long   now       = (long)TimeGMT();  // UTC תמיד — כמו Python time.time()

    if(now - sigTime > 900) { Print("[BRIDGE] איתות ישן — מתעלם | now=",now," sig=",sigTime," diff=",now-sigTime); return; }

    int    digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
    double point  = SymbolInfoDouble(sym, SYMBOL_POINT);
    double mult   = (digits == 3 || digits == 5) ? 10.0 : 1.0;
    double slDist = InpSLPips * point * mult;
    double tpDist = slDist * 2.0;
    double lot    = CalcLot(sym, InpSLPips);

    if(direction == "LONG")
    {
        double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
        double sl  = NormalizeDouble(ask - slDist, digits);
        double tp  = NormalizeDouble(ask + tpDist, digits);
        if(trade.Buy(lot, sym, ask, sl, tp, "Bridge LONG"))
            Print("[BRIDGE] LONG  ", sym, " | lot:", lot, " | SL:", sl, " | TP:", tp);
        else
            Print("[BRIDGE] FAIL LONG ", sym, " | error:", trade.ResultRetcode());
    }
    else if(direction == "SHORT")
    {
        double bid = SymbolInfoDouble(sym, SYMBOL_BID);
        double sl  = NormalizeDouble(bid + slDist, digits);
        double tp  = NormalizeDouble(bid - tpDist, digits);
        if(trade.Sell(lot, sym, bid, sl, tp, "Bridge SHORT"))
            Print("[BRIDGE] SHORT ", sym, " | lot:", lot, " | SL:", sl, " | TP:", tp);
        else
            Print("[BRIDGE] FAIL SHORT ", sym, " | error:", trade.ResultRetcode());
    }
}

//+------------------------------------------------------------------+
//| OnTick — רץ על כל תנועת מחיר, מבדיק נר חדש בלבד                |
//+------------------------------------------------------------------+
void OnTick()
{
    static datetime lastBar = 0;
    datetime curBar = iTime(_Symbol, PERIOD_M15, 0);

    CheckBridgeSignal(_Symbol);

    if(curBar == lastBar) return;
    lastBar = curBar;

    if(!FTMOGuard()) return;
    CheckSignal(_Symbol);
}
//+------------------------------------------------------------------+
