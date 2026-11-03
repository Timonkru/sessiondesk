# Earnings desk

Exact times, the report documents, the call, and a flash summary with hit or miss, all from free sources. US filers only.

Where to find it: **Calendar → Earnings** (times, call, click a row for the report panel) and **Data hub → Earnings
flash** (every summary collected). The calendar's Timeline shows the best known time as well.

It needs one thing from you: **Settings → Connectors → SEC EDGAR → Contact email**. SEC asks every automated client to
name a contact and blocks those that do not. Without it, nothing here calls SEC and the pages say so.

## Times

Every time says what it is:

| Kind | Meaning |
| --- | --- |
| actual | SEC's acceptance time of the 8-K with Item 2.02 |
| announced | named before the fact: call time from the press release or from Yahoo (date confirmed) |
| historical estimate | median of the company's last eight results filings in Eastern time, with the spread |
| session only | the free calendar's "after close" / "pre-market", because no history is loaded yet |

Times show in Eastern time and in your local time. Yahoo's report timestamp is not used as a time when a company history
exists: it is always a round placeholder, 25 minutes off at the median (October 2026 sample below).

## Documents

The report panel links the press release (8-K Exhibit 99) and the 10-Q / 10-K on sec.gov. "Save" stores a copy under
`<data dir>/earnings/<SYMBOL>/<date>/`, as text or original HTML. The address always comes from SEC's own filing
list. Stored files are served only as downloads: a filing is foreign HTML and never renders on the app's origin. Keep
these files local. Do not put them, transcripts or call audio into a repository, and do not redistribute them.

## Calls

"Join call" opens the webcast **in its own window**. Embedding is not offered: webcast hosts ask you to register first
(Q4, the common host, opens with a registration form), and investor sites send headers that forbid framing (15 of 33 links
checked).

The link falls back and says so: this release → last quarter's release → company site ("IR site" button). Only about one
link in seven in a release is a real webcast link; most releases only name the company's site. Nothing here records or
stores audio or transcripts.

## Flash summary

A collector polls EDGAR's current-filings feed every 30 seconds **only while a report is due**: one request covers all
companies, with at most eight SEC requests per second overall and a ten-minute stop on a 429. It reads Exhibit 99 by rules
(tables, then sentences), with no AI, and shows reported figures with the line they came from, stated guidance, and the
latency from SEC's acceptance to the display. The press wire is usually a few minutes ahead of SEC, so this is not the
first moment a number is public.

**Which reports:** your watchlist, members of the big indices and large caps. Any other report can be read on request in its
panel; such a read is marked and claims no latency.

### Hit or miss

Shown only when all of this holds:

1. **Consensus frozen before the report.** Yahoo's "current quarter" rolls to the next quarter once a company has
   reported, and Nasdaq drops its year-ago EPS. So snapshots are taken up to two days ahead and refused once the report's
   window has opened. No snapshot: no verdict, not a late one.
2. **The basis is confirmed.** Vendors differ: on 2 Nov 2026 Palantir's consensus was 0.41 at Yahoo and 0.32 at Nasdaq, and
   REITs are often compared on FFO. So a figure counts only if its row in the release also holds a value that vendor
   published for the previous or the year-ago quarter. No such row, or rows on different bases that match: **basis unclear**.
3. **The gap can be real.** More than 50 % from the consensus (25 % for a GAAP figure, which carries one-offs) is shown as
   basis unclear. Under one cent counts as in line, since a consensus has more digits than a company reports.

Each vendor is checked separately. If they disagree the row says "sources disagree". A beat says little on its own: about
72 % of reports beat (2016-2022, n = 1,679). The desk never turns a figure into a trade statement.

**Known limit of Nasdaq's calendar:** its `eps` field holds the year-ago quarter until `surprise` is filled in, which
caused false misses in the Reported list before (a9f5843). The desk does not use that field.

### Push

Off by default. **Settings → Push → Earnings flash** sends only your watchlist.

### AI reading (optional)

The panel offers a second reading with your own key, on request only, and it costs what your provider charges. Each number
must come with a word-for-word quote; a quote that is not in the release, or does not hold the number, is dropped. The
rule-based flash needs no key. Not yet tested with a real model.

## Coverage

| Company | What you get |
| --- | --- |
| US filer (8-K Item 2.02) | everything above |
| Foreign filer (6-K, 20-F) | link to the 6-K, no flash: a 6-K has no results item, and the release often is not an exhibit |
| No EDGAR filings (DAX etc.) | "not covered" |

Non-US reports would need each company's own site (no common format) or a paid feed.

## Measured on the October 2026 season

Sample: Nasdaq calendar 12-30 Oct 2026, market cap at least 15 bn USD, 343 reports. 315 had an Exhibit 99 on EDGAR; 24 were
foreign filers on 6-K; 4 had no results 8-K near the date.

| Question | Result |
| --- | --- |
| Time from the company's own history | median error 2 min, 83 % within 15 min, p90 46 min, session right 94 % (n 290) |
| Yahoo report timestamp | always a round minute, median error 25 min, 40 % within 15 min (n 302) |
| Call time / link in the release | 75 % / 69 %, both 62 % (n 315) |
| Kind of link | company site 153, investor page 31, webcast or events page 33 (n 217) |
| Call after SEC acceptance | median 104 min |
| Webcast framing (33 links) | 15 forbid framing, 11 refused an automated request, 17 no header; hosts ask for registration |
| Press wire vs SEC (n 32, via Google News dates) | 22 cases: wire 0.1 to 57 min ahead, typically 2-7 min. 10 cases show the wire 33-59 min after SEC, more likely Google's indexing than the wire, so this is a rough figure |

### Reading the figures: hit or miss against the vendor's own result

Rules were tuned on 108 reports, then tested once on the 207 others (holdout). Truth = what the vendor itself lists for the
report, because a vendor's consensus stands on its own basis. Anchors come only from quarters before the report. Yahoo's
consensus is read afterwards here; in use it is frozen.

| Holdout, n = 203 Yahoo / 207 Nasdaq | Yahoo | Nasdaq |
| --- | --- | --- |
| A verdict is shown | 50 % | 48 % |
| "Basis unclear" | 50 % | 52 % |
| Hit or miss wrong, of those shown | 2.0 % (2 of 102) | 3.0 % (3 of 100) |
| Figure differs from the vendor's, of those shown | 2.9 % | 7.0 % |

The tuning set had 0 wrong, so read the holdout, not that. Two fixes made after this test (reconciliation rows, long series)
removed two errors and exposed two others (2.0 % and 2.1 % on a rerun that is no longer a clean test). Expect about one wrong
verdict in fifty and no verdict for half of all reports; each row shows the line it came from, so check before relying on one.
A figure that differs while the verdict agrees is often the vendor adjusting on its own (Alphabet: 2.12 reported, 2.67 Yahoo).

Forward test against a consensus frozen before the reports of 2 Nov 2026 (after-hours names, Yahoo side, n = 17): 7 of 8
verdicts agreed with Yahoo's own result, 9 were basis unclear. A single day, and two rules were tightened after looking at
it, so this is a check rather than a rate.
Revenue has no free historical consensus, so its verdict could only be read forward and has no measured error rate yet.
