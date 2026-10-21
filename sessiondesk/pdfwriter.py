"""A small PDF writer for reports: A4 pages with text (Helvetica, WinAnsi), lines, filled boxes, polylines and a
translucent diagonal watermark. No dependency - the PDF is written by hand (PDF 1.4 objects, uncompressed).
Coordinates are in points from the TOP-left corner, as on screen; they are flipped when written.
"""
from __future__ import annotations

import math

A4 = (595.28, 841.89)

# Helvetica / Helvetica-Bold advance widths (1/1000 em) for ASCII 32..126 (Adobe AFM); other characters count 556
_HELV = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278] + [556] * 10 + [
    278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722,
    667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222,
    833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]
_HELV_B = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278] + [556] * 10 + [
    333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722,
    667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278,
    889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584]


def text_width(s: str, size: float, bold: bool = False) -> float:
    table = _HELV_B if bold else _HELV
    return sum(table[ord(c) - 32] if 32 <= ord(c) <= 126 else 556 for c in s) * size / 1000


def _esc(s: str) -> bytes:
    raw = s.encode("cp1252", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)").replace(b"\r", b"").replace(b"\n", b" ")


def _rgb(c) -> str:
    return " ".join(f"{v:.3f}" for v in c)


class PDF:
    def __init__(self, size=A4, title: str = "", author: str = "", subject: str = ""):
        self.w, self.h = size
        self.pages: list[list[bytes]] = []
        self.current = -1                               # page that drawing goes to (goto() returns to an earlier one)
        self.info = {"Title": title, "Author": author, "Subject": subject, "Producer": "SessionDesk"}

    # ---------------------------------------------------------------- drawing
    def add_page(self) -> None:
        self.pages.append([])
        self.current = len(self.pages) - 1

    def goto(self, index: int) -> None:
        self.current = index

    def _put(self, op: str | bytes) -> None:
        self.pages[self.current].append(op.encode("latin-1") if isinstance(op, str) else op)

    def text(self, x: float, y: float, s: str, size: float = 9, bold: bool = False, color=(0, 0, 0), align: str = "left") -> None:
        """y is the baseline, measured from the top of the page."""
        s = str(s)
        if align != "left":
            w = text_width(s, size, bold)
            x -= w if align == "right" else w / 2
        self._put(f"BT /{'F2' if bold else 'F1'} {size:.2f} Tf {_rgb(color)} rg {x:.2f} {self.h - y:.2f} Td (".encode("latin-1")
                  + _esc(s) + b") Tj ET")

    def line(self, x1, y1, x2, y2, width: float = 0.5, color=(0, 0, 0)) -> None:
        self._put(f"{width:.2f} w {_rgb(color)} RG {x1:.2f} {self.h - y1:.2f} m {x2:.2f} {self.h - y2:.2f} l S")

    def rect(self, x, y, w, h, fill=None, stroke=None, width: float = 0.5) -> None:
        if fill is None and stroke is None:
            return
        ops = (f"{_rgb(fill)} rg " if fill else "") + (f"{_rgb(stroke)} RG {width:.2f} w " if stroke else "")
        ops += f"{x:.2f} {self.h - y - h:.2f} {w:.2f} {h:.2f} re " + ("B" if fill and stroke else "f" if fill else "S")
        self._put(ops)

    def polyline(self, pts: list[tuple[float, float]], width: float = 1, color=(0, 0, 0)) -> None:
        if len(pts) < 2:
            return
        path = " ".join(f"{x:.2f} {self.h - y:.2f} {'m' if i == 0 else 'l'}" for i, (x, y) in enumerate(pts))
        self._put(f"{width:.2f} w {_rgb(color)} RG 1 J 1 j {path} S")

    def watermark(self, s: str, size: float = 30, color=(0.55, 0.55, 0.55)) -> None:
        """Diagonal text across the page, drawn translucent (ExtGState /GS1)."""
        a = math.atan2(self.h, self.w)
        c, sn = math.cos(a), math.sin(a)
        w = text_width(s, size, True)
        x, y = self.w / 2 - c * w / 2, self.h / 2 - sn * w / 2       # centred along the diagonal, PDF coordinates
        self._put(f"q /GS1 gs BT /F2 {size:.2f} Tf {_rgb(color)} rg {c:.4f} {sn:.4f} {-sn:.4f} {c:.4f} {x:.2f} {y:.2f} Tm (".encode("latin-1")
                  + _esc(s) + b") Tj ET Q")

    # ---------------------------------------------------------------- output
    def output(self) -> bytes:
        objs: list[bytes] = []                          # object n = objs[n - 1]

        def add(body: bytes) -> int:
            objs.append(body)
            return len(objs)
        f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        f2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        gs = add(b"<< /Type /ExtGState /ca 0.12 /CA 0.12 >>")
        pages_id = len(objs) + 1 + 2 * len(self.pages)    # the Pages object comes after all page + content objects
        kids = []
        for ops in self.pages:
            stream = b"\n".join(ops)
            content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
            kids.append(add((f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {self.w:.2f} {self.h:.2f}] "
                             f"/Resources << /Font << /F1 {f1} 0 R /F2 {f2} 0 R >> /ExtGState << /GS1 {gs} 0 R >> >> "
                             f"/Contents {content} 0 R >>").encode("latin-1")))
        add(f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode("latin-1"))
        info = add(b"<< " + b" ".join(b"/" + k.encode() + b" (" + _esc(v) + b")" for k, v in self.info.items() if v) + b" >>")
        catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("latin-1"))
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, body in enumerate(objs, 1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
        out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
        out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, catalog, info, xref)
        return bytes(out)
