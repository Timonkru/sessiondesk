"""Deterministic reading of an earnings press release (8-K Exhibit 99): every per-share and revenue figure with the
line it came from, the conference call time and webcast link, guidance sentences, and the check that decides whether a
figure may be compared with a consensus at all.

The basis check is the core of it. Consensus numbers are on the data vendor's basis, which is usually adjusted but not
always (PLTR on 2026-11-02: Yahoo 0.41 on the adjusted basis, Nasdaq 0.32 on another), and REITs are compared on FFO. So
a figure counts as comparable only if the row it sits in also carries a value the vendor itself published for an
earlier quarter (the anchors, frozen before the report). No such row, or two rows with different current values: basis
unclear, and no hit or miss is shown. No guessing from labels.

Everything here is pure and works offline. No AI involved.
"""
from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, NavigableString, Tag

ET = ZoneInfo("America/New_York")
BLOCK = {"p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "center", "section", "article", "tr", "blockquote", "hr", "body", "html"}
TOKEN = re.compile(r"(?P<open>\()?\s*(?:US)?(?P<cur>[$€£])?\s*(?P<open2>\()?\s*(?P<sign>[-−–])?\s*(?:US)?(?:[$€£])?\s*"
                   r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<close>\))?\s*(?P<unit>%|bps|pts|basis points|[BbMm]\b|x\b)?")
NIL = {"—", "–", "-", "n/a", "na", "nm", "n.m.", "*", "**"}

EPS_GOOD = re.compile(r"\bEPS\b|earnings\s*(?:\(loss(?:es)?\)\s*)?(?:from continuing operations\s*)?per|(?:income|loss|profit)\s*(?:\(loss\)\s*)?(?:from continuing operations\s*)?per|"
                      r"per\s+(?:diluted\s+|common\s+|ordinary\s+|basic\s+and\s+diluted\s+)?share|per\s+ADS|\bA?FFO\b|funds from operations", re.I)
EPS_BAD = re.compile(r"dividend|distribution|book value|shares?\s+(?:used|outstanding)|weighted|average\s+(?:diluted\s+|basic\s+)?shares?|share count|number of shares|"
                     r"repurchas|buyback|price|cash flow|revenues?\s+per|sales\s+per|impact|effect|contribution|tangible|net asset|\bNAV\b|per\s+share\s+amounts?|except|"
                     r"year[- ]to[- ]date|full[- ]year|nine months|six months|twelve months|guidance|outlook|forecast|estimate", re.I)
BARE_DILUTED = re.compile(r"^(?:diluted|assuming dilution|basic and diluted|diluted and basic|net income\s*[-–—]\s*diluted|dilutive)\b", re.I)
SUB_ROW = re.compile(r"^(?:net (?:income|earnings|loss)|continuing operations|income from continuing|earnings from continuing|total|attributable)", re.I)
BASIC_ONLY = re.compile(r"\bbasic\b(?!\s+and\s+diluted)", re.I)
ADJUSTED = re.compile(r"non[- ]?gaap|non[- ]?ifrs|adjusted|\bcore\b|\boperating\b|underlying|normali[sz]ed|comparable|excluding|ex[- ]items|pro forma|as adjusted", re.I)
FFO = re.compile(r"\bA?FFO\b|funds from operations", re.I)
GAAP = re.compile(r"\bgaap\b|\bifrs\b|reported|net income|net earnings|net \(loss\)|net loss", re.I)
REVENUE = re.compile(r"^(?:consolidated\s+|total\s+)*(?:net\s+|operating\s+|gross\s+)?(?:revenues?|sales)(?:\s*,?\s*net(?:\s+of\s+[a-z ]+)?)?(?:\s+and other income)?(?:\s*\((?:gaap|as reported|reported)\))?\s*(?:\(?[a-z0-9]\)?\s*)?$|"
                     r"^total\s+(?:net\s+)?(?:revenues?|sales)\b|^net\s+(?:revenues?|sales)\b|^revenues?,?\s+net\b|^(?:reported|managed)\s+revenue\b", re.I)
