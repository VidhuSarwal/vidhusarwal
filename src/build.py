#!/usr/bin/env python3
"""
Builds every SVG in ../assets from this one file.

    pip install -r src/requirements.txt
    python3 src/build.py

Text is converted to outlines at build time, so the images carry no fonts
and render the same in every browser. GitHub serves repo SVGs with
`default-src 'none'`, which would block an embedded @font-face anyway.

Fonts (both OFL) are downloaded once into src/.fonts/.
"""

import pathlib
import urllib.request

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONT_DIR = ROOT / "src" / ".fonts"

FONT_URLS = {
    "SpaceGrotesk.ttf": "https://github.com/google/fonts/raw/main/ofl/spacegrotesk/SpaceGrotesk%5Bwght%5D.ttf",
    "JetBrainsMono.ttf": "https://github.com/google/fonts/raw/main/ofl/jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf",
}

# Same token pairs as vidhux.dev, so the README and the site read as one thing.
THEMES = {
    "dark": {
        "ink": "#F4F4F2",
        "sec": "#8A8A88",
        "ter": "#5C5C59",
        "hair": "rgba(255,255,255,0.07)",
        "rule": "rgba(255,255,255,0.13)",
        "accent": "#C8E4FF",
        "accent_fill": "rgba(200,228,255,0.07)",
        "accent_line": "rgba(200,228,255,0.45)",
        "panel": "rgba(255,255,255,0.018)",
    },
    "light": {
        "ink": "#1C1A17",
        "sec": "#6B6865",
        "ter": "#A3A09A",
        "hair": "rgba(0,0,0,0.08)",
        "rule": "rgba(0,0,0,0.14)",
        "accent": "#2C5282",
        "accent_fill": "rgba(44,82,130,0.06)",
        "accent_line": "rgba(44,82,130,0.45)",
        "panel": "rgba(0,0,0,0.018)",
    },
}


# ── fonts ────────────────────────────────────────────────────────────────────

def font_path(name):
    path = FONT_DIR / name
    if not path.exists():
        FONT_DIR.mkdir(parents=True, exist_ok=True)
        print(f"downloading {name}")
        urllib.request.urlretrieve(FONT_URLS[name], path)
    return path


class Face:
    """One weight of a variable font: shapes text and hands out glyph outlines."""

    def __init__(self, key, file, weight, features):
        path = font_path(file)
        self.key = key
        self.features = features
        self.tt = TTFont(path)
        self.upem = self.tt["head"].unitsPerEm
        self.order = self.tt.getGlyphOrder()
        self.glyphs = self.tt.getGlyphSet(location={"wght": weight})
        self.hb = hb.Font(hb.Face(hb.Blob.from_file_path(str(path))))
        self.hb.set_variations({"wght": weight})

    def shape(self, text):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hb, buf, self.features)
        out = []
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            if info.codepoint == 0:
                raise ValueError(f"{self.key}: no glyph for a character in {text!r}")
            out.append((self.order[info.codepoint], pos.x_advance, pos.x_offset, pos.y_offset))
        return out

    def outline(self, name):
        pen = SVGPathPen(self.glyphs, ntos=lambda v: str(round(v)))
        self.glyphs[name].draw(pen)
        return pen.getCommands()

    def width(self, text, size, ls=0):
        glyphs = self.shape(text)
        units = sum(adv for _, adv, _, _ in glyphs)
        return units * size / self.upem + ls * (len(glyphs) - 1)


NO_LIGATURES = {"liga": False, "calt": False, "dlig": False}

FACES = {}


def face(key):
    if not FACES:
        FACES["display"] = Face("display", "SpaceGrotesk.ttf", 500, {"kern": True, **NO_LIGATURES})
        FACES["display-bold"] = Face("display-bold", "SpaceGrotesk.ttf", 700, {"kern": True, **NO_LIGATURES})
        FACES["body"] = Face("body", "SpaceGrotesk.ttf", 400, {"kern": True, **NO_LIGATURES})
        FACES["mono"] = Face("mono", "JetBrainsMono.ttf", 400, NO_LIGATURES)
    return FACES[key]


