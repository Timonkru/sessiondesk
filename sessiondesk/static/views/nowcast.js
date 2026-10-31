// Earnings nowcast: free company proxies vs the consensus for upcoming reports (features/nowcast.py). Unvalidated.
import { api } from "../lib/api.js";
import { h, clear, table, section, num, big, note, loading, errorBox, ago } from "../lib/ui.js";

const pp = (v, d = 1) => (v == null ? "–" : (v > 0 ? "+" : "") + num(v, d));

function proxyCell(p) {
  if (!p) return "–";
  if (!p.now) return h("span", { class: "muted small" }, p.history_n ? "no data this quarter" : `history from ${p.first}`);
  const unit = p.now.unit === "%" ? " %" : p.now.unit === "places" ? " places" : " $/mo";
  return [h("span", null, pp(p.now.value) + unit), h("div", { class: "small muted" },
    p.z == null ? `z needs 8 quarters (has ${p.history_n})` : `z ${pp(p.z)} vs ${p.history_n} quarters`)];
}

function consensusCell(r) {
  const c = r.consensus;
  if (!c) return h("span", { class: "muted small" }, "no consensus");
  return [h("span", null, big(c.revenue)), h("div", { class: "small muted" }, c.source + (c.analysts ? ` · ${c.analysts} analysts` : "")),
    r.quarter?.stale ? null
      : c.matches_quarter === false ? h("div", { class: "small warn" }, "year-ago figure differs from the SEC quarter: not compared") : null];
}

function beatCell(b, status) {
  if (!b) return h("span", { class: "muted small" }, status || "–");
  return [h("span", null, num(b.rate * 100, 0) + " %"), h("div", { class: "small muted" }, `${b.beats} of ${b.n} · SE ${num(b.se * 100, 0)} pp`)];
}