GUIDE_HEAD = re.compile(r"\b(?:outlook|guidance|forecast|forward[- ]looking)\b", re.I)
RESULT_HEAD = re.compile(r"\b(?:results|performance|highlights|summary)\b", re.I)
BOILER = re.compile(r"safe harbor|forward[- ]looking statements?|actual results|risks? and uncertainties|may differ|could differ|no obligation|undertakes? no|private securities|factors that", re.I)
GUIDE_WORD = re.compile(r"\b(?:guidance|outlook|expects?|expected|expecting|anticipates?|forecasts?|projects?|now sees|sees|targets?|raises?|raised|raising|lowers?|lowered|lowering|reaffirm\w*|maintains?|narrow\w*)\b", re.I)
GUIDE_DIR = (("raised", re.compile(r"\b(?:raises?|raised|raising|increas\w+ (?:its |our |the )?(?:full[- ]year |fy\S* |annual )?(?:guidance|outlook))\b", re.I)),
             ("lowered", re.compile(r"\b(?:lowers?|lowered|lowering|cuts?|reduc\w+ (?:its |our |the )?(?:full[- ]year |fy\S* |annual )?(?:guidance|outlook))\b", re.I)),
             ("reaffirmed", re.compile(r"\b(?:reaffirm\w*|maintain\w*|reiterat\w*|unchanged)\b", re.I)))