# ── svg document ─────────────────────────────────────────────────────────────

class Svg:
    def __init__(self, width, height, title):
        self.w = width
        self.h = height
        self.title = title
        self.defs = {}
        self.body = []
        self.css = []

    def add(self, *parts):
        self.body.extend(parts)

    def glyph(self, fc, name):
        gid = f"{fc.key[0]}{fc.key[-1]}{fc.order.index(name)}"
        if gid not in self.defs:
            self.defs[gid] = fc.outline(name)
        return gid

    def text(self, x, y, s, key, size, fill, anchor="start", ls=0, attrs=""):
        """Lay out `s` as outlined glyphs. Returns (svg, width_px)."""
        fc = face(key)
        k = size / fc.upem
        ls_units = ls / k
        glyphs = fc.shape(s)
        width = fc.width(s, size, ls)
        if anchor == "middle":
            x -= width / 2
        elif anchor == "end":
            x -= width
        uses = []
        pen = 0.0
        for name, adv, xo, yo in glyphs:
            if self.glyphs_has_ink(fc, name):
                gid = self.glyph(fc, name)
                y_attr = f' y="{yo}"' if yo else ""
                uses.append(f'<use href="#{gid}" x="{pen + xo:.0f}"{y_attr}/>')
            pen += adv + ls_units
        svg = (f'<g transform="translate({x:.2f} {y:.2f}) scale({k:.5f} {-k:.5f})" '
               f'fill="{fill}"{attrs}>{"".join(uses)}</g>')
        return svg, width

    @staticmethod
    def glyphs_has_ink(fc, name):
        return bool(fc.outline(name))

    def render(self):
        defs = "".join(f'<path id="{k}" d="{d}"/>' for k, d in self.defs.items())
        style = f"<style>{''.join(self.css)}</style>" if self.css else ""
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
                f'viewBox="0 0 {self.w} {self.h}" role="img" aria-label="{self.title}">'
                f"<title>{self.title}</title>{style}<defs>{defs}</defs>"
                f'{"".join(self.body)}</svg>\n')


def brackets(x, y, w, h, arm, color, width=1.5):
    """The VX corner brackets from vidhux.dev."""
    x2, y2 = x + w, y + h
    d = (f"M{x} {y + arm}V{y}H{x + arm}"
         f"M{x2 - arm} {y}H{x2}V{y + arm}"
         f"M{x} {y2 - arm}V{y2}H{x + arm}"
         f"M{x2 - arm} {y2}H{x2}V{y2 - arm}")
    return (f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" '
            f'stroke-linecap="square"/>')


# ── I²C waveform ─────────────────────────────────────────────────────────────

def i2c_capture(addr, payload):
    """
    Slot-by-slot model of one I²C write: START, address+W, ACK, data bytes
    each followed by ACK, STOP. Returns edge lists for SCL and SDA (as
    (slot_position, level) pairs) plus the decoded frames.
    """
    scl = [(0.0, 1)]
    sda = [(0.0, 1)]
    frames = []

    slot = 1                       # slot 0 is idle lead-in
    sda.append((slot + 0.30, 0))   # START: SDA falls while SCL is high
    scl.append((slot + 0.70, 0))
    slot += 1

    for i, byte in enumerate([addr << 1] + list(payload)):
        first = slot
        for bit in range(7, -1, -1):
            sda.append((slot + 0.18, (byte >> bit) & 1))
            scl.append((slot + 0.50, 1))
            scl.append((slot + 1.00, 0))
            slot += 1
        sda.append((slot + 0.18, 0))   # ACK from the target
        scl.append((slot + 0.50, 1))
        scl.append((slot + 1.00, 0))
        frames.append({"first": first, "ack": slot, "byte": byte, "addr": i == 0})
        slot += 1

    stop = slot
    sda.append((slot + 0.18, 0))
    scl.append((slot + 0.45, 1))
    sda.append((slot + 0.75, 1))       # STOP: SDA rises while SCL is high
    slot += 2                          # idle tail
    return scl, sda, frames, stop, slot


