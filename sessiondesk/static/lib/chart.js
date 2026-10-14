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