QUARTER = re.compile(r"\b(first|second|third|fourth|1st|2nd|3rd|4th)[- ]quarter\b|\bQ([1-4])\b|\bquarter ended\s+([A-Z][a-z]+\.? \d{1,2}, ?\d{4})|\bquarter ending\s+([A-Z][a-z]+\.? \d{1,2}, ?\d{4})", re.I)
CALL_WORD = re.compile(r"conference call|earnings call|investor call|analyst call|webcast|web cast|live call|teleconference|audio cast|audiocast", re.I)
CLOCK = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\.?\s*[(,]?\s*(?:U\.?S\.?\s+)?(ET|EDT|EST|Eastern|CT|CDT|CST|Central|MT|MDT|MST|Mountain|PT|PDT|PST|Pacific|GMT|UTC|BST|CET)?\b", re.I)
ZONES = {"et": "America/New_York", "edt": "America/New_York", "est": "America/New_York", "eastern": "America/New_York",
         "ct": "America/Chicago", "cdt": "America/Chicago", "cst": "America/Chicago", "central": "America/Chicago",
         "mt": "America/Denver", "mdt": "America/Denver", "mst": "America/Denver", "mountain": "America/Denver",
         "pt": "America/Los_Angeles", "pdt": "America/Los_Angeles", "pst": "America/Los_Angeles", "pacific": "America/Los_Angeles",
         "gmt": "UTC", "utc": "UTC", "bst": "Europe/London", "cet": "Europe/Berlin"}
LONG_DATE = re.compile(r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(20\d\d))?", re.I)
URL_TEXT = re.compile(r"(?:https?://|www\.)[^\s<>\"')\]]+|\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|co)(?:/[^\s<>\"')\]]*)?", re.I)
SCALE_RE = re.compile(r"\b(?:in|dollars in|amounts in|\$ in|us\$ in|usd in|\(in|in u\.?s\.? dollars,?)\s*(?:u\.?s\.?\s*)?(?:\$\s*|dollars\s*)?(millions?|thousands?|billions?)\b|\$\s*(?:in\s*)?(millions?|thousands?|billions?)\b|\(?(000s|000's|\$000|\$m|\$mm)\)?", re.I)
SCALE = {"million": 1e6, "thousand": 1e3, "billion": 1e9, "000s": 1e3, "000's": 1e3, "$000": 1e3, "$m": 1e6, "$mm": 1e6}
SENTENCE = re.compile(r"(?<=[.;!?])(?<![apAP]\.[mM]\.)\s+(?=[A-Z])")      # "at 5:00 p.m. ET" stays one sentence
EPS_TOLERANCE = 0.011     # vendors round to cents
REV_TOLERANCE = 0.006     # press releases round to one or two digits less than the vendor
MAX_GAP = 0.5             # a figure this far from the consensus is more likely another basis than a real surprise
MAX_GAP_GAAP = 0.25


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ").replace("​", "")).strip()


def blocks(html: str) -> list[dict]:
    """The document in reading order: {'kind': 'text', 'text', 'links'} and {'kind': 'table', 'rows': [[cell, ...]], 'links'}.
    Tables that only lay out other tables are walked through; inline tags (font, span, ix:*) stay inside their block."""
    soup = BeautifulSoup(html or "", "html.parser")
    for t in soup(["script", "style", "head"]):
        t.decompose()
    out: list[dict] = []
    buf: list[str] = []
    links: list[str] = []

    def flush():
        text = clean("".join(buf))
        if text:
            out.append({"kind": "text", "text": text, "links": list(links)})
        buf.clear()
        links.clear()

    def walk(node):
        for ch in node.children:
            if isinstance(ch, NavigableString):
                if type(ch) is NavigableString:     # skips comments and declarations
                    buf.append(str(ch))
            elif isinstance(ch, Tag):
                name = ch.name.lower()
                if name == "table":
                    flush()
                    if ch.find("table"):
                        walk(ch)
                    else:
                        rows = [[clean(c.get_text(" ")) for c in tr.find_all(["td", "th"])] for tr in ch.find_all("tr")]
                        rows = [[c for c in r if c] for r in rows]
                        out.append({"kind": "table", "rows": [r for r in rows if r],
                                    "links": [a.get("href") for a in ch.find_all("a") if a.get("href")]})
                elif name == "br":
                    flush()
                elif name in BLOCK or name in ("td", "th"):
                    flush()
                    walk(ch)
                    flush()
                else:
                    if name == "a" and ch.get("href"):
                        links.append(ch.get("href"))
                    walk(ch)
    walk(soup)
    flush()
    return out


def plain_text(html: str) -> str:
    """The document as text, table rows on one line with cells separated by ' | ' (for saving and for quotes)."""
    lines = []
    for b in blocks(html):
        if b["kind"] == "text":
            lines.append(b["text"])
        else:
            lines.extend(" | ".join(r) for r in b["rows"])
            lines.append("")
    return "\n".join(lines)


def row_values(cells: list[str]) -> tuple[str, list[float | None]]:
    """Split a table row into its label and its plain numbers. Percentages, basis points and multiples are dropped, so
    'change' columns do not count as values; a dash keeps its column as None (pure, tested)."""
    label_cells = []
    i = 0
    while i < len(cells) and not re.fullmatch(r"[\s$€£()+\-−–—%.,\d]*|n/?a|nm|n\.m\.", cells[i], re.I) and not TOKEN.fullmatch(cells[i].strip()):
        label_cells.append(cells[i])
        i += 1
    label = clean(" ".join(label_cells))
    vals: list[float | None] = []
    rest = cells[i:]
    k = 0
    while k < len(rest):
        c = rest[k].strip()
        if c.lower() in NIL:
            vals.append(None)
            k += 1
            continue
        if c in ("$", "€", "£", "(", ")", "%", "+", "US$"):
            k += 1
            continue
        joined = c
        # a number's sign or unit may sit in its own cell: "(" "0.12" ")" "%"
        before = rest[k - 1].strip() if k else ""
        after = rest[k + 1].strip() if k + 1 < len(rest) else ""
        m = TOKEN.search(joined)
        if not m:
            k += 1
            continue
        for m in TOKEN.finditer(joined):
            unit = (m.group("unit") or "").lower()
            if unit in ("%", "bps", "pts", "basis points", "x") or (after in ("%", "bps", "pts") and m.end() == len(joined)):
                continue
            v = float(m.group("num").replace(",", ""))
            neg = m.group("open") or m.group("open2") or m.group("sign") or (before.endswith("(") and m.start() == 0)
            if unit == "b":
                v *= 1e9
            elif unit == "m":
                v *= 1e6
            vals.append(-v if neg else v)
        k += 1
    return label, vals


def _decimals(cells: list[str]) -> bool:
    return any(re.search(r"\d\.\d{2}", c) for c in cells)


def _table_scale(rows: list[list[str]], upto: int, before: list[str]) -> float | None:
    """The unit the table's money is in: nearest statement above the row, then the text just above the table."""
    for r in reversed(rows[:upto]):
        m = SCALE_RE.search(" ".join(r))
        if m:
            return SCALE.get((m.group(1) or m.group(2) or m.group(3) or "").lower().rstrip("s") if (m.group(1) or m.group(2)) else (m.group(3) or "").lower())
    for t in reversed(before):
        m = SCALE_RE.search(t)
        if m:
            return SCALE.get((m.group(1) or m.group(2) or m.group(3) or "").lower().rstrip("s") if (m.group(1) or m.group(2)) else (m.group(3) or "").lower())
    return None


def _current_column(rows: list[list[str]], upto: int) -> int | None:
    """Which value column holds the reported quarter. Usually the first; '2025 2026' means the second, and so does
    '2025 2026 | 2025 2026'. A header with three or more rising periods does not say which one is the quarter
    (HOOD: 'Q3 2025 | Q3 2026 | Q2 2026'), so None: the row is not used (pure, tested)."""
    for r in reversed(rows[:upto]):
        years = [int(y) for y in re.findall(r"\b(20\d\d)\b", " ".join(r))]
        if len(years) >= 2 and not any(re.search(r"[a-z]{3}.*\d+\.\d", c, re.I) for c in r):
            if years[1] < years[0] or years[0] == years[1]:
                return 0
            if len(years) == 2 or (len(years) == 4 and years[2] < years[1]):
                return 1
            return None
    return 0


def _section(rows: list[list[str]], upto: int, heads: list[str]) -> str:
    """Nearest heading row above (a row without numbers), plus the text heading above the table."""
    out = []
    for r in reversed(rows[max(0, upto - 14):upto]):
        lab = clean(" ".join(r))
        if lab and not re.search(r"\d", lab) and len(lab) < 120:      # a row with digits is data, even if only percentages
            out.append(lab)
            if ADJUSTED.search(lab) or GAAP.search(lab):
                break
    heading = [t for t in heads[-1:] if len(t) <= 60 and not re.search(r"\d", t)]     # a short sentence with figures is no heading
    return " | ".join(out[:3] + heading)


def _current(vals: list, idx: int | None) -> tuple[float | None, list[float]]:
    if idx is None:
        return None, []
    idx = idx if idx < len(vals) else 0
    return vals[idx], [v for i, v in enumerate(vals) if i != idx and v is not None]


def _basis(label: str, section: str) -> str:
    if FFO.search(label):
        return "ffo"
    if re.search(r"\bgaap\b", label, re.I) and not re.search(r"non[- ]?gaap", label, re.I):
        return "gaap"
    if ADJUSTED.search(label):
        return "adjusted"
    for part in section.split(" | "):      # nearest heading first
        if FFO.search(part):
            return "ffo"
        if re.search(r"non[- ]?gaap|adjusted", part, re.I):
            return "adjusted"
        if re.search(r"gaap", part, re.I):
            return "gaap"
    return "gaap"


def _short(q: str, n: int = 240) -> str:
    return q if len(q) <= n else q[: n - 1] + "…"


def period_row(vals: list) -> bool:
    """Whether a row's columns can be read as periods with the reported quarter in front. Not a reconciliation, where the
    first two add up to the third (UNP's year-ago table: 3.01 + 0.07 = 3.08), and not a multi-year series with more
    than four columns, where the reported quarter sits anywhere (NEM: nine columns, pure, tested)."""
    plain = [v for v in vals if v is not None]
    if len(plain) > 4:
        return False
    return not (len(plain) >= 3 and abs(plain[0] + plain[1] - plain[2]) <= EPS_TOLERANCE)


def _eps_from_table(rows: list[list[str]], heads: list[str]) -> list[dict]:
    out = []
    for i, cells in enumerate(rows):
        if not _decimals(cells):
            continue
        label, vals = row_values(cells)
        if not label or not vals:
            continue
        if EPS_BAD.search(label) or (BASIC_ONLY.search(label) and not re.search(r"dilut", label, re.I)):
            continue
        above = [row_values(r)[0] for r in rows[max(0, i - 5):i]]
        above_text = " | ".join(a for a in above if a)
        good = bool(EPS_GOOD.search(label))
        if not good and (BARE_DILUTED.match(label) or SUB_ROW.match(label)):
            good = bool(re.search(r"per\s+(?:\w+\s+)?share|\bEPS\b", above_text, re.I)) and \
                   (bool(BARE_DILUTED.match(label)) or bool(re.search(r"dilut", above_text, re.I)))
            if good and EPS_BAD.search(above[-1] if above else ""):
                good = False
        if not good:
            continue
        if not re.search(r"per|eps|dilut|ffo", label, re.I) and not above_text:
            continue
        if not period_row(vals):
            continue
        cur, prior = _current(vals, _current_column(rows, i))
        if cur is None or abs(cur) >= 2000 or any(abs(p) >= 2000 for p in prior):
            continue
        section = _section(rows, i, heads)
        out.append({"value": round(cur, 4), "prior": [round(p, 4) for p in prior], "label": clean(f"{above[-1] + ': ' if above and above[-1] and not EPS_GOOD.search(label) else ''}{label}"),
                    "basis": _basis(label, section), "quote": _short(" | ".join(cells)), "where": "table"})
    return out


EPS_PHRASE = re.compile(r"(?P<label>(?:[\w'’.\-/&*]+[ ,]+){0,7}?(?:EPS|earnings\s+(?:\(loss\)\s+)?per\s+(?:diluted\s+|common\s+)?share|(?:income|loss)\s+per\s+(?:diluted\s+|common\s+)?share|A?FFO\s+per\s+(?:diluted\s+)?share)\b[\s*]*(?:\([^)]{0,40}\))?[^$.;]{0,45}?)\(?\$\s?(?P<v>\d{1,4}\.\d{2})\b", re.I)
PER_SHARE = re.compile(r"(?P<label>(?:[\w'’.\-/&]+[ ,]+){0,8}?)\(?\$\s?(?P<v>\d{1,4}\.\d{2})\)?\s+(?:per|a)\s+(?:diluted\s+|common\s+|fully\s+diluted\s+)*share\b", re.I)
NARR_BAD = re.compile(r"dividend|distribution|repurchas|buyback|average price|share price|stock price|charge|impact|benefit|headwind|tailwind|expens|tax|gain|expect|guidance|outlook|forecast|anticipat|"
                      r"full[- ]year|fiscal (?:year )?20|year[- ]to[- ]date|nine months|six months|twelve months|next quarter|reduc|increase[ds]? by|cents|include", re.I)
PRIOR_PHRASE = re.compile(r"(?:compared\s+(?:to|with)|versus|vs\.?|from|against)\s[^;]{0,70}?\(?\$\s?(\d{1,4}\.\d{2})\b(?!\s*(?:billion|million))", re.I)


def _eps_from_text(text: str) -> list[dict]:
    out = []
    if BOILER.search(text):
        return out
    for sent in re.split(r"(?<=[.;:!?])\s+(?=[A-Z•·•])|\s*[•·•]\s*", text):
        if not 6 <= len(sent) <= 700 or "$" not in sent:
            continue
        for rx in (EPS_PHRASE, PER_SHARE):
            for m in rx.finditer(sent):
                label = clean(m.group("label")).strip(" ,:-–—")
                ante = sent[max(0, m.start("v") - 90):m.start("v")]
                if NARR_BAD.search(ante):
                    continue
                if rx is PER_SHARE and not re.search(r"net income|net earnings|net loss|earnings|income|profit|loss|results?|ffo", ante, re.I):
                    continue
                neg = bool(re.search(r"\bloss\b", label, re.I) and not re.search(r"\(loss\)", label, re.I))
                rest = sent[m.end("v"):m.end("v") + 110]
                prior = PRIOR_PHRASE.search(rest)
                val = float(m.group("v"))
                tail = sent[m.end("v"):m.end("v") + 60]      # "$5.75 per share excluding significant items"
                out.append({"value": -val if neg else val, "prior": [float(prior.group(1))] if prior else [], "label": _short(label, 90),
                            "basis": _basis(f"{label} {tail}", ""), "quote": _short(sent), "where": "text"})
    return out


REV_TEXT = re.compile(r"(?P<label>(?:(?:total|net|consolidated|record|quarterly|third[- ]quarter|second[- ]quarter|first[- ]quarter|fourth[- ]quarter)\s+){0,3}(?:revenues?|net sales|sales))"
                      r"(?:\s+(?:of|were|was|totaled|totalled|reached|at|came in at|grew to|increased to|rose to|up to)){1,2}\s*\$\s?(?P<v>\d[\d,]*(?:\.\d+)?)\s*(?P<u>billion|million|B|M)\b", re.I)


def _rev_from_table(rows, heads, before) -> list[dict]:
    out = []
    for i, cells in enumerate(rows):
        label, vals = row_values(cells)
        if not label or not vals or not REVENUE.search(label) or re.search(r"growth|per |%|cost|deferred|backlog", label, re.I):
            continue
        cur, prior = _current(vals, _current_column(rows, i))
        if cur is None:
            continue
        scale = _table_scale(rows, i, before)
        if scale is None and abs(cur) < 1e6:
            continue
        scale = scale or 1.0
        if cur * scale < 1e6:       # a percent or ratio row that slipped through
            continue
        out.append({"value": cur * scale, "prior": [p * scale for p in prior], "label": label, "quote": _short(" | ".join(cells)), "where": "table",
                    "basis": "adjusted" if ADJUSTED.search(label) or re.search(r"non[- ]?gaap|adjusted", _section(rows, i, heads), re.I) else "reported"})
    return out


def _rev_from_text(text: str) -> list[dict]:
    if BOILER.search(text):
        return []
    out = []
    for m in REV_TEXT.finditer(text):
        ante = text[max(0, m.start() - 70):m.start()]
        if re.search(r"expect|guidance|outlook|forecast|full[- ]year|fiscal (?:year )?20|year[- ]to[- ]date|segment|deferred", ante + m.group(0), re.I):
            continue
        u = m.group("u").lower()
        val = float(m.group("v").replace(",", "")) * (1e9 if u.startswith("b") else 1e6)
        start, end = max(0, m.start() - 60), min(len(text), m.end() + 80)
        out.append({"value": val, "prior": [], "label": clean(m.group("label")), "quote": _short(text[start:end].strip()), "where": "text",
                    "basis": "reported", "digits": len(m.group("v").split(".")[1]) if "." in m.group("v") else 0})
    return out


def _guidance(bl: list[dict]) -> dict:
    """Sentences and rows that state an outlook with a number, with the direction only when the sentence says it."""
    quotes: list[str] = []
    in_head = False
    for b in bl:
        if b["kind"] == "text":
            t = b["text"]
            if len(t) < 90 and GUIDE_HEAD.search(t):
                in_head = not BOILER.search(t)
                if not RESULT_HEAD.search(t) or re.search(r"guidance", t, re.I):
                    continue
            if len(t) < 70 and t[:1].isupper() and not re.search(r"\d", t):
                in_head = False
            if BOILER.search(t):
                continue
            for s in SENTENCE.split(t):
                if GUIDE_WORD.search(s) and re.search(r"\d", s) and re.search(r"\b(?:guidance|outlook|expect\w*|forecast\w*|anticipat\w*|now sees|sees)\b", s, re.I) \
                        and re.search(r"revenue|sales|eps|earnings|per share|margin|income|profit|cash flow|ffo|growth", s, re.I) and 25 < len(s) < 500:
                    quotes.append(s)
        elif in_head:
            for r in b["rows"]:
                lab, vals = row_values(r)
                if lab and vals and re.search(r"revenue|sales|eps|earnings|per share|margin|income|ffo", lab, re.I):
                    quotes.append(" | ".join(r))
    seen, uniq = set(), []
    for q in quotes:
        k = q[:80].lower()
        if k not in seen:
            seen.add(k)
            uniq.append(_short(q, 320))
    head = " ".join(q for q in uniq if not q.count(" | "))
    direction = None
    for name, rx in GUIDE_DIR:
        if rx.search(head):
            direction = name
            break
    return {"found": bool(uniq), "direction": direction, "quotes": uniq[:6]}


def _month(name: str) -> int:
    return ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].index(name[:3].lower()) + 1