def trace_path(edges, x0, step, y_hi, y_lo, end, rise=1.4):
    level_y = {1: y_hi, 0: y_lo}
    level = edges[0][1]
    d = [f"M{x0:.1f} {level_y[level]}"]
    for pos, new in edges[1:]:
        if new == level:
            continue
        x = x0 + pos * step
        d.append(f"H{x - rise / 2:.1f}L{x + rise / 2:.1f} {level_y[new]}")
        level = new
    d.append(f"H{x0 + end * step:.1f}")
    return "".join(d)


def bus_shape(xa, xb, yc, h):
    """Timing-diagram bus segment: a long hexagon."""
    n = h / 2
    return (f"M{xa:.1f} {yc}L{xa + n:.1f} {yc - n}H{xb - n:.1f}L{xb:.1f} {yc}"
            f"L{xb - n:.1f} {yc + n}H{xa + n:.1f}Z")


# ── hero ─────────────────────────────────────────────────────────────────────

HERO_CSS = """
.sweep{transform-origin:{X0}px 0;animation:sweep {DUR}s linear {T0}s both}
.cursor{animation:cursor {DUR}s linear {T0}s both}
.pop{animation:pop .3s ease-out both}
.acq{animation:acq {ACQ}s steps(1) both}
.done{animation:pop .3s ease-out {DONE}s both}
.led{animation:led 2.8s ease-in-out {DONE}s infinite}
@keyframes sweep{from{transform:scaleX(0)}to{transform:scaleX(1)}}
@keyframes cursor{from{transform:translateX(0);opacity:1}97%{opacity:1}to{transform:translateX({SPAN}px);opacity:0}}
@keyframes pop{from{opacity:0}to{opacity:1}}
@keyframes acq{0%,24%,48%,72%{opacity:1}12%,36%,60%,84%,100%{opacity:0}}
@keyframes led{0%,100%{opacity:1}50%{opacity:.3}}
@media (prefers-reduced-motion:reduce){*{animation:none!important}}
"""


