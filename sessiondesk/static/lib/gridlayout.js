// Free tile grid for My desk: every tile sits at x/y with a width and height in grid cells (24 columns, rows of a
// fixed height). Dragging or resizing one tile pushes the others out of its way and everything floats up, so the
// grid never has holes (the behaviour of Bloomberg's Launchpad and react-grid-layout). Pure functions; the desk view
// does the DOM and the mouse.
export const COLS = 24;

export const overlap = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

// Layouts saved before the free grid had only a width out of 12 and flowed left to right: give every tile a place.
export function normalize(tiles, defH) {
  if (tiles.every((t) => Number.isFinite(t.x) && Number.isFinite(t.y) && Number.isFinite(t.h))) return tiles.map((t) => ({ ...t }));
  let x = 0, y = 0, rowH = 0;
  return tiles.map((t) => {
    const w = Math.max(2, Math.min(COLS, (t.w || 4) * 2)), hh = defH(t.type);
    if (x + w > COLS) { x = 0; y += rowH; rowH = 0; }
    const out = { ...t, x, y, w, h: hh };
    x += w;
    rowH = Math.max(rowH, hh);
    return out;
  });
}

// Settle all tiles. `moving` is the index of the tile being dragged or resized: it keeps the spot it was dropped on
// and a tile under it gives way - unless the drop point is in that tile's lower half, then the dragged tile goes below.
export function arrange(tiles, moving = -1) {
  const out = tiles.map((t) => ({ ...t, w: Math.max(1, Math.min(COLS, t.w)), h: Math.max(1, t.h) }));
  out.forEach((t) => { t.x = Math.max(0, Math.min(COLS - t.w, Math.round(t.x))); t.y = Math.max(0, Math.round(t.y)); });
  const m = out[moving];
  const key = (i) => {
    const t = out[i];
    if (!m || i === moving) return t.y;
    return m.x < t.x + t.w && t.x < m.x + m.w ? t.y + t.h / 2 : t.y;
  };
  const order = out.map((_, i) => i).sort((a, b) => key(a) - key(b) || (a === moving ? -1 : b === moving ? 1 : out[a].x - out[b].x));
  const placed = [];
  for (const i of order) {
    const t = out[i];
    let hit;
    while ((hit = placed.find((p) => overlap(p, t)))) t.y = hit.y + hit.h;           // out of the way, downwards
    while (t.y > 0 && !placed.some((p) => overlap(p, { ...t, y: t.y - 1 }))) t.y--;  // then float up
    placed.push(t);
  }
  return out;
}

export const bottom = (tiles) => tiles.reduce((m, t) => Math.max(m, t.y + t.h), 0);