def call_info(bl: list[dict], filed: dt.datetime | None = None) -> dict:
    """Time and webcast link of the earnings call from the release. The clock time must sit in a sentence about a call
    or webcast; with no zone named it is not converted (time stays unknown). The date: an explicit one, 'tomorrow', or
    the filing day (pure, tested)."""
    when, time_quote, url, url_quote = None, None, None, None
    ref = filed.astimezone(ET) if filed else None
    for b in bl:
        if b["kind"] != "text":
            continue
        t = b["text"]
        if not CALL_WORD.search(t) or BOILER.search(t[:200]):
            continue
        for s in SENTENCE.split(t):
            if not CALL_WORD.search(s):
                continue
            if not when:
                for c in CLOCK.finditer(s):
                    if not c.group(4) or not ref:
                        continue
                    hour = int(c.group(1)) % 12 + (12 if c.group(3).lower() == "p" else 0)
                    tz = ZoneInfo(ZONES[c.group(4).lower()])
                    day = ref.date()
                    d = LONG_DATE.search(s)
                    if d:
                        try:
                            day = dt.date(int(d.group(3) or ref.year), _month(d.group(1)), int(d.group(2)))
                        except ValueError:
                            continue
                    elif re.search(r"\btomorrow\b", s, re.I):
                        day += dt.timedelta(days=1)
                    if abs((day - ref.date()).days) > 14:
                        continue
                    when = dt.datetime(day.year, day.month, day.day, hour, int(c.group(2) or 0), tzinfo=tz).timestamp()
                    time_quote = _short(s)
                    break
            if not url:
                cand = [u for u in b.get("links") or [] if u.lower().startswith(("http", "www"))]
                cand += [m.group(0).rstrip(".,;") for m in URL_TEXT.finditer(s)]
                cand = [u for u in cand if not re.search(r"sec\.gov|mailto|twitter|linkedin|facebook|youtube\.com/user|forward", u, re.I)]
                if cand:
                    url = cand[0] if cand[0].lower().startswith("http") else "https://" + cand[0]
                    url_quote = _short(s)
    return {"ts": when, "time_quote": time_quote, "url": url, "url_quote": url_quote}