export async function render(root, _params, ctx) {
  const body = h("div", null, loading("Loading filings, estimates and proxies… (first load can take a minute)"));
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Earnings nowcast"),
    h("span", { class: "meta" }, "free company proxies vs consensus · unvalidated")), body);

  const draw = async (fresh) => {
    const d = await api("/api/nowcast" + (fresh ? "?fresh=1" : ""), { fresh: true });
    if (d.error && !d.rows) { clear(body, errorBox(d.error)); return; }
    const rows = d.rows || [];
    const keys = d.keys || {};
    const status = [
      keys.fmp || keys.finnhub ? `consensus history: ${keys.fmp ? "FMP" : "Finnhub"}` : "consensus history: key needed (FMP or Finnhub, Settings → Connectors) - revenue beat rates stay empty, revenue consensus comes from Yahoo",
      d.sec_contact ? "insider trades: SEC Form 4 on" : "insider trades: SEC contact email needed (Settings → Connectors → SEC EDGAR)",
      keys.quiver ? "Quiver Quantitative: key set" : "Quiver Quantitative: key needed (paid, not used on this page yet)",
    ];
    const alertBox = h("div");
    const a = d.alert || {};
    const on = h("input", { type: "checkbox", checked: !!a.enabled });
    const gap = h("input", { type: "text", inputmode: "decimal", value: String(a.gap_sd), style: { width: "60px" } });
    const minz = h("input", { type: "text", inputmode: "decimal", value: String(a.min_z), style: { width: "60px" } });
    clear(alertBox, h("div", { class: "toolbar" }, h("label", null, on, " alert on"),
      h("span", { class: "small muted" }, "when |gap| ≥"), gap, h("span", { class: "small muted" }, "residual SD and |proxy z| ≥"), minz,
      h("button", { onclick: async () => {
        const res = await api("/api/nowcast_alert", { method: "PUT", body: { enabled: on.checked, gap_sd: gap.value.replace(",", "."), min_z: minz.value.replace(",", ".") } });
        if (res.error) alertBox.append(errorBox(res.error)); else draw(false);
      } }, "Save")),
      note("Off by default. One notice per company and fiscal quarter, on the same path as your own alerts. It describes a divergence between two numbers, both unvalidated; it is not a trade signal."));

    clear(body,
      h("p", { class: "note warn" }, h("strong", null, (d.validation?.status || "unvalidated").toUpperCase() + ": "), d.validation?.text || ""),
      d.mapping_error ? errorBox(d.mapping_error) : null,
      h("p", { class: "small muted" }, status.join(" · ")),
      section(`Companies (watchlist, mapped, and index members reporting in the next ${d.lookahead_days} days)`, h("div", { class: "scroll" }, table([
        { label: "Company", render: (r) => [h("a", { href: "#/stock/" + encodeURIComponent(r.symbol) }, h("strong", null, r.symbol)),
          h("div", { class: "small muted" }, [r.name, r.why].filter(Boolean).join(" · "))] },
        { label: "Report", render: (r) => [r.report_date || "–", h("div", { class: "small muted" }, r.timing || "")] },
        { label: "Fiscal quarter", render: (r) => (r.error ? h("span", { class: "warn small" }, r.error) : !r.quarter ? h("span", { class: "muted small" }, r.symbol.includes(".") ? "no SEC filings (non-US)" : "no quarterly revenue at the SEC")
          : r.quarter.stale ? h("span", { class: "warn small" }, `SEC revenue data stop at ${r.quarter.last_filed}: quarter unknown, not compared`)
          : [`${r.quarter.start} – ${r.quarter.end}`, h("div", { class: "small muted" }, r.quarter.running ? `running, to ${r.quarter.to_date}` : "ended, not yet filed")]) },
        { label: "Consensus revenue", num: true, render: consensusCell },
        { label: "implied YoY", num: true, render: (r) => (r.gap ? pp(r.gap.implied_growth) + " %" : r.consensus && r.quarter?.year_ago_revenue && r.consensus.matches_quarter !== false ? pp((r.consensus.revenue / r.quarter.year_ago_revenue - 1) * 100) + " %" : "–") },
        { label: "Primary proxy", render: (r) => (r.primary ? [h("div", { class: "small muted" }, (r.proxies?.[r.primary]?.label) || r.primary), proxyCell(r.proxies?.[r.primary])] : h("span", { class: "muted small" }, r.mapped ? "no primary set" : "not mapped")) },
        { label: "Nowcast YoY", num: true, render: (r) => (!r.nowcast ? "–" : r.nowcast.missing ? h("span", { class: "muted small" }, r.nowcast.missing)
          : [pp(r.nowcast.growth) + " %", h("div", { class: "small muted" }, `n ${r.nowcast.n} · r ${num(r.nowcast.r, 2)} · t ${num(r.nowcast.t_b, 1)}${r.nowcast.partial ? " · partial quarter" : ""}`)]) },
        { label: "Gap", num: true, cls: (r) => (r.gap?.gap_sd != null && Math.abs(r.gap.gap_sd) >= (a.gap_sd || 2) ? "warn" : ""),
          render: (r) => (r.gap ? [pp(r.gap.gap_pp) + " pp", h("div", { class: "small muted" }, r.gap.gap_sd == null ? "" : pp(r.gap.gap_sd) + " SD")] : "–") },
        { label: "EPS beat rate", num: true, render: (r) => beatCell(r.beat_eps, "no history") },
        { label: "Revenue beat rate", num: true, render: (r) => beatCell(r.beat_revenue, r.consensus_history?.status) },
      ], rows, { empty: "No companies: add some to your watchlist or to the mapping file." }))),
      section("Proxies per company", ...rows.filter((r) => Object.keys(r.proxies || {}).length).map((r) => h("details", null,
        h("summary", null, `${r.symbol}: ${Object.keys(r.proxies).length} proxies` + (r.revenue_quarters ? ` · ${r.revenue_quarters} fiscal quarters at the SEC` : "")),
        table([
          { label: "Proxy", render: (p) => [p.label, p.key === r.primary ? h("span", { class: "tag" }, " primary") : null] },
          { label: "This quarter vs year ago", num: true, render: (p) => proxyCell(p) },
          { label: "Quarters with revenue", num: true, render: (p) => num(p.pairs, 0) },
          { label: "Fit (all quarters, in-sample)", render: (p) => (p.fit ? `growth = ${num(p.fit.a, 2)} + ${num(p.fit.b, 3)} × proxy · n ${p.fit.n} · r ${num(p.fit.r, 2)} · t ${num(p.fit.t_b, 1)}` : h("span", { class: "muted small" }, p.key === "insiders" ? "no regression (not a revenue proxy)" : "needs 8 quarters")) },
          { label: "Data", render: (p) => [h("span", { class: "small muted" }, `${p.first} – ${p.last} `), h("a", { href: "#/hub/" + encodeURIComponent(r.series[p.key]) }, "Data hub")] },
        ], Object.entries(r.proxies).map(([key, p]) => ({ key, ...p })))))),
      section("Alert", alertBox),
      note(d.note),
      h("p", { class: "small muted" }, `Mapping file (ticker → proxies, edit it and press refresh): ${d.mapping_file} · computed ${ago(d.asof)} ago `,
        h("button", { class: "linkish", type: "button", onclick: () => { clear(body, loading("Recomputing…")); draw(true); } }, "refresh")),
      Object.keys(d.proxy_errors || {}).length ? note("Last collector problems: " + Object.entries(d.proxy_errors).map(([k, v]) => `${k}: ${v}`).join(" · "), "warn") : null);

    ctx.setContext({ page: "Earnings nowcast (unvalidated)", validation: d.validation, rows: rows.map((r) => ({ symbol: r.symbol, report: r.report_date,
      quarter: r.quarter, consensus: r.consensus?.revenue, consensus_source: r.consensus?.source, nowcast_growth: r.nowcast?.growth,
      nowcast_n: r.nowcast?.n, gap: r.gap, beat_eps: r.beat_eps, beat_revenue: r.beat_revenue, primary: r.primary,
      primary_proxy: r.proxies?.[r.primary]?.now, primary_z: r.proxies?.[r.primary]?.z })) });
  };
  await draw(false);
}
