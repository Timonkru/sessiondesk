// Command bar mnemonics, Bloomberg-style but in plain words: "AAPL OPT", "DAX MEMBERS", "ECO", "SAP.DE FA".
// parseCommand() is pure: it turns the typed text into { href, label } or null (then the normal search runs).

// instrument functions -> tab of the instrument page
export const FUNCTIONS = {
  DES: ["overview", "overview"], OV: ["overview", "overview"], GP: ["overview", "chart"], CHART: ["overview", "chart"],
  FA: ["financials", "financial statements"], FIN: ["financials", "financial statements"],
  EE: ["earnings", "earnings history"], ERN: ["earnings", "earnings history"],
  ANR: ["street", "estimates & analysts"], EST: ["street", "estimates & analysts"],
  RV: ["valuation", "valuation"], VAL: ["valuation", "valuation"], DCF: ["valuation", "valuation"],
  HDS: ["ownership", "ownership & short interest"], OWN: ["ownership", "ownership & short interest"],
  OMON: ["options", "options"], OPT: ["options", "options"], OVDV: ["options", "options"],
  PERF: ["performance", "performance & risk"], RISK: ["performance", "performance & risk"],
  COMP: ["peers", "peers"], PEERS: ["peers", "peers"],
  MGMT: ["people", "people & indices"], PEOPLE: ["people", "people & indices"],
  SPLC: ["network", "network"], NET: ["network", "network"],
  DVD: ["dividends", "dividends"], CN: ["news", "news"], NEWS: ["news", "news"], FIL: ["filings", "SEC filings"], SEC: ["filings", "SEC filings"],
};
// pages without a symbol (no word that is also a common ticker: MOV, MAC, CAL, RES ... stay stock searches)
export const PAGES = {
  TOP: ["#/news", "News"], NEWS: ["#/news", "News"], WEI: ["#/markets", "Markets overview"], MKT: ["#/markets", "Markets overview"],
  ECO: ["#/calendar", "Calendar"], FLOW: ["#/flows", "Forced flows"], IDX: ["#/indices", "Indices"],
  SECT: ["#/sectors", "Sectors"], EQS: ["#/stocks", "Stocks"], SCREEN: ["#/stocks", "Stocks"], MOST: ["#/watch", "Movers"],
  BSKT: ["#/baskets", "Baskets"], HUB: ["#/hub", "Data hub"], ECST: ["#/macro", "Macro"], MACRO: ["#/macro", "Macro"], CMDTY: ["#/commodities", "Commodities & energy"],
  CTRY: ["#/country", "Countries"], CRUDE: ["#/monitor/oil", "Crude oil monitor"], NATGAS: ["#/monitor/gas", "Gas & power monitor"],
  BULLION: ["#/monitor/gold", "Gold monitor"], TANK: ["#/tankers", "Tankers (AIS)"], ALRT: ["#/alerts", "Alerts"], DESK: ["#/desk", "My desk"], PORT: ["#/portfolio", "Portfolio"],
  JRNL: ["#/journal", "Journal"], RSRCH: ["#/research", "Research"], HELP: ["#/help", "Help"],
};
// index names and Bloomberg tickers -> bundled universe key
export const INDEX_ALIASES = {
  SPX: "sp500", SP500: "sp500", "S&P": "sp500", NDX: "nasdaq100", NASDAQ: "nasdaq100", INDU: "dow30", DOW: "dow30", DJI: "dow30",
  TSX: "tsx60", SPTSX60: "tsx60", DAX: "dax40", UKX: "ftse100", FTSE: "ftse100", CAC: "cac40", SMI: "smi", SX5E: "stoxx50", STOXX: "stoxx50",
  FTSEMIB: "ftsemib", MIB: "ftsemib", IBEX: "ibex35", AEX: "aex25", NKY: "nikkei225", NIKKEI: "nikkei225", HSI: "hsi", HANGSENG: "hsi",
  AS51: "asx200", ASX: "asx200", XJO: "asx200",
};
const INDEX_FUNCS = { MEMBERS: ["members", "members"], MEMB: ["members", "members"], BREADTH: ["breadth", "breadth, drivers & valuation"],
  DRIVERS: ["breadth", "breadth, drivers & valuation"], WEIGHTS: ["breadth", "breadth, drivers & valuation"], MOV: ["breadth", "breadth, drivers & valuation"] };

const SYMBOL = /^[\^]?[A-Z0-9][A-Z0-9&]{0,9}([.=\-][A-Z0-9]{1,4})?$/;

export function parseCommand(text) {
  const parts = (text || "").trim().toUpperCase().split(/\s+/).filter(Boolean);
  if (!parts.length || parts.length > 2) return null;
  if (parts.length === 1) {
    const p = PAGES[parts[0]];
    return p ? { href: p[0], label: `open ${p[1]}` } : null;
  }
  const [a, b] = parts;
  if (INDEX_ALIASES[a] && INDEX_FUNCS[b]) {
    const [tab, what] = INDEX_FUNCS[b];
    return { href: `#/indices/${INDEX_ALIASES[a]}/${tab}`, label: `${a}: ${what}` };
  }
  if (FUNCTIONS[b] && SYMBOL.test(a)) {
    const [tab, what] = FUNCTIONS[b];
    return { href: `#/stock/${encodeURIComponent(a)}/${tab}`, label: `${a}: ${what}` };
  }
  if (b === "HUB" && SYMBOL.test(a)) return { href: `#/hub/${encodeURIComponent("mkt:" + a)}`, label: `${a} in the data hub` };
  return null;
}