def quarter_label(bl: list[dict]) -> str | None:
    for b in bl[:40]:
        if b["kind"] == "text":
            m = QUARTER.search(b["text"])
            if m:
                return clean(m.group(0))
    return None


def highlights(bl: list[dict], limit: int = 5) -> list[str]:
    """The release's own opening lines that carry a number (verbatim, no rewording)."""
    out = []
    for b in bl[:60]:
        if b["kind"] != "text" or BOILER.search(b["text"]):
            continue
        t = b["text"]
        if 35 < len(t) < 420 and re.search(r"\$\s?\d|\d%", t):
            out.append(t)
            if len(out) >= limit:
                break
    return out


def parse_release(html: str, filed: dt.datetime | None = None) -> dict:
    """All candidates of one release (pure, tested): eps [{value, prior, label, basis, quote, where}], revenue, guidance,
    call, quarter, highlights. The choice of the comparable figure happens later, in choose()."""
    bl = blocks(html)
    eps, rev = [], []
    heads: list[str] = []
    recent: list[str] = []
    in_guide = False
    for b in bl:
        if b["kind"] == "text":
            t = b["text"]
            if len(t) < 90:
                in_guide = bool(GUIDE_HEAD.search(t)) and not BOILER.search(t) and not RESULT_HEAD.search(t)
                heads.append(t)
            eps.extend(_eps_from_text(t))
            rev.extend(_rev_from_text(t))
            recent = (recent + [t])[-4:]
        elif not in_guide:
            title = " ".join(" ".join(r) for r in b["rows"][:3])
            if not GUIDE_HEAD.search(title) or RESULT_HEAD.search(title):
                eps.extend(_eps_from_table(b["rows"], heads))
                rev.extend(_rev_from_table(b["rows"], heads, recent))
    _merge_same_label(eps)
    return {"eps": eps, "revenue": rev, "guidance": _guidance(bl), "call": call_info(bl, filed), "quarter": quarter_label(bl),
            "highlights": highlights(bl)}


