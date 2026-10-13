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

export function bars(rows, { height = 160, fmt = (v) => v.toFixed(2) } = {}) {
  // Horizontal-free simple column chart for small series (e.g. Fed path).
  const W = 1000, H = height, pad = 24;
  const vals = rows.map((r) => r.value);
  const min = Math.min(0, ...vals), max = Math.max(0, ...vals) || 1;
  const bw = (W - pad * 2) / rows.length;
  const Y = (v) => pad + (1 - (v - min) / (max - min || 1)) * (H - pad * 2);
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", class: "chart-svg bars" });
  root.appendChild(svg("line", { x1: pad, x2: W - pad, y1: Y(0), y2: Y(0), class: "gridline" }));
  rows.forEach((r, i) => {
    const x = pad + i * bw + bw * 0.15, y0 = Y(0), y1 = Y(r.value);
    root.appendChild(svg("rect", { x, width: bw * 0.7, y: Math.min(y0, y1), height: Math.max(1, Math.abs(y1 - y0)), class: r.value >= 0 ? "bar up" : "bar down" }));
    root.appendChild(svg("text", { x: x + bw * 0.35, y: H - 6, class: "axis", "text-anchor": "middle" }, r.label));
    root.appendChild(svg("text", { x: x + bw * 0.35, y: Math.min(y0, y1) - 4, class: "axis", "text-anchor": "middle" }, fmt(r.value)));
  });
  return h("div", { class: "chart" }, root);
}
