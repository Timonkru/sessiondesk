// Small dependency-free SVG line chart with hover read-out. Enough for price history and curves;
// serious charting stays in the user's charting platform.
import { svg, h } from "./ui.js";

export function lineChart(points, { height = 260, ref = null, fmtY = (v) => v.toFixed(2), fmtX = (x) => x, xLabels = null, area = true } = {}) {
  const wrap = h("div", { class: "chart" });
  if (!points || points.length < 2) { wrap.appendChild(h("p", { class: "muted" }, "Not enough data for a chart.")); return wrap; }
  const W = 1000, H = height, padL = 8, padR = 64, padT = 10, padB = 22;
  const ys = points.map((p) => p.y);
  let min = Math.min(...ys, ref ?? Infinity), max = Math.max(...ys, ref ?? -Infinity);
  const pad = (max - min) * 0.06 || Math.abs(max) * 0.01 || 1;
  min -= pad; max += pad;
  const X = (i) => padL + (i / (points.length - 1)) * (W - padL - padR);
  const Y = (v) => padT + (1 - (v - min) / (max - min)) * (H - padT - padB);
  const up = ys[ys.length - 1] >= (ref ?? ys[0]);
  const cls = up ? "up" : "down";
  const line = points.map((p, i) => (i ? "L" : "M") + X(i).toFixed(1) + " " + Y(p.y).toFixed(1)).join(" ");
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", class: "chart-svg " + cls });
  // grid + y labels
  for (let k = 0; k <= 4; k++) {
    const v = min + ((max - min) * k) / 4, y = Y(v);
    root.appendChild(svg("line", { x1: padL, x2: W - padR, y1: y, y2: y, class: "gridline" }));
    root.appendChild(svg("text", { x: W - padR + 6, y: y + 4, class: "axis" }, fmtY(v)));
  }
  // x labels
  const n = 5;
  for (let k = 0; k < n; k++) {
    const i = Math.round((k / (n - 1)) * (points.length - 1));
    const label = xLabels ? xLabels(points[i].x) : fmtX(points[i].x);
    root.appendChild(svg("text", { x: X(i), y: H - 4, class: "axis", "text-anchor": k === 0 ? "start" : k === n - 1 ? "end" : "middle" }, label));
  }
  if (ref !== null && ref !== undefined) root.appendChild(svg("line", { x1: padL, x2: W - padR, y1: Y(ref), y2: Y(ref), class: "refline" }));
  if (area) root.appendChild(svg("path", { d: `${line} L${X(points.length - 1)} ${H - padB} L${X(0)} ${H - padB} Z`, class: "area" }));
  root.appendChild(svg("path", { d: line, class: "line" }));
  const cross = svg("line", { y1: padT, y2: H - padB, class: "cross", visibility: "hidden" });
  const dot = svg("circle", { r: 4, class: "dot", visibility: "hidden" });
  root.append(cross, dot);
  const tip = h("div", { class: "chart-tip", hidden: true });
  wrap.append(root, tip);
  root.addEventListener("mousemove", (e) => {
    const r = root.getBoundingClientRect();
    const fx = ((e.clientX - r.left) / r.width) * W;
    const i = Math.max(0, Math.min(points.length - 1, Math.round(((fx - padL) / (W - padL - padR)) * (points.length - 1))));
    const p = points[i];
    cross.setAttribute("x1", X(i)); cross.setAttribute("x2", X(i)); cross.setAttribute("visibility", "visible");
    dot.setAttribute("cx", X(i)); dot.setAttribute("cy", Y(p.y)); dot.setAttribute("visibility", "visible");
    tip.hidden = false;
    tip.textContent = `${fmtX(p.x)}   ${fmtY(p.y)}` + (ref ? `   ${((p.y / ref - 1) * 100).toFixed(2)}%` : "");
    tip.style.left = Math.min(r.width - 160, Math.max(0, ((X(i) / W) * r.width) - 70)) + "px";
  });
  root.addEventListener("mouseleave", () => { cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); tip.hidden = true; });
  return wrap;
}

export function bars(rows, { height = 150, fmt = (v) => v.toFixed(2) } = {}) {
  // HTML columns (crisp text at any width). Negative values hang below a zero line.
  rows = (rows || []).filter((r) => r.value !== null && r.value !== undefined && Number.isFinite(r.value));
  const wrap = h("div", { class: "bars", style: { height: height + "px" } });
  if (!rows.length) { wrap.appendChild(h("p", { class: "muted" }, "No data.")); return wrap; }
  const max = Math.max(0, ...rows.map((r) => r.value)), min = Math.min(0, ...rows.map((r) => r.value));
  const span = max - min || 1;
  const plot = height - 34;                                    // room for value + label text
  const zeroFromTop = (max / span) * plot;
  for (const r of rows) {
    const hgt = Math.max(1, (Math.abs(r.value) / span) * plot);
    const top = r.value >= 0 ? zeroFromTop - hgt : zeroFromTop;
    wrap.appendChild(h("div", { class: "barcol", title: `${r.label}: ${fmt(r.value)}` },
      h("div", { class: "barval", style: { top: Math.max(0, (r.value >= 0 ? top : top + hgt) - (r.value >= 0 ? 15 : -2)) + "px" } }, fmt(r.value)),
      h("div", { class: "bar " + (r.value >= 0 ? "up" : "down"), style: { top: top + "px", height: hgt + "px" } }),
      h("div", { class: "barlabel" }, r.label)));
  }
  wrap.appendChild(h("div", { class: "barzero", style: { top: zeroFromTop + "px" } }));
  return wrap;
}