def _merge_same_label(cands: list[dict]) -> None:
    """Some releases give the year-ago quarter in its own table, under the same label (NSC: 'Adjusted diluted earnings
    per share' 3.62, further down 3.30). The later rows then count as earlier values of the first one."""
    first: dict[tuple, dict] = {}
    for c in cands:
        if c["where"] != "table":
            continue
        key = (c["basis"], re.sub(r"[^a-z]+", " ", c["label"].lower()).strip())
        if key not in first:
            first[key] = c
        elif abs(c["value"] - first[key]["value"]) > EPS_TOLERANCE:
            first[key].setdefault("same_label", []).append(c["value"])


def _hits(cand: dict, anchors: list[float], tol) -> bool:
    """A row confirms only through its next two columns (prior quarter, year ago). Further columns are year-to-date or
    segment totals, where a match is chance (NEE: FPL 0.71, NEER 0.53, Corporate -0.11, total 1.13)."""
    earlier = list(cand.get("prior") or [])[:2] + list(cand.get("same_label") or [])
    return any(tol(p, a) for p in earlier for a in anchors)


def choose(cands: list[dict], anchors: list[float], kind: str = "eps") -> dict:
    """The figure whose row carries a value the vendor published for an earlier quarter (pure, tested).
    Returns status 'confirmed' with the figure, or 'unclear' with the reason and the labelled figures that were found:
    no anchors, no row matched, or matching rows that disagree on the current value."""
    tol = (lambda p, a: abs(p - a) <= EPS_TOLERANCE) if kind == "eps" else (lambda p, a: a != 0 and abs(p - a) / abs(a) <= REV_TOLERANCE)
    if not cands:
        return {"status": "none", "reason": "no figure found in the release"}
    if not anchors:
        return {"status": "unclear", "reason": "no earlier vendor figure to check the basis against"}
    matched = [c for c in cands if _hits(c, anchors, tol)]
    if not matched:
        return {"status": "unclear", "reason": "no row in the release carries a figure the vendor published for an earlier quarter"}
    if kind == "eps":      # a cent apart on both rows (LRCX: GAAP 1.81, non-GAAP 1.82, vendor 1.82): the exact one decides
        matched = [c for c in matched if _hits(c, anchors, lambda p, a: abs(p - a) <= 0.005)] or matched
    same = (lambda a, b: abs(a - b) <= 0.005) if kind == "eps" else (lambda a, b: abs(a - b) / max(abs(a), abs(b), 1) <= REV_TOLERANCE)
    first = matched[0]
    if all(same(c["value"], first["value"]) for c in matched):
        # a quarter without adjustments a year ago makes the GAAP row match too: with an adjusted figure in the same
        # release that differs, the match says nothing (JPM 2026-10-13: GAAP 5.57, excluding items 5.75, vendor 5.75)
        rival = [c for c in cands if c.get("basis") in ("adjusted", "ffo") and not same(c["value"], first["value"])
                 and abs(c["value"] - first["value"]) <= 0.6 * max(abs(c["value"]), abs(first["value"]))]     # far off = an effect or a year-to-date figure
        if first.get("basis") == "gaap" and rival and kind == "eps":
            return {"status": "unclear", "reason": f"the GAAP row matches, but the release also gives {rival[0]['label'][:40]} {rival[0]['value']:g}"}
        return {"status": "confirmed", **first}
    return {"status": "unclear", "reason": "rows on different bases match the vendor's earlier figures: " +
            ", ".join(sorted({f"{c['label'][:40]} {c['value']:g}" for c in matched})[:4])}


