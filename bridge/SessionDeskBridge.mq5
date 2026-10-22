//+------------------------------------------------------------------+
//| SessionDeskBridge.mq5                                            |
//| Read-only exporter: account, positions, running EAs, quotes,     |
//| closed deals, cash bookings (tax, deposits, fees), the economic |
//| calendar (with actual values) for                                |
//| SessionDesk. Attach ONCE per terminal to any chart.              |
//|                                                                  |
//| This program never sends, modifies or closes an order. It uses   |
//| no DLLs, no WebRequest and no notifications. It only writes TSV  |
//| files to the common data folder:                                 |
//|   <Common>\Files\SessionDesk\                                    |
//| License: MIT                                                     |
//+------------------------------------------------------------------+
#property strict
#property version     "1.20"
#property description "Read-only data bridge for SessionDesk (account, positions, EAs, quotes, specs, deals, calendar + history)."

input int  InpFastSeconds      = 2;     // positions / account / calendar-change check (seconds)
input int  InpSlowSeconds      = 60;    // full calendar, deals, running EAs (seconds)
input int  InpDealDays         = 100;   // deal history to export (days) - a monthly report needs the whole last month
input int  InpMaxQuotes        = 200;   // max Market Watch symbols exported
input bool InpExportCalendar   = true;  // only one terminal needs this; harmless if several do

#define BRIDGE_VERSION "1.20"
string   g_folder = "SessionDesk\\";
ulong    g_calendar_change = 0;
datetime g_last_slow = 0;

//--- trade-server minus UTC, rounded to 15 minutes (server clocks are not exact)
long ServerOffset()
{
   long diff = (long)(TimeTradeServer() - TimeGMT());
   return (long)MathRound(diff / 900.0) * 900;
}

string Clean(string value)
{
   StringReplace(value, "\t", " ");
   StringReplace(value, "\r", " ");
   StringReplace(value, "\n", " ");
   return value;
}

string Header(string kind)
{
   return "#sessiondesk\t" + BRIDGE_VERSION + "\t" + kind + "\t" + IntegerToString((long)TimeGMT())
        + "\t" + IntegerToString(ServerOffset()) + "\t" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + "\n";
}

//--- write to a temp file, then move over the target: readers never see half a file
bool Publish(string name, string body)
{
   string tmp = g_folder + name + "." + IntegerToString(ChartID()) + ".tmp";
   int h = FileOpen(tmp, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON, 0, CP_UTF8);
   if(h == INVALID_HANDLE) { Print("SessionDesk: cannot open ", tmp, " error ", GetLastError()); return false; }
   FileWriteString(h, body);
   FileClose(h);
   if(!FileMove(tmp, FILE_COMMON, g_folder + name, FILE_COMMON | FILE_REWRITE))
   {
      Print("SessionDesk: cannot publish ", name, " error ", GetLastError());
      FileDelete(tmp, FILE_COMMON);
      return false;
   }
   return true;
}

string D(double v, int digits) { return DoubleToString(v, digits); }

//--- money lost if price moves from open to stop (0 if no stop or stop in profit)
double RiskToStop(string symbol, long type, double volume, double open, double sl)
{
   if(sl <= 0) return 0;
   double pnl = 0;
   ENUM_ORDER_TYPE ot = (type == POSITION_TYPE_BUY) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   if(!OrderCalcProfit(ot, symbol, volume, open, sl, pnl)) return 0;
   return pnl < 0 ? -pnl : 0;
}

