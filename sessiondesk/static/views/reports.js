// Reports: performance of one account over a period, straight from the MetaTrader 5 deal history - a PDF to show
// (locked against editing, watermarked, with a SHA-256 fingerprint of its data) and a CSV with the same data to check.
// Below: the register of issued reports and a check of a PDF or CSV that someone shows you.
import { api } from "../lib/api.js";
import { h, clear, table, section, note, loading, errorBox, num, pct, dir, stamp } from "../lib/ui.js";

const PERIODS = [["last_month", "Last calendar month"], ["this_month", "This month so far"], ["last_30", "Last 30 days"], ["custom", "Custom dates"]];

export async function render(root, _params, ctx) {
  const token = document.querySelector('meta[name="sd-token"]').content;
  const file = (id, ext) => `/api/reports/file/${id}.${ext}?t=${encodeURIComponent(token)}`;
  const links = (r) => h("span", null, h("a", { href: file(r.id, "pdf") + "&view=1", target: "_blank", rel: "noopener" }, "view"), " · ",
    h("a", { href: file(r.id, "pdf"), download: `${r.id}.pdf` }, "PDF"), " · ",
    h("a", { href: file(r.id, "csv"), download: `${r.id}.csv` }, "CSV"));
  const form = h("div", null, loading()), result = h("div"), issued = h("div"), check = h("div"), recheckBox = h("div");
  // build an issued report again from the broker export as it is now and compare: identical = made correctly
  const recheckNote = (v) => (v.error ? note(v.error, "warn")
    : !v.reproducible ? note(`${v.report_id}: cannot be rebuilt - ${v.detail}`, "warn")
    : v.identical ? note(`${v.report_id}: rebuilt from the broker export now - identical (${v.checked}). The report was made correctly from the broker's data.`, "up")
    : v.explained ? h("div", null, note(`${v.report_id}: rebuilt from the broker export now - ${v.explained}`, "up"),
      h("details", null, h("summary", { class: "small muted" }, "the differences"), h("ul", { class: "small" }, v.differences.map((x) => h("li", null, x)))))
    : h("div", null, note(`${v.report_id}: rebuilt from the broker export now - it differs:`, "warn"), h("ul", { class: "small" }, v.differences.map((x) => h("li", null, x)))));
  const recheck = async (id, box) => {
    clear(box, loading("Rebuilding from the broker export…"));
    clear(box, recheckNote(await api(`/api/reports/${encodeURIComponent(id)}/recheck`, { method: "POST", body: {} })));
  };
  root.append(h("div", { class: "pagehead" }, h("h1", null, "Reports"), h("span", { class: "meta" }, "performance of an account over a period - a PDF to show, a CSV to check")),
    section("New report", form, result), section("Check a report someone shows you", check), section("Issued reports", recheckBox, issued));

  const load = async () => {
    const d = await api("/api/reports", { fresh: true });
    if (d.error) { clear(form, errorBox(d.error)); return; }
    const accs = d.accounts || [];
    drawIssued(d.issued || []);
    if (!accs.length) { clear(form, note("No MetaTrader 5 account with exported deals. Accounts & EAs shows how to connect the terminal.", "warn")); return; }
    const acc = h("select", null, accs.map((a) => h("option", { value: a.account }, `${a.account} · ${a.currency || ""} · deals ${a.from || "?"} to ${a.to || "?"}`)));
    const per = h("select", null, PERIODS.map(([k, l]) => h("option", { value: k }, l)));
    const frm = h("input", { type: "date" }), to = h("input", { type: "date" });
    const dates = h("span", { hidden: true }, " from ", frm, " to ", to);
    per.addEventListener("change", () => { dates.hidden = per.value !== "custom"; });
    const full = h("input", { type: "checkbox" });
    const units = h("select", { title: "Percent only: no amounts and no lot sizes anywhere in the PDF and CSV - results in % of the start balance, the balance as an index (start = 100)" },
      h("option", { value: "money" }, "amounts and %"), h("option", { value: "percent" }, "% only"));
    try { units.value = localStorage.getItem("sd.reportUnits") || "money"; } catch { /* storage blocked */ }
    units.addEventListener("change", () => { try { localStorage.setItem("sd.reportUnits", units.value); } catch { /* storage blocked */ } });
    // 2026-10-22: performance report (taxes as one figure) or tax report (every tax booking, taxes per month and day)
    const kind = h("select", { title: "Performance report: taxes as one net figure. Tax report: every tax booking listed, taxes per month and per day." },
      h("option", { value: "summed" }, "performance (taxes summed)"), h("option", { value: "itemised" }, "tax report (taxes itemised)"));
    try { kind.value = localStorage.getItem("sd.reportTaxes") || "summed"; } catch { /* storage blocked */ }
    kind.addEventListener("change", () => { try { localStorage.setItem("sd.reportTaxes", kind.value); } catch { /* storage blocked */ } });
    const go = h("button", { onclick: async () => {
      go.disabled = true; clear(result, loading("Building the report…"));
      const r = await api("/api/reports", { method: "POST", body: { account: acc.value, period: per.value, from: frm.value, to: to.value, full_number: full.checked, units: units.value, taxes: kind.value } });
      go.disabled = false;
      if (r.error) { clear(result, errorBox(r.error)); return; }
      const s = r.summary, pctOnly = r.units === "percent";
      clear(result, h("div", { class: "keystrip" }, [["Report", r.id], ["Period", `${r.period_from} to ${r.period_to}`],
        ["Net", h("span", { class: dir(s.net) }, pctOnly ? pct(s.net_pct, 2) : `${num(s.net, 2)} ${r.currency || ""} (${pct(s.net_pct, 2)})`)], ["Positions", s.trades],
        ["Win rate", s.win_rate == null ? "–" : pct(s.win_rate, 0, false)], ["Max drawdown", pctOnly ? pct(s.max_dd_pct, 2, false) : `${num(s.max_dd, 2)} (${pct(s.max_dd_pct, 2, false)})`],
        ["Shown as", pctOnly ? "% only" : "amounts and %"], ["Kind", r.taxes === "itemised" ? "tax report" : "performance"]]
        .map(([k, v]) => h("div", null, h("span", { class: "k" }, k), h("span", { class: "v" }, v)))),
        h("p", null, h("strong", null, "Download: "), links(r)),
        !r.check || !r.check.days ? note("Balance check: no recorded day-start balances for this account yet - the start balance is reconstructed and unchecked.", "warn")
          : r.check.worst ? note(`Balance check: ${r.check.matched} of ${r.check.days} recorded day starts agree; the largest difference is ${num(r.check.worst.diff, 2)} on ${r.check.worst.day}. This account has balance changes that are not trades (fees, dividend adjustments, deposits, payouts) or the export misses deals - return and drawdown can be off by about that much. The PDF says so on its first page.`, "warn")
          : note(`Balance check: all ${r.check.days} recorded day-start balances agree with the reconstruction.`, "up"),
        r.trimmed_from ? note(`The deal export of this account starts later than ${r.trimmed_from}: the report covers ${r.period_from} to ${r.period_to} only.`, "warn") : null,
        note(`Fingerprint (SHA-256 of the report data): ${r.data_sha}`));
      ctx.setContext({ page: "Reports", last_report: { id: r.id, period: [r.period_from, r.period_to], ...s } });
      load();
    } }, "Create report");
    clear(form, h("div", { class: "toolbar" }, h("label", null, "Account ", acc), h("label", null, "Period ", per), dates,
      h("label", null, "Report ", kind), h("label", null, "Show ", units),
      h("label", { title: "Without it the account shows as …638, as everywhere in SessionDesk (Settings → Privacy)" }, full, " full account number"), go),
    note("From the MetaTrader 5 deal history the terminal exports - nothing typed in. The PDF opens without a password but is locked against editing, carries a watermark with its report ID on every page and the fingerprint of its data; the CSV has the same data, so a changed number shows when the fingerprint is recomputed. It is your own software's statement, not an audit: for independent proof compare the position IDs with the broker's statement or give read-only (investor) access."));
  };

  const drawIssued = (rows) => clear(issued, table([
    { label: "Report", render: (r) => h("code", null, r.id) }, { label: "Created", render: (r) => stamp(r.created) },
    { label: "Account", render: (r) => r.account }, { label: "Period", render: (r) => `${r.period_from} to ${r.period_to}` },
    { label: "Kind", render: (r) => (r.taxes === "itemised" ? "tax report" : r.taxes === "summed" ? "performance" : h("span", { class: "muted small" }, "–")) },
    { label: "Net", num: true, cls: (r) => dir(r.net_pct), render: (r) => (r.units === "percent" || r.net == null ? h("span", { class: "muted small" }, "% only") : `${num(r.net, 2)} ${r.currency || ""}`) },
    { label: "%", num: true, cls: (r) => dir(r.net_pct), render: (r) => pct(r.net_pct, 2) },
    { label: "Positions", num: true, render: (r) => r.trades }, { label: "", render: links },
    { label: "", render: (r) => h("button", { class: "linkish", title: "Build this report again from the broker export and compare", onclick: () => recheck(r.id, recheckBox) }, "recheck") },
  ], rows, { empty: "No report issued yet." }));

  // a PDF or CSV checked against the register; a CSV also gets its fingerprint recomputed
  const pick = h("input", { type: "file", accept: ".pdf,.csv,application/pdf,text/csv" });
  const verdict = h("div");
  pick.addEventListener("change", async () => {
    const f = pick.files[0];
    if (!f) return;
    clear(verdict, loading("Checking…"));
    const res = await fetch("/api/reports/verify", { method: "POST", headers: { "X-SD-Token": token, "Content-Type": "application/octet-stream" }, body: await f.arrayBuffer() });
    const v = await res.json();
    if (v.error) { clear(verdict, errorBox(v.error)); return; }
    const reg = v.registered;
    const lines = [];
    if (reg && (reg.pdf_sha === v.sha256 || reg.csv_sha === v.sha256)) lines.push(note(`Issued by this SessionDesk on ${stamp(reg.created)} as ${reg.id} (account ${reg.account}, ${reg.period_from} to ${reg.period_to}) - unchanged byte for byte.`, "up"));
    else lines.push(note(v.kind === "pdf" ? "This PDF is not in this SessionDesk's register: it was issued elsewhere or changed after issuing (any change alters the file's hash)." : "This file is not in this SessionDesk's register.", "warn"));
    if (v.csv) {
      lines.push(v.csv.error ? note(v.csv.error, "warn") : v.csv.ok
        ? note(`Fingerprint recomputed from the CSV matches the one it states (${v.csv.recomputed.slice(0, 16)}…): no number of the report data was changed.`, "up")
        : note(`Fingerprint does NOT match: the CSV states ${String(v.csv.stated).slice(0, 16)}…, its data gives ${v.csv.recomputed.slice(0, 16)}… - a figure was changed.`, "warn"));
    }
    const again = h("div");
    clear(verdict, lines, again, h("p", { class: "small muted" }, `SHA-256 of the file: ${v.sha256}`));
    if (reg) recheck(reg.id, again);                 // a registered report is also rebuilt from the broker data
  });
  clear(check, h("div", { class: "toolbar" }, pick), verdict);
  await load();
}