def hero(t):
    W, H = 900, 424
    svg = Svg(W, H, "Vidhu Sarwal. Systems engineer: Linux kernel, embedded, distributed systems. "
                    "Figure: an I2C write to address 0x10, decoded as the bytes h-e-l-l-o.")
    add = svg.add
    M = 32                                     # outer margin

    add(f'<rect x="1.5" y="1.5" width="{W - 3}" height="{H - 3}" fill="none" stroke="{t["hair"]}"/>')
    add(brackets(1.5, 1.5, W - 3, H - 3, 28, t["sec"]))

    # top bar
    g, _ = svg.text(M, 44, "VX.", "display-bold", 19, t["ink"], ls=-0.5)
    add(g)
    g, w_bar = svg.text(W - M, 43, "FINAL-YEAR CS  ·  LKMP '26  ·  GSOC '25  ·  SAMSUNG RESEARCH '25  ·  "
                        "QUALCOMM HACKATHON WINNER '26", "mono", 10.5, t["sec"], anchor="end", ls=1.1)
    assert w_bar < W - 2 * M - 70, f"top bar too wide: {w_bar:.0f}px"
    add(g)
    add(f'<path d="M{M} 62H{W - M}" stroke="{t["hair"]}"/>')

    # name, with the accent full stop that ends every VX mark
    g, w_name = svg.text(M - 4, 162, "Vidhu Sarwal", "display", 94, t["ink"], ls=-3.2)
    add(g)
    g, _ = svg.text(M - 4 + w_name - 1, 162, ".", "display", 94, t["accent"], attrs=' class="led"')
    add(g)

    g, _ = svg.text(M - 1, 206, "Systems engineer. Linux kernel, embedded, distributed systems.",
                    "body", 23, t["sec"], ls=-0.2)
    add(g)

    # figure: logic-analyser capture
    FX, FY, FW, FH = M, 236, W - 2 * M, 134
    add(f'<rect x="{FX}" y="{FY}" width="{FW}" height="{FH}" fill="{t["panel"]}" stroke="{t["hair"]}"/>')

    scl, sda, frames, stop, slots = i2c_capture(0x10, b"hello")
    X0, X1 = FX + 66, FX + FW - 16
    step = (X1 - X0) / slots
    y_scl, y_sda, y_dec = (270, 290), (312, 332), 352

    for label, y in (("SCL", y_scl[0] + 14), ("SDA", y_sda[0] + 14)):
        g, _ = svg.text(FX + 16, y, label, "mono", 10.5, t["ter"], ls=1)
        add(g)

    # time ruler: a tick per bit, a longer tick per frame
    ticks = []
    for s in range(slots + 1):
        major = any(s == f["first"] for f in frames) or s in (1, stop)
        ticks.append(f"M{X0 + s * step:.1f} {FY}v{6 if major else 3}")
    add(f'<path d="{"".join(ticks)}" stroke="{t["rule"]}"/>')

    # trigger flag on the START condition
    tx = X0 + 1.30 * step
    add(f'<path d="M{tx - 4:.1f} {FY - 7}h8l-4 6z" fill="{t["accent"]}"/>')

    duration, start = 2.6, 0.35
    span = X1 - X0
    svg.css.append(HERO_CSS
                   .replace("{X0}", f"{X0:.1f}").replace("{DUR}", str(duration))
                   .replace("{T0}", str(start)).replace("{SPAN}", f"{span:.1f}")
                   .replace("{ACQ}", f"{start + duration:.2f}")
                   .replace("{DONE}", f"{start + duration:.2f}"))

    add(f'<clipPath id="acq"><rect class="sweep" x="{X0 - 2:.1f}" y="{FY}" '
        f'width="{span + 4:.1f}" height="{FH}"/></clipPath>')
    add(f'<g clip-path="url(#acq)" fill="none" stroke-width="1.5" stroke-linejoin="round">')
    add(f'<path d="{trace_path(scl, X0, step, *y_scl, slots)}" stroke="{t["sec"]}"/>')
    add(f'<path d="{trace_path(sda, X0, step, *y_sda, slots)}" stroke="{t["accent"]}"/>')
    add("</g>")

    def delay_at(x):
        return start + duration * (x - X0) / span

    # decoded frames
    for f in frames:
        xa = X0 + (f["first"] + 0.18) * step
        xb = X0 + (f["ack"] + 0.18) * step
        mid = (xa + xb) / 2
        style = f' class="pop" style="animation-delay:{delay_at(xb):.2f}s"'
        add(f'<g{style}>')
        add(f'<path d="{bus_shape(xa, xb - 1.5, y_dec, 17)}" fill="{t["accent_fill"]}" '
            f'stroke="{t["accent_line"]}"/>')
        if f["addr"]:
            g, _ = svg.text(mid, y_dec + 3.8, "0x10 W", "mono", 10.5, t["sec"], anchor="middle")
            add(g)
        else:
            hexs = f"0x{f['byte']:02X} "
            ch = f"'{chr(f['byte'])}'"
            wh = face("mono").width(hexs, 10.5)
            wc = face("mono").width(ch, 11.5)
            left = mid - (wh + wc) / 2
            g, _ = svg.text(left, y_dec + 3.8, hexs, "mono", 10.5, t["ter"])
            add(g)
            g, _ = svg.text(left + wh, y_dec + 3.9, ch, "mono", 11.5, t["ink"])
            add(g)
        ax = X0 + (f["ack"] + 0.5) * step
        g, _ = svg.text(ax, y_dec + 3.8, "A", "mono", 9, t["ter"], anchor="middle")
        add(g)
        add("</g>")

    for pos, ch in ((1.5, "S"), (stop + 0.5, "P")):
        x = X0 + pos * step
        g, _ = svg.text(x, y_dec + 3.8, ch, "mono", 9.5, t["accent"], anchor="middle",
                        attrs=f' class="pop" style="animation-delay:{delay_at(x):.2f}s"')
        add(g)

    # sweep cursor and run/stop status
    add(f'<path class="cursor" d="M{X0:.1f} {FY + 8}V{FY + FH - 6}" stroke="{t["accent"]}" '
        f'stroke-width="1" opacity="0"/>')
    g, _ = svg.text(FX + FW - 14, FY + 20, "● ACQUIRING", "mono", 9.5, t["accent"], anchor="end",
                    ls=1.2, attrs=' class="acq" opacity="0"')
    add(g)
    g, _ = svg.text(FX + FW - 14, FY + 20, "STOP · 400 kHz · 7-BIT", "mono", 9.5, t["ter"],
                    anchor="end", ls=1.2, attrs=' class="done"')
    add(g)

    # caption
    g, _ = svg.text(M, 398, "FIG. 1  ·  I²C WRITE TO 0x10, DECODED", "mono", 10.5, t["ter"], ls=1.6)
    add(g)
    g, _ = svg.text(W - M, 398, "30.7333°N  76.7794°E", "mono", 10.5, t["ter"], anchor="end", ls=1.6)
    add(g)
    return svg


