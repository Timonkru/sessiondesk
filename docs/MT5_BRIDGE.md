# MetaTrader 5 bridge

`bridge/SessionDeskBridge.mq5` is a small read-only Expert Advisor. It writes what SessionDesk
shows into the terminal's common data folder (`%APPDATA%\MetaQuotes\Terminal\Common\Files\SessionDesk`).
It contains no trade functions, no DLL imports, no WebRequest and no notifications.

## Install

1. In MetaTrader 5: File → Open Data Folder → `MQL5\Experts`, copy `SessionDeskBridge.mq5` there.
2. Open it in MetaEditor and compile (F7).
3. Attach `SessionDeskBridge` to **one** chart per terminal.
4. SessionDesk → Accounts & EAs shows the data within seconds, and the calendar starts showing actual values.

If your common folder differs (Wine, portable install), set it in Settings → Connectors → MetaTrader 5.

## Files

TSV, first line `#sessiondesk  version  kind  utc_epoch  server_offset  login`.

| File | Content | Refresh |
|---|---|---|
| `account_<login>.tsv` | balance, equity, margin, AutoTrading state | 2 s |
| `positions_<login>.tsv` | open positions, money at risk to the stop, magic number | 2 s |
| `quotes_<login>.tsv` | Market Watch bid/ask and previous daily close | 2 s |
| `eas_<login>.tsv` | which Expert Advisor runs on which chart | 60 s |
| `deals_<login>.tsv` | closed deals of the last 30 days | 60 s |
| `calendar.tsv` | MetaQuotes calendar incl. actual values, 12 h back to 7 days ahead | on change (checked every 2 s) and every 60 s |

Times are converted from trade-server time to UTC (offset rounded to 15 minutes). Files older than
their freshness limit are shown as stale, never as current. Account numbers are masked in the UI by
default (Settings → Privacy).

Status: compiles with 0 errors and 0 warnings (MetaEditor build of 13 Oct 2026); not yet
observed on a live chart.