void ExportAccount()
{
   long login = AccountInfoInteger(ACCOUNT_LOGIN);
   bool trade_allowed = (bool)TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) && (bool)AccountInfoInteger(ACCOUNT_TRADE_ALLOWED);
   string body = Header("account");
   body += "login\tserver\tcompany\tcurrency\tbalance\tequity\tmargin\tfree_margin\tprofit\tleverage\ttrade_allowed\tconnected\n";
   body += IntegerToString(login) + "\t" + Clean(AccountInfoString(ACCOUNT_SERVER)) + "\t" + Clean(AccountInfoString(ACCOUNT_COMPANY))
         + "\t" + AccountInfoString(ACCOUNT_CURRENCY) + "\t" + D(AccountInfoDouble(ACCOUNT_BALANCE), 2)
         + "\t" + D(AccountInfoDouble(ACCOUNT_EQUITY), 2) + "\t" + D(AccountInfoDouble(ACCOUNT_MARGIN), 2)
         + "\t" + D(AccountInfoDouble(ACCOUNT_MARGIN_FREE), 2) + "\t" + D(AccountInfoDouble(ACCOUNT_PROFIT), 2)
         + "\t" + IntegerToString(AccountInfoInteger(ACCOUNT_LEVERAGE)) + "\t" + (trade_allowed ? "1" : "0")
         + "\t" + (TerminalInfoInteger(TERMINAL_CONNECTED) ? "1" : "0") + "\n";
   Publish("account_" + IntegerToString(login) + ".tsv", body);
}

void ExportPositions()
{
   long login = AccountInfoInteger(ACCOUNT_LOGIN);
   long offset = ServerOffset();
   string body = Header("positions");
   body += "ticket\tsymbol\tside\tvolume\topen_price\topen_time_utc\tsl\ttp\tprice\tprofit\tswap\tmagic\tcomment\trisk_to_stop\tdigits\tmoney_per_pct\n";
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket)) continue;
      string sym = PositionGetString(POSITION_SYMBOL);
      long type = PositionGetInteger(POSITION_TYPE);
      double vol = PositionGetDouble(POSITION_VOLUME);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl = PositionGetDouble(POSITION_SL);
      int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      body += IntegerToString((long)ticket) + "\t" + sym + "\t" + (type == POSITION_TYPE_BUY ? "LONG" : "SHORT")
            + "\t" + D(vol, 2) + "\t" + D(open, digits)
            + "\t" + IntegerToString((long)PositionGetInteger(POSITION_TIME) - offset)
            + "\t" + D(sl, digits) + "\t" + D(PositionGetDouble(POSITION_TP), digits)
            + "\t" + D(PositionGetDouble(POSITION_PRICE_CURRENT), digits)
            + "\t" + D(PositionGetDouble(POSITION_PROFIT), 2) + "\t" + D(PositionGetDouble(POSITION_SWAP), 2)
            + "\t" + IntegerToString(PositionGetInteger(POSITION_MAGIC)) + "\t" + Clean(PositionGetString(POSITION_COMMENT))
            + "\t" + D(RiskToStop(sym, type, vol, open, sl), 2) + "\t" + IntegerToString(digits)
            + "\t" + D(MoneyPerPercent(sym, vol, PositionGetDouble(POSITION_PRICE_CURRENT)), 2) + "\n";
   }
   Publish("positions_" + IntegerToString(login) + ".tsv", body);
}

//--- account-currency P/L of a 1 % move in the symbol for the given volume (sensitivity for scenarios)
double MoneyPerPercent(string symbol, double volume, double price)
{
   if(price <= 0) return 0;
   double pnl = 0;
   if(!OrderCalcProfit(ORDER_TYPE_BUY, symbol, volume, price, price * 1.01, pnl)) return 0;
   return MathAbs(pnl);
}

void ExportSpecs()
{
   long login = AccountInfoInteger(ACCOUNT_LOGIN);
   string body = Header("specs");
   body += "symbol\tspread_points\tpoint\tdigits\tmoney_per_unit\tcontract_size\tvolume_min\tvolume_step\tswap_long\tswap_short\tswap_mode\ttriple_day\tcurrency_profit\n";
   int n = SymbolsTotal(true);
   for(int i = 0; i < n && i < InpMaxQuotes; i++)
   {
      string sym = SymbolName(i, true);
      double tick_value = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
      double tick_size = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
      double per_unit = tick_size > 0 ? tick_value / tick_size : 0;     // account money per 1.0 price move per lot
      body += sym + "\t" + IntegerToString(SymbolInfoInteger(sym, SYMBOL_SPREAD))
            + "\t" + DoubleToString(SymbolInfoDouble(sym, SYMBOL_POINT), 10) + "\t" + IntegerToString(SymbolInfoInteger(sym, SYMBOL_DIGITS))
            + "\t" + D(per_unit, 6) + "\t" + D(SymbolInfoDouble(sym, SYMBOL_TRADE_CONTRACT_SIZE), 2)
            + "\t" + D(SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN), 2) + "\t" + D(SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP), 2)
            + "\t" + D(SymbolInfoDouble(sym, SYMBOL_SWAP_LONG), 4) + "\t" + D(SymbolInfoDouble(sym, SYMBOL_SWAP_SHORT), 4)
            + "\t" + IntegerToString(SymbolInfoInteger(sym, SYMBOL_SWAP_MODE)) + "\t" + IntegerToString(SymbolInfoInteger(sym, SYMBOL_SWAP_ROLLOVER3DAYS))
            + "\t" + SymbolInfoString(sym, SYMBOL_CURRENCY_PROFIT) + "\n";
   }
   Publish("specs_" + IntegerToString(login) + ".tsv", body);
}