# ── section headers ──────────────────────────────────────────────────────────

SECTIONS = [
    ("now", "01", "Now", "what's on the bench"),
    ("upstream", "02", "Upstream", "patches to mainline linux"),
    ("work", "03", "Work", "selected projects"),
    ("experience", "04", "Experience", "revision history"),
    ("wins", "05", "Wins", "competitions"),
    ("toolchain", "06", "Toolchain", "what I reach for"),
]


def section(t, index, title, caption):
    W, H = 900, 64
    svg = Svg(W, H, f"{index} {title}")
    base = 44
    # index sits top-aligned with the title's cap height, like a footnote mark
    g, w_idx = svg.text(0, base - 17, index, "mono", 13, t["accent"], ls=1)
    svg.add(g)
    x_title = w_idx + 10
    g, w_title = svg.text(x_title, base, title, "display", 37, t["ink"], ls=-0.9)
    svg.add(g)
    cap, w_cap = svg.text(W, base, caption.upper(), "mono", 11, t["ter"], anchor="end", ls=1.8)
    svg.add(cap)
    rule_y = base - 4.5
    x_from, x_to = x_title + w_title + 18, W - w_cap - 18
    svg.add(f'<path d="M{x_from:.1f} {rule_y}H{x_to:.1f}" stroke="{t["rule"]}"/>')
    svg.add(f'<path d="M{x_to:.1f} {rule_y - 3}v6" stroke="{t["rule"]}"/>')
    return svg


# ── footer ───────────────────────────────────────────────────────────────────

def footer(t):
    W, H = 900, 104
    svg = Svg(W, H, "hardware, linux, distributed systems, llms. VX. Works.")
    svg.add(f'<path d="M0 1.5H{W}" stroke="{t["hair"]}"/>')
    g, _ = svg.text(W / 2, 48, "hardware  →  linux  →  distributed systems  →  llms", "mono", 13,
                    t["sec"], anchor="middle", ls=0.4)
    svg.add(g)
    g, _ = svg.text(0, 92, "EOF", "mono", 10.5, t["ter"], ls=1.6)
    svg.add(g)
    g, w_vx = svg.text(W / 2, 92, "VX.", "display-bold", 15, t["ink"], anchor="middle", ls=-0.4)
    svg.add(g)
    g, _ = svg.text(W, 92, "SYS · NOMINAL", "mono", 10.5, t["ter"], anchor="end", ls=1.6)
    svg.add(g)
    return svg


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    ASSETS.mkdir(exist_ok=True)
    total = 0
    for theme, palette in THEMES.items():
        outputs = {"hero": hero(palette), "footer": footer(palette)}
        for key, index, title, caption in SECTIONS:
            outputs[f"s-{key}"] = section(palette, index, title, caption)
        for name, svg in outputs.items():
            path = ASSETS / f"{name}-{theme}.svg"
            data = svg.render()
            path.write_text(data)
            total += len(data)
            print(f"{path.relative_to(ROOT)}  {len(data) / 1024:.1f} KB")
    print(f"total {total / 1024:.1f} KB (both themes)")


if __name__ == "__main__":
    main()