// Candles from [{t, o, h, l, c, v}], volume underneath, 20/50-candle averages, hover read-out (OHLC + volume).
// More than maxBars bars are merged into wider candles (e.g. 5 years of days -> weekly-ish candles).
export function mergeBars(bars, maxBars = 320) {
  if (bars.length <= maxBars) return { bars, step: 1 };
  const step = Math.ceil(bars.length / maxBars), out = [];
  for (let i = 0; i < bars.length; i += step) {
    const g = bars.slice(i, i + step);
    out.push({ t: g[0].t, o: g[0].o, h: Math.max(...g.map((b) => b.h)), l: Math.min(...g.map((b) => b.l)), c: g[g.length - 1].c, v: g.reduce((s, b) => s + (b.v || 0), 0) });
  }
  return { bars: out, step };
}

export function sma(values, n) {
  let sum = 0;
  return values.map((v, i) => { sum += v; if (i >= n) sum -= values[i - n]; return i >= n - 1 ? sum / n : null; });
}

export function candleChart(rawBars, { height = 300, fmtY = (v) => v.toFixed(2), fmtX = (x) => x, averages = [20, 50] } = {}) {
  const wrap = h("div", { class: "chart" });
  const clean = (rawBars || []).filter((b) => [b.o, b.h, b.l, b.c].every((x) => x !== null && x !== undefined && Number.isFinite(x)));
  if (clean.length < 2) { wrap.appendChild(h("p", { class: "muted" }, "Not enough data for a chart.")); return wrap; }
  const { bars, step } = mergeBars(clean);
  const W = 1000, H = height, padL = 8, padR = 64, padT = 10, padB = 22;
  const hasVol = bars.some((b) => b.v > 0);
  const volH = hasVol ? Math.round((H - padT - padB) * 0.18) : 0;
  const priceBottom = H - padB - volH - (hasVol ? 6 : 0);
  let min = Math.min(...bars.map((b) => b.l)), max = Math.max(...bars.map((b) => b.h));
  const pad = (max - min) * 0.05 || Math.abs(max) * 0.01 || 1;
  min -= pad; max += pad;
  const slot = (W - padL - padR) / bars.length;
  const X = (i) => padL + slot * (i + 0.5);
  const Y = (v) => padT + (1 - (v - min) / (max - min)) * (priceBottom - padT);
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", class: "chart-svg candles" });
  for (let k = 0; k <= 4; k++) {
    const v = min + ((max - min) * k) / 4, y = Y(v);
    root.appendChild(svg("line", { x1: padL, x2: W - padR, y1: y, y2: y, class: "gridline" }));
    root.appendChild(svg("text", { x: W - padR + 6, y: y + 4, class: "axis" }, fmtY(v)));
  }
  for (let k = 0; k < 5; k++) {
    const i = Math.round((k / 4) * (bars.length - 1));
    root.appendChild(svg("text", { x: X(i), y: H - 4, class: "axis", "text-anchor": k === 0 ? "start" : k === 4 ? "end" : "middle" }, fmtX(bars[i].t)));
  }
  const bw = Math.max(1, slot * 0.7);
  const vmax = hasVol ? Math.max(...bars.map((b) => b.v || 0)) || 1 : 1;
  bars.forEach((b, i) => {
    const cls = b.c >= b.o ? "up" : "down";
    const g = svg("g", { class: "candle " + cls });
    g.appendChild(svg("line", { x1: X(i), x2: X(i), y1: Y(b.h), y2: Y(b.l), class: "wick" }));
    const top = Y(Math.max(b.o, b.c)), bot = Y(Math.min(b.o, b.c));
    g.appendChild(svg("rect", { x: X(i) - bw / 2, y: top, width: bw, height: Math.max(0.8, bot - top) }));
    if (hasVol) {
      const vh = ((b.v || 0) / vmax) * volH;
      g.appendChild(svg("rect", { x: X(i) - bw / 2, y: H - padB - vh, width: bw, height: Math.max(0, vh), class: "vol" }));
    }
    root.appendChild(g);
  });
  const closes = bars.map((b) => b.c);
  averages.forEach((n, k) => {
    const m = sma(closes, n);
    const d = m.map((v, i) => (v === null ? "" : (m[i - 1] === null || i === 0 ? "M" : "L") + X(i).toFixed(1) + " " + Y(v).toFixed(1))).join(" ");
    if (d.trim()) root.appendChild(svg("path", { d, class: "ma ma" + (k + 1) }));
  });
  const cross = svg("line", { y1: padT, y2: H - padB, class: "cross", visibility: "hidden" });
  root.appendChild(cross);
  const tip = h("div", { class: "chart-tip", hidden: true });
  const legend = h("div", { class: "small muted" }, averages.map((n, k) => h("span", { class: "malegend ma" + (k + 1) }, `── ${n}-candle average  `)),
    step > 1 ? `· each candle = ${step} source bars` : "");
  wrap.append(root, tip, legend);
  root.addEventListener("mousemove", (e) => {
    const r = root.getBoundingClientRect();
    const fx = ((e.clientX - r.left) / r.width) * W;
    const i = Math.max(0, Math.min(bars.length - 1, Math.floor((fx - padL) / slot)));
    const b = bars[i];
    cross.setAttribute("x1", X(i)); cross.setAttribute("x2", X(i)); cross.setAttribute("visibility", "visible");
    tip.hidden = false;
    tip.textContent = `${fmtX(b.t)}   O ${fmtY(b.o)}  H ${fmtY(b.h)}  L ${fmtY(b.l)}  C ${fmtY(b.c)}` + (hasVol ? `  V ${Math.round(b.v).toLocaleString()}` : "");
    tip.style.left = Math.min(r.width - 330, Math.max(0, ((X(i) / W) * r.width) - 120)) + "px";
  });
  root.addEventListener("mouseleave", () => { cross.setAttribute("visibility", "hidden"); tip.hidden = true; });
  return wrap;
}