void ExportEAs()
{
   long login = AccountInfoInteger(ACCOUNT_LOGIN);
   string body = Header("eas");
   body += "chart_id\tsymbol\ttimeframe\texpert\n";
   long chart = ChartFirst();
   int guard = 0;
   while(chart >= 0 && guard < 200)
   {
      string expert = ChartGetString(chart, CHART_EXPERT_NAME);
      if(expert != "")
         body += IntegerToString(chart) + "\t" + ChartSymbol(chart) + "\t"
               + StringSubstr(EnumToString(ChartPeriod(chart)), 7) + "\t" + Clean(expert) + "\n";
      chart = ChartNext(chart);
      guard++;
   }
   Publish("eas_" + IntegerToString(login) + ".tsv", body);
}

void ExportQuotes()
{
   long login = AccountInfoInteger(ACCOUNT_LOGIN);
   long offset = ServerOffset();
   string body = Header("quotes");
   body += "symbol\tbid\task\ttime_utc\tprev_close\tday_open\tdigits\n";
   int n = SymbolsTotal(true);
   for(int i = 0; i < n && i < InpMaxQuotes; i++)
   {
      string sym = SymbolName(i, true);
      MqlTick tick;
      if(!SymbolInfoTick(sym, tick)) continue;
      int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      double prev = iClose(sym, PERIOD_D1, 1);
      double open = iOpen(sym, PERIOD_D1, 0);
      body += sym + "\t" + D(tick.bid, digits) + "\t" + D(tick.ask, digits) + "\t" + IntegerToString((long)tick.time - offset)
            + "\t" + D(prev, digits) + "\t" + D(open, digits) + "\t" + IntegerToString(digits) + "\n";
   }
   Publish("quotes_" + IntegerToString(login) + ".tsv", body);
}

//--- deal type -> exported name; "" = skip. Besides BUY/SELL the cash bookings a statement shows: deposits and
//--- withdrawals (BALANCE), credit, charges, corrections, bonus, commissions billed apart, interest, dividends, tax.
string DealKind(long type)
{
   switch((int)type)
   {
      case DEAL_TYPE_BUY:                      return "BUY";
      case DEAL_TYPE_SELL:                     return "SELL";
      case DEAL_TYPE_BALANCE:                  return "BALANCE";
      case DEAL_TYPE_CREDIT:                   return "CREDIT";
      case DEAL_TYPE_CHARGE:                   return "CHARGE";
      case DEAL_TYPE_CORRECTION:               return "CORRECTION";
      case DEAL_TYPE_BONUS:                    return "BONUS";
      case DEAL_TYPE_COMMISSION:
      case DEAL_TYPE_COMMISSION_DAILY:
      case DEAL_TYPE_COMMISSION_MONTHLY:
      case DEAL_TYPE_COMMISSION_AGENT_DAILY:
      case DEAL_TYPE_COMMISSION_AGENT_MONTHLY: return "COMMISSION";
      case DEAL_TYPE_INTEREST:                 return "INTEREST";
      case DEAL_DIVIDEND:
      case DEAL_DIVIDEND_FRANKED:              return "DIVIDEND";
      case DEAL_TAX:                           return "TAX";
   }
   return "";
}