def verdict(actual: float | None, consensus: float | None, status: str, kind: str = "eps", basis: str | None = None) -> dict:
    """Hit or miss only on a confirmed basis, a known consensus, and a gap that can still be a real surprise. A GAAP figure
    has a tighter limit: one-offs move it far from a consensus that leaves them out (VRTX 2026-11-02: GAAP 2.56 against 4.36,
    while the adjusted figure was in line). Under a cent is rounding, since the consensus has more digits than the
    company reports (pure, tested)."""
    if consensus is None:
        return {"verdict": None, "why": "no consensus frozen before the report"}
    if status != "confirmed" or actual is None:
        return {"verdict": "basis unclear", "why": "the basis of the figure could not be matched to the consensus"}
    base = abs(consensus)
    gap = actual - consensus
    limit = MAX_GAP_GAAP if kind == "eps" and basis == "gaap" else MAX_GAP
    if base > 0 and abs(gap) / base > limit and abs(gap) > (0.25 if kind == "eps" else 0):
        return {"verdict": "basis unclear", "why": f"{gap / base * 100:+.0f}% from the consensus is more likely another basis than a real surprise"}
    if kind == "eps":
        word = "in line" if abs(round(gap, 3)) < 0.01 else "beat" if gap > 0 else "miss"
    else:
        word = "beat" if gap > 0 else "miss" if gap < 0 else "in line"
    return {"verdict": word, "surprise_pct": gap / base * 100 if base else None}