void ExportDeals()
{
   long login = AccountInfoInteger(ACCOUNT_LOGIN);
   long offset = ServerOffset();
   datetime to = TimeTradeServer() + 3600;
   datetime from = to - InpDealDays * 86400;
   if(!HistorySelect(from, to)) return;
   string body = Header("deals");
   body += "ticket\ttime_utc\tsymbol\ttype\tentry\tvolume\tprice\tprofit\tcommission\tswap\tmagic\tposition_id\tcomment\tfee\n";
   int n = HistoryDealsTotal();
   for(int i = 0; i < n; i++)
   {
      ulong t = HistoryDealGetTicket(i);
      if(t == 0) continue;
      long type = HistoryDealGetInteger(t, DEAL_TYPE);
      string kind = DealKind(type);                    // trades and the cash bookings (tax, deposits, fees, dividends)
      if(kind == "") continue;
      string sym = HistoryDealGetString(t, DEAL_SYMBOL);
      int digits = sym == "" ? 2 : (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      body += IntegerToString((long)t) + "\t" + IntegerToString((long)HistoryDealGetInteger(t, DEAL_TIME) - offset)
            + "\t" + sym + "\t" + kind
            + "\t" + IntegerToString(HistoryDealGetInteger(t, DEAL_ENTRY))
            + "\t" + D(HistoryDealGetDouble(t, DEAL_VOLUME), 2) + "\t" + D(HistoryDealGetDouble(t, DEAL_PRICE), digits)
            + "\t" + D(HistoryDealGetDouble(t, DEAL_PROFIT), 2) + "\t" + D(HistoryDealGetDouble(t, DEAL_COMMISSION), 2)
            + "\t" + D(HistoryDealGetDouble(t, DEAL_SWAP), 2) + "\t" + IntegerToString(HistoryDealGetInteger(t, DEAL_MAGIC))
            + "\t" + IntegerToString(HistoryDealGetInteger(t, DEAL_POSITION_ID))
            + "\t" + Clean(HistoryDealGetString(t, DEAL_COMMENT))
            + "\t" + D(HistoryDealGetDouble(t, DEAL_FEE), 2) + "\n";
   }
   Publish("deals_" + IntegerToString(login) + ".tsv", body);
}

string CalValue(long raw, int digits)
{
   if(raw == LONG_MIN) return "";
   return DoubleToString((double)raw / 1000000.0, MathMin(digits, 6));
}

string Unit(MqlCalendarEvent &ev, MqlCalendarCountry &c)
{
   string scale = "";
   if(ev.multiplier == CALENDAR_MULTIPLIER_THOUSANDS) scale = "K";
   if(ev.multiplier == CALENDAR_MULTIPLIER_MILLIONS)  scale = "M";
   if(ev.multiplier == CALENDAR_MULTIPLIER_BILLIONS)  scale = "B";
   if(ev.multiplier == CALENDAR_MULTIPLIER_TRILLIONS) scale = "T";
   if(ev.unit == CALENDAR_UNIT_PERCENT)  return scale + "%";
   if(ev.unit == CALENDAR_UNIT_CURRENCY) return scale + " " + c.currency;
   if(ev.unit == CALENDAR_UNIT_USD)      return scale + " USD";
   return scale;
}

//--- calendar window: 12 h back, 7 days ahead. Times are trade-server time -> converted to UTC.
void ExportCalendar()
{
   if(!InpExportCalendar) return;
   long offset = ServerOffset();
   datetime now = TimeTradeServer();
   MqlCalendarValue values[];
   if(CalendarValueHistory(values, now - 12 * 3600, now + 7 * 86400) <= 0) return;
   string body = Header("calendar");
   body += "value_id\tevent_id\ttime_utc\tcurrency\tcountry\tname\timportance\tactual\tforecast\tprevious\trevised_previous\tunit\timpact\n";
   for(int i = 0; i < ArraySize(values); i++)
   {
      MqlCalendarEvent ev;
      MqlCalendarCountry c;
      if(!CalendarEventById(values[i].event_id, ev)) continue;
      if(!CalendarCountryById(ev.country_id, c)) continue;
      if(ev.importance == CALENDAR_IMPORTANCE_NONE) continue;
      int digits = (int)ev.digits;
      body += IntegerToString((long)values[i].id) + "\t" + IntegerToString((long)ev.id)
            + "\t" + IntegerToString((long)values[i].time - offset) + "\t" + c.currency + "\t" + c.code
            + "\t" + Clean(ev.name) + "\t" + IntegerToString((int)ev.importance)
            + "\t" + CalValue(values[i].actual_value, digits) + "\t" + CalValue(values[i].forecast_value, digits)
            + "\t" + CalValue(values[i].prev_value, digits) + "\t" + CalValue(values[i].revised_prev_value, digits)
            + "\t" + Unit(ev, c) + "\t" + IntegerToString((int)values[i].impact_type) + "\n";
   }
   Publish("calendar.tsv", body);
}

//--- last 10 releases of every medium/high event due in the next 36 h (for the reaction history)
void ExportCalendarHistory()
{
   if(!InpExportCalendar) return;
   long offset = ServerOffset();
   datetime now = TimeTradeServer();
   MqlCalendarValue upcoming[];
   if(CalendarValueHistory(upcoming, now, now + 36 * 3600) <= 0) return;
   string body = Header("calhist");
   body += "event_id\tcurrency\tname\ttime_utc\tactual\tforecast\tprevious\tunit\timportance\n";
   ulong done[];
   for(int i = 0; i < ArraySize(upcoming); i++)
   {
      MqlCalendarEvent ev;
      MqlCalendarCountry c;
      if(!CalendarEventById(upcoming[i].event_id, ev)) continue;
      if(ev.importance < CALENDAR_IMPORTANCE_MODERATE) continue;
      bool seen = false;
      for(int k = 0; k < ArraySize(done); k++) if(done[k] == ev.id) { seen = true; break; }
      if(seen) continue;
      int m = ArraySize(done);
      ArrayResize(done, m + 1);
      done[m] = ev.id;
      if(!CalendarCountryById(ev.country_id, c)) continue;
      MqlCalendarValue hist[];
      int got = CalendarValueHistoryByEvent(ev.id, hist, now - 3 * 365 * 86400, now);
      int digits = (int)ev.digits;
      for(int j = MathMax(0, got - 10); j < got; j++)
      {
         if(hist[j].actual_value == LONG_MIN) continue;
         body += IntegerToString((long)ev.id) + "\t" + c.currency + "\t" + Clean(ev.name)
               + "\t" + IntegerToString((long)hist[j].time - offset)
               + "\t" + CalValue(hist[j].actual_value, digits) + "\t" + CalValue(hist[j].forecast_value, digits)
               + "\t" + CalValue(hist[j].prev_value, digits) + "\t" + Unit(ev, c) + "\t" + IntegerToString((int)ev.importance) + "\n";
      }
   }
   Publish("calhist.tsv", body);
}

//--- cheap change probe: true when MetaQuotes published anything new (e.g. an actual value)
bool CalendarChanged()
{
   if(!InpExportCalendar) return false;
   MqlCalendarValue changed[];
   ulong id = g_calendar_change;
   int n = CalendarValueLast(id, changed);
   bool first = (g_calendar_change == 0);
   g_calendar_change = id;
   return (!first && n > 0);
}

int OnInit()
{
   FolderCreate("SessionDesk", FILE_COMMON);
   EventSetTimer(MathMax(1, InpFastSeconds));
   CalendarChanged();            // arm the change id
   ExportAccount(); ExportPositions(); ExportQuotes(); ExportEAs(); ExportDeals(); ExportCalendar();
   ExportSpecs(); ExportCalendarHistory();
   g_last_slow = TimeLocal();
   Print("SessionDesk bridge ", BRIDGE_VERSION, " started (read-only).");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) { EventKillTimer(); }

void OnTimer()
{
   ExportAccount();
   ExportPositions();
   ExportQuotes();
   if(CalendarChanged()) ExportCalendar();          // new actual value -> out within InpFastSeconds
   if(TimeLocal() - g_last_slow >= InpSlowSeconds)
   {
      ExportEAs();
      ExportDeals();
      ExportCalendar();
      ExportSpecs();
      ExportCalendarHistory();
      g_last_slow = TimeLocal();
   }
}
