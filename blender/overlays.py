#!/usr/bin/env python3
"""2D UI overlay renderer for the Baby Sim Blender proof-of-concept.

Recreates the HTML/CSS overlay of ../baby-sim.html (title card, chapter pill,
"Design your baby" panel, speech bubble, response options, "You said" pill,
feedback panel with development check-in, rewind + reflect cards and the
scripted cursor) as straight-alpha RGBA PNG frames at 1280x720 / 24 fps.

    python3 blender/overlays.py [--start F] [--end F] [--every N] [--jobs J]

Frame f (1-based) shows video time g = (f-1)/24 s; story time t = g - INTRO.
Output: blender/overlay_frames/0001.png ... 1524.png
Only Pillow is required.
"""
import argparse
import math
import os
import re
import sys
import time
from functools import lru_cache
from multiprocessing import Pool

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

# ------------------------------------------------------------------ timing
W, H = 1280, 720
FPS = 24
INTRO = 23.5
DURATION = INTRO + 40
NFRAMES = int(round(DURATION * FPS))          # 1524
FADE = 0.45
# In baby-sim.html `round2 = t > 20`, which would swap the round-1 feedback
# panel to round-2 content (and hide the retry button the cursor clicks at
# t=22.3) while it is still on screen. We switch after the panel has faded out.
ROUND2_AT = 23.1

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, 'overlay_frames')


def clamp(x, a=0.0, b=1.0):
    return min(b, max(a, x))


def lerp(a, b, k):
    return a + (b - a) * k


def smooth(a, b, t):
    k = clamp((t - a) / (b - a))
    return k * k * (3 - 2 * k)


def within(t, a, b):
    return a <= t < b


def trans(fn, t, d, n=12):
    """Approximates a CSS transition of duration d on boolean state fn(t)."""
    if d <= 0:
        return 1.0 if fn(t) else 0.0
    s = sum(1.0 for j in range(n) if fn(t - d * j / (n - 1))) / n
    return s * s * (3 - 2 * s)


def bezier(x1, y1, x2, y2):
    def f(x):
        if x <= 0: return 0.0
        if x >= 1: return 1.0
        lo, hi = 0.0, 1.0
        for _ in range(30):
            s = (lo + hi) / 2
            bx = 3 * (1 - s) ** 2 * s * x1 + 3 * (1 - s) * s * s * x2 + s ** 3
            if bx < x: lo = s
            else: hi = s
        s = (lo + hi) / 2
        return 3 * (1 - s) ** 2 * s * y1 + 3 * (1 - s) * s * s * y2 + s ** 3
    return f


STRIP_EASE = bezier(.3, 1.35, .5, 1)
EASE_OUT = bezier(0, 0, .58, 1)

# ------------------------------------------------------------------ colors
def hexc(h, a=255):
    h = h.lstrip('#')
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


def mix(c1, c2, k):
    return tuple(int(round(lerp(a, b, k))) for a, b in zip(c1, c2))


INK = hexc('#3b2a2f'); MUTED = hexc('#7a666b'); ACCENT = hexc('#d6385a')
PANEL = (255, 252, 250, int(round(0.94 * 255)))
CHIP = hexc('#e9e6ff'); CHIPLINE = hexc('#c9c3f5')
GOOD = hexc('#5bbf8a'); BAD = hexc('#e2677f')
WHITE = (255, 255, 255, 255)
SHADOW_RGB = (80, 40, 50)

# ------------------------------------------------------------------ fonts
FONT_FILES = {
    'sans': ['/System/Library/Fonts/SFNS.ttf', '/System/Library/Fonts/HelveticaNeue.ttc',
             '/System/Library/Fonts/Helvetica.ttc', '/Library/Fonts/Arial Unicode.ttf'],
    'sansi': ['/System/Library/Fonts/SFNSItalic.ttf', '/System/Library/Fonts/HelveticaNeue.ttc',
              '/System/Library/Fonts/SFNS.ttf'],
    'serif': ['/System/Library/Fonts/Supplemental/Georgia.ttf', '/Library/Fonts/Georgia.ttf',
              '/System/Library/Fonts/Times.ttc'],
}
FALLBACK_FILES = ['/System/Library/Fonts/SFNS.ttf', '/Library/Fonts/Arial Unicode.ttf',
                  '/System/Library/Fonts/Menlo.ttc', '/System/Library/Fonts/Apple Symbols.ttf']
EMOJI_FILE = '/System/Library/Fonts/Apple Color Emoji.ttc'
PPU = 2   # every UI sprite is drawn at 2x CSS px


def _open(path, px, weight, italic):
    f = ImageFont.truetype(path, px)
    try:
        axes = f.get_variation_axes()
        vals = []
        for ax in axes:
            n = ax['name'].decode() if isinstance(ax['name'], bytes) else ax['name']
            if n == 'Weight': vals.append(weight)
            elif n == 'Optical Size': vals.append(clamp(px / PPU, ax['minimum'], ax['maximum']))
            else: vals.append(ax['default'])
        f.set_variation_by_axes(vals)
    except Exception:
        pass
    return f


@lru_cache(maxsize=None)
def font(fam, size, weight=400):
    px = int(round(size * PPU))
    for p in FONT_FILES[fam]:
        if os.path.exists(p):
            try:
                if p.endswith('HelveticaNeue.ttc'):
                    idx = 1 if weight >= 600 else 0
                    return ImageFont.truetype(p, px, index=idx)
                return _open(p, px, weight, fam == 'sansi')
            except Exception:
                continue
    return ImageFont.load_default(px)


@lru_cache(maxsize=None)
def fallback_font(i, size, weight):
    return _open(FALLBACK_FILES[i], int(round(size * PPU)), weight, False)


def _glyph_sig(f, ch):
    im = Image.new('L', (int(f.size * 1.6) + 4, int(f.size * 1.6) + 4))
    ImageDraw.Draw(im).text((2, 2), ch, font=f, fill=255)
    return im.tobytes()


@lru_cache(maxsize=None)
def has_glyph(fkey, ch):
    fam, size, weight, fb = fkey
    f = font(fam, 20, weight) if fb < 0 else fallback_font(fb, 20, weight)
    if ch.isspace():
        return True
    return _glyph_sig(f, ch) != _glyph_sig(f, '￿')


def runs(s, fam, size, weight):
    """Split s into (text, fontobj) runs with per-glyph fallback."""
    out = []
    for ch in s:
        f = None
        if has_glyph((fam, size, weight, -1), ch):
            f = font(fam, size, weight)
        else:
            for i, p in enumerate(FALLBACK_FILES):
                if os.path.exists(p) and has_glyph((fam, size, weight, i), ch):
                    f = fallback_font(i, size, weight)
                    break
            if f is None:
                f = font(fam, size, weight)
        if out and out[-1][1] is f:
            out[-1][0] += ch
        else:
            out.append([ch, f])
    return out


class FK:
    """Font key: family, CSS px size, weight, letter spacing (px)."""
    def __init__(self, fam='sans', size=16, weight=400, ls=0.0):
        self.fam, self.size, self.weight, self.ls = fam, size, weight, ls

    @property
    def f(self):
        return font(self.fam, self.size, self.weight)

    def width(self, s):
        return text_width(s, self.fam, self.size, self.weight, self.ls)

    def metrics(self):
        a, d = self.f.getmetrics()
        return a / PPU, d / PPU


@lru_cache(maxsize=4096)
def text_width(s, fam, size, weight, ls):
    if fam == 'emoji':
        return size * 1.2 * len(s)
    w = 0.0
    for txt, f in runs(s, fam, size, weight):
        if ls:
            for ch in txt:
                w += f.getlength(ch) / PPU + ls
        else:
            w += f.getlength(txt) / PPU
    return w


@lru_cache(maxsize=64)
def emoji_img(ch, px):
    f = ImageFont.truetype(EMOJI_FILE, 160)
    im = Image.new('RGBA', (200, 200), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((10, 10), ch, font=f, embedded_color=True)
    bb = im.getbbox()
    im = im.crop(bb) if bb else im
    return im.convert('RGBa').resize((px, px), Image.LANCZOS).convert('RGBA')


# ------------------------------------------------------------------ svg-ish paths
_TOK = re.compile(r'[MmLlHhVvCcQqZz]|-?\d*\.?\d+(?:e-?\d+)?')


def parse_path(d):
    toks = _TOK.findall(d)
    i = 0; cmd = None; cx = cy = 0.0; sx = sy = 0.0
    subs = []; cur = []

    def num():
        nonlocal i
        v = float(toks[i]); i += 1; return v
    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i]; i += 1
            if cmd in 'Zz':
                if cur: subs.append((cur, True)); cur = []
                cx, cy = sx, sy
                continue
        rel = cmd.islower(); c = cmd.upper()
        ox, oy = (cx, cy) if rel else (0.0, 0.0)
        if c == 'M':
            if cur: subs.append((cur, False))
            cx, cy = ox + num(), oy + num(); sx, sy = cx, cy; cur = [(cx, cy)]
            cmd = 'l' if rel else 'L'
        elif c == 'L':
            cx, cy = ox + num(), oy + num(); cur.append((cx, cy))
        elif c == 'H':
            cx = ox + num(); cur.append((cx, cy))
        elif c == 'V':
            cy = oy + num(); cur.append((cx, cy))
        elif c == 'C':
            x1, y1, x2, y2, x3, y3 = [v + o for v, o in zip([num() for _ in range(6)], [ox, oy] * 3)]
            p0 = (cx, cy)
            for k in range(1, 17):
                s = k / 16
                cur.append(((1 - s) ** 3 * p0[0] + 3 * (1 - s) ** 2 * s * x1 + 3 * (1 - s) * s * s * x2 + s ** 3 * x3,
                            (1 - s) ** 3 * p0[1] + 3 * (1 - s) ** 2 * s * y1 + 3 * (1 - s) * s * s * y2 + s ** 3 * y3))
            cx, cy = x3, y3
        elif c == 'Q':
            x1, y1, x2, y2 = [v + o for v, o in zip([num() for _ in range(4)], [ox, oy] * 2)]
            p0 = (cx, cy)
            for k in range(1, 13):
                s = k / 12
                cur.append(((1 - s) ** 2 * p0[0] + 2 * (1 - s) * s * x1 + s * s * x2,
                            (1 - s) ** 2 * p0[1] + 2 * (1 - s) * s * y1 + s * s * y2))
            cx, cy = x2, y2
    if cur:
        subs.append((cur, False))
    return subs


# ------------------------------------------------------------------ sprite
class Sprite:
    """RGBA canvas addressed in CSS px (units), stored at `ppu` pixels/unit.
    Every shape is rasterised as a 2x-supersampled coverage mask and
    alpha-composited, so translucent fills blend correctly."""

    def __init__(self, w, h, ppu=PPU):
        self.w, self.h, self.p = w, h, ppu
        self.im = Image.new('RGBA', (max(1, int(math.ceil(w * ppu))), max(1, int(math.ceil(h * ppu)))), (0, 0, 0, 0))

    # -- masks
    def _region(self, x0, y0, x1, y1, pad=2):
        p = self.p
        X0 = max(0, int(math.floor(x0 * p)) - pad); Y0 = max(0, int(math.floor(y0 * p)) - pad)
        X1 = min(self.im.width, int(math.ceil(x1 * p)) + pad); Y1 = min(self.im.height, int(math.ceil(y1 * p)) + pad)
        if X1 <= X0 or Y1 <= Y0:
            return None
        return X0, Y0, X1, Y1

    def mask(self, bbox, draw_fn):
        r = self._region(*bbox)
        if r is None:
            return None
        X0, Y0, X1, Y1 = r
        q = 2 * self.p
        m = Image.new('L', ((X1 - X0) * 2, (Y1 - Y0) * 2), 0)
        d = ImageDraw.Draw(m)
        tx = lambda x, y: (x * q - X0 * 2, y * q - Y0 * 2)
        draw_fn(d, tx, q)
        return m.reduce(2), X0, Y0

    def fill(self, mk, color):
        if mk is None:
            return
        m, X0, Y0 = mk
        a = color[3] if len(color) > 3 else 255
        if a < 255:
            m = m.point(lambda v: v * a // 255)
        solid = Image.new('RGBA', m.size, tuple(color[:3]) + (0,))
        solid.putalpha(m)
        self.im.alpha_composite(solid, dest=(X0, Y0))

    # -- shapes
    def rr_mask(self, x, y, w, h, r):
        r = max(0, min(r, w / 2, h / 2))

        def fn(d, tx, q):
            a = tx(x, y); b = tx(x + w, y + h)
            d.rounded_rectangle([a[0], a[1], b[0] - 1, b[1] - 1], radius=r * q, fill=255)
        return self.mask((x, y, x + w, y + h), fn)

    def rrect(self, x, y, w, h, r, fill=None, border=None, bw=0.0, dashed=False):
        outer = self.rr_mask(x, y, w, h, r)
        if fill is not None:
            self.fill(outer, fill)
        if border is not None and bw > 0:
            if dashed:
                self._dashed(x, y, w, h, r, border, bw)
            else:
                inner = self.rr_mask(x + bw, y + bw, w - 2 * bw, h - 2 * bw, max(0, r - bw))
                if outer is None:
                    return
                m, X0, Y0 = outer
                if inner is not None:
                    im2 = Image.new('L', m.size, 0)
                    im2.paste(inner[0], (inner[1] - X0, inner[2] - Y0))
                    m = ImageChops.subtract(m, im2)
                self.fill((m, X0, Y0), border)

    def _dashed(self, x, y, w, h, r, color, bw, dash=4.5, gap=3.5):
        # walk the stroke centre line of the rounded rect
        c = bw / 2; x0, y0, x1, y1 = x + c, y + c, x + w - c, y + h - c; rr = max(0, r - c)
        pts = []
        segs = [((x0 + rr, y0), (x1 - rr, y0)), ('arc', x1 - rr, y0 + rr, -90, 0),
                ((x1, y0 + rr), (x1, y1 - rr)), ('arc', x1 - rr, y1 - rr, 0, 90),
                ((x1 - rr, y1), (x0 + rr, y1)), ('arc', x0 + rr, y1 - rr, 90, 180),
                ((x0, y1 - rr), (x0, y0 + rr)), ('arc', x0 + rr, y0 + rr, 180, 270)]
        for s in segs:
            if s[0] == 'arc':
                _, cx, cy, a0, a1 = s
                for k in range(1, 13):
                    a = math.radians(lerp(a0, a1, k / 12))
                    pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
            else:
                pts.append(s[0]); pts.append(s[1])
        # resample by arc length
        dashes = []; on = True; left = dash; curd = [pts[0]]
        for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1]):
            L = math.hypot(bx - ax, by - ay); pos = 0.0
            while L - pos > left:
                pos += left
                p = (ax + (bx - ax) * pos / L, ay + (by - ay) * pos / L)
                if on:
                    curd.append(p); dashes.append(curd)
                else:
                    curd = [p]
                on = not on; left = dash if on else gap
            left -= (L - pos)
            if on: curd.append((bx, by))

        def fn(d, tx, q):
            for ds in dashes:
                if len(ds) >= 2:
                    d.line([tx(*p) for p in ds], fill=255, width=max(1, int(round(bw * q))), joint='curve')
        self.fill(self.mask((x, y, x + w, y + h), fn), color)

    def ellipse(self, cx, cy, rx, ry, fill=None, border=None, bw=0.0):
        def mk(rx_, ry_):
            def fn(d, tx, q):
                a = tx(cx - rx_, cy - ry_); b = tx(cx + rx_, cy + ry_)
                d.ellipse([a[0], a[1], b[0] - 1, b[1] - 1], fill=255)
            return self.mask((cx - rx_, cy - ry_, cx + rx_, cy + ry_), fn)
        outer = mk(rx, ry)
        if fill is not None:
            self.fill(outer, fill)
        if border is not None and bw > 0 and outer is not None:
            inner = mk(rx - bw, ry - bw)
            m, X0, Y0 = outer
            if inner is not None:
                im2 = Image.new('L', m.size, 0); im2.paste(inner[0], (inner[1] - X0, inner[2] - Y0))
                m = ImageChops.subtract(m, im2)
            self.fill((m, X0, Y0), border)

    def circle(self, cx, cy, r, fill=None, border=None, bw=0.0):
        self.ellipse(cx, cy, r, r, fill, border, bw)

    def polygon(self, pts, fill):
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]

        def fn(d, tx, q):
            d.polygon([tx(*p) for p in pts], fill=255)
        self.fill(self.mask((min(xs), min(ys), max(xs), max(ys)), fn), fill)

    def polyline(self, pts, color, width, round_cap=True):
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]; hw = width / 2 + 1

        def fn(d, tx, q):
            P = [tx(*p) for p in pts]
            d.line(P, fill=255, width=max(1, int(round(width * q))), joint='curve')
            if round_cap:
                rr = width * q / 2
                for (px, py) in (P[0], P[-1]):
                    d.ellipse([px - rr, py - rr, px + rr, py + rr], fill=255)
        self.fill(self.mask((min(xs) - hw, min(ys) - hw, max(xs) + hw, max(ys) + hw), fn), color)

    def path(self, d, fill=None, stroke=None, sw=1.0, cap_round=True):
        for pts, closed in parse_path(d):
            if fill is not None and len(pts) >= 3:
                self.polygon(pts, fill)
            if stroke is not None and len(pts) >= 2:
                self.polyline(pts, stroke, sw, cap_round)

    # -- text
    def text(self, x, baseline, s, fk, color, align='l'):
        if not s:
            return 0
        w = fk.width(s)
        if align == 'c': x -= w / 2
        elif align == 'r': x -= w
        if fk.fam == 'emoji':
            px = int(round(fk.size * 1.15 * self.p))
            for ch in s:
                if ch.strip():
                    em = emoji_img(ch, px)
                    self.paste(em, x + fk.size * 0.02, baseline - fk.size * 0.95)
                x += fk.size * 1.2
            return w
        asc_px = fk.f.getmetrics()[0]
        pieces = []
        cx = x
        for txt, f in runs(s, fk.fam, fk.size, fk.weight):
            if fk.ls:
                for ch in txt:
                    pieces.append((cx, ch, f)); cx += f.getlength(ch) / PPU + fk.ls
            else:
                pieces.append((cx, txt, f)); cx += f.getlength(txt) / PPU
        top = baseline - asc_px / PPU - fk.size * 0.3
        bot = baseline + fk.size * 0.5
        r = self._region(x - fk.size * 0.3, top, cx + fk.size * 0.3, bot, pad=2)
        if r is None:
            return w
        X0, Y0, X1, Y1 = r
        m = Image.new('L', (X1 - X0, Y1 - Y0), 0)
        d = ImageDraw.Draw(m)
        for px, txt, f in pieces:
            d.text((px * self.p - X0, baseline * self.p - Y0), txt, font=f, fill=255, anchor='ls')
        self.fill((m, X0, Y0), color)
        return w

    def line_text(self, x, top, lh, s, fk, color, align='l'):
        a, d = fk.metrics()
        base = top + (lh - (a + d)) / 2 + a
        return self.text(x, base, s, fk, color, align)

    def paste(self, img, x, y, opacity=1.0):
        """Alpha-composite a pixel image (already at this ppu) at unit coords."""
        X = int(round(x * self.p)); Y = int(round(y * self.p))
        if opacity < 1:
            img = with_opacity(img, opacity)
        paste_clip(self.im, img, X, Y)

    def paste_sprite(self, sp, x, y, scale=1.0, opacity=1.0):
        img = sp.im
        if abs(scale - 1) > 1e-3:
            nw = max(1, int(round(img.width * scale))); nh = max(1, int(round(img.height * scale)))
            img = img.convert('RGBa').resize((nw, nh), Image.LANCZOS).convert('RGBA')
            x += sp.w * (1 - scale) / 2; y += sp.h * (1 - scale) / 2
        self.paste(img, x, y, opacity)

    def out(self, k=1.0):
        """Downsample to final screen pixels (k = extra CSS scale)."""
        tw = max(1, int(round(self.w * k))); th = max(1, int(round(self.h * k)))
        if self.p == 2 and abs(k - 1) < 1e-6 and self.im.size == (tw * 2, th * 2):
            return self.im.convert('RGBa').reduce(2).convert('RGBA')
        return self.im.convert('RGBa').resize((tw, th), Image.LANCZOS).convert('RGBA')


_OP_LUT = {}


def with_opacity(img, op):
    if op >= 0.999:
        return img
    q = int(round(op * 100))
    lut = _OP_LUT.get(q)
    if lut is None:
        lut = _OP_LUT[q] = [int(v * q / 100 + 0.5) for v in range(256)]
    img = img.copy()
    img.putalpha(img.getchannel('A').point(lut))
    return img


def paste_clip(dst, src, X, Y):
    sx0 = max(0, -X); sy0 = max(0, -Y)
    sx1 = min(src.width, dst.width - X); sy1 = min(src.height, dst.height - Y)
    if sx1 <= sx0 or sy1 <= sy0:
        return
    if (sx0, sy0, sx1, sy1) != (0, 0, src.width, src.height):
        src = src.crop((sx0, sy0, sx1, sy1))
    dst.alpha_composite(src, dest=(X + sx0, Y + sy0))


@lru_cache(maxsize=128)
def shadow_img(wpx, hpx, rpx, dy, blur, alpha, rgb=SHADOW_RGB, cut=True):
    """CSS box-shadow (offset-y, blur) around a rounded box of wpx x hpx.
    Returns (image, margin); the box's top-left sits at (margin, margin)."""
    m = int(math.ceil(blur)) + abs(int(dy)) + 4
    sz = (wpx + 2 * m, hpx + 2 * m)
    mk = Image.new('L', sz, 0)
    ImageDraw.Draw(mk).rounded_rectangle([m, m + dy, m + wpx - 1, m + dy + hpx - 1], radius=rpx, fill=int(255 * alpha))
    mk = mk.filter(ImageFilter.GaussianBlur(blur / 2))
    if cut:  # CSS shadows are not painted under the box itself
        box = Image.new('L', (sz[0] * 2, sz[1] * 2), 0)
        ImageDraw.Draw(box).rounded_rectangle([2 * m, 2 * m, 2 * (m + wpx) - 1, 2 * (m + hpx) - 1], radius=2 * rpx, fill=255)
        mk = ImageChops.subtract(mk, ImageChops.multiply(mk, box.reduce(2)))
    im = Image.new('RGBA', sz, rgb + (0,))
    im.putalpha(mk)
    return im, m


def with_shadow(img, rpx, dy, blur, alpha, extra=None):
    """Put a box shadow under a 1x panel image. Returns (image, margin)."""
    sh, m = shadow_img(img.width, img.height, rpx, dy, blur, alpha)
    out = sh.copy()
    out.alpha_composite(img, dest=(m, m))
    return out, m


# ------------------------------------------------------------------ text layout
def wrap(segments, maxw, first_indent=0.0):
    """segments: [(text, FK, color)] -> list of lines [(x, text, FK, color)], widths"""
    toks = []
    for text, fk, col in segments:
        for part in re.split(r'(\n)', text):
            if part == '\n':
                toks.append(('\n', fk, col)); continue
            for w in re.findall(r'\S+\s*|\s+', part):
                toks.append((w, fk, col))
    lines = []; cur = []; x = first_indent; widths = []
    for w, fk, col in toks:
        if w == '\n':
            lines.append(cur); widths.append(x); cur = []; x = 0.0; continue
        tw = fk.width(w.rstrip())
        if cur and x + tw > maxw + 0.5:
            lines.append(cur); widths.append(x); cur = []; x = 0.0
            if not w.strip():
                continue
        cur.append((x, w, fk, col))
        x += fk.width(w)
    lines.append(cur); widths.append(x)
    # trim trailing space widths
    for i, ln in enumerate(lines):
        if ln:
            lx, lw, lfk, _ = ln[-1]
            widths[i] = lx + lfk.width(lw.rstrip())
    return lines, widths


def draw_lines(sp, lines, x, top, lh, align='l', boxw=0.0, widths=None):
    for i, ln in enumerate(lines):
        off = 0.0
        if align == 'c' and widths is not None:
            off = (boxw - widths[i]) / 2
        for lx, w, fk, col in ln:
            sp.line_text(x + off + lx, top + i * lh, lh, w.rstrip() if w.strip() else '', fk, col)


def normal_lh(fk):
    a, d = fk.metrics()
    return a + d


# ------------------------------------------------------------------ script / data
SKIN_HEX = ['#fde3d3', '#f3cba8', '#e2ab82', '#c58a5f', '#9c6340', '#71432a', '#4b2c1b']
HAIR_COLORS = ['#6b4a33', '#1c1514', '#d9aa5f', '#9a4a2c', '#3a2518']


def skin_at(v):
    x = clamp(v) * (len(SKIN_HEX) - 1); i = min(len(SKIN_HEX) - 2, int(math.floor(x)))
    return mix(hexc(SKIN_HEX[i]), hexc(SKIN_HEX[i + 1]), x - i)


OPT_NAMES = {
    'gender': ['Not specified', 'Girl', 'Boy'],
    'face': ['Round', 'Oval', 'Chubby cheeks'],
    'hair': ['Baby tuft', 'Short hair', 'Pigtails', 'Curly'],
    'outfit': ['Onesie', 'Overalls', 'Dress', 'T-shirt & pants'],
}
TABS = [('gender', 'Gender'), ('face', 'Face'), ('skin', 'Skin'), ('hair', 'Hair'), ('outfit', 'Clothes')]

SCRIPT = [
    dict(at=4.8, do='next', dir=1), dict(at=6.0, do='tab', cat='face'),
    dict(at=7.2, do='next', dir=1), dict(at=8.2, do='next', dir=1),
    dict(at=9.4, do='tab', cat='skin'),
    dict(at=10.5, do='drag', keys=[(10.5, 0.5), (11.3, 0.82), (12.4, 0.2)]),
    dict(at=13.4, do='tab', cat='hair'),
    dict(at=14.5, do='next', dir=1), dict(at=15.5, do='next', dir=1), dict(at=16.5, do='next', dir=-1),
    dict(at=17.6, do='color', i=1),
    dict(at=18.8, do='tab', cat='outfit'),
    dict(at=19.9, do='next', dir=1), dict(at=20.9, do='next', dir=1),
    dict(at=22.3, do='start'),
]
START_AT = SCRIPT[-1]['at'] - INTRO


def keyed(keys, c):
    for i in range(1, len(keys)):
        if c < keys[i][0]:
            return lerp(keys[i - 1][1], keys[i][1], smooth(keys[i - 1][0], keys[i][0], c))
    return keys[-1][1]


def creator_state(c):
    st = dict(tab='gender', gender=0, face=0, hair=0, outfit=0, hairColor=0, skin=0.5)
    for a in SCRIPT:
        if c < a['at']: break
        if a['do'] == 'tab': st['tab'] = a['cat']
        if a['do'] == 'next':
            st[st['tab']] = int(clamp(st[st['tab']] + a['dir'], 0, len(OPT_NAMES[st['tab']]) - 1))
        if a['do'] == 'color': st['hairColor'] = a['i']
        if a['do'] == 'drag': st['skin'] = keyed(a['keys'], c)
    return st


def tab_since(c):
    """Time (video g) at which the currently active tab was (re)built."""
    t0 = -1e9
    for a in SCRIPT:
        if c < a['at']: break
        if a['do'] == 'tab': t0 = a['at']
    return t0


INDICATORS = [
    ('Emotional security', 'Attachment', -30, 25),
    ('Emotion regulation', 'Self-regulation · calming down', -26, 18),
    ('Self-worth', 'Self-concept', -28, 22),
    ('Persistence & curiosity', 'Approaches to learning', -35, 30),
    ('Asking for help', 'Social-communication', -32, 24),
    ('Problem-solving', 'Cognitive · learning from mistakes', -18, 28),
    ('Parent–child trust', 'Relationship', -24, 26),
]
BASE = 55
RESPONSES = {
    'harsh': dict(you='“Stop making a mess!”', style='Critical', color=BAD,
                  child='“I did something bad. Maybe I shouldn\'t ask for help next time.”',
                  why='Sharp words right after an accident can trigger a stress response. If it happens often, children may learn to hide mistakes and give up sooner, instead of practicing how to fix things.'),
    'warm': dict(you='“Oops! Let\'s build it again together.”', style='Warm · collaborative', color=GOOD,
                 child='“Mistakes are okay. We can fix it together.”',
                 why='Staying calm and fixing it together is a “serve-and-return” moment. It helps the child calm down, shows how to solve the problem, and tells them it\'s safe to try again.'),
}
NOTE = ('Areas drawn from domains used in early-childhood screeners (e.g. ASQ:SE-2) and research on attachment and '
        '“serve-and-return” interaction. One moment doesn’t define a child — these show direction, not a measurement.')
CHAPTERS = [(11.4, 'An everyday moment'), (14.6, 'Choose a response'), (22.5, 'A possible reaction'),
            (26.2, 'Try again'), (35.4, 'A different reaction'), (99, 'Reflect')]
OPTS = [('A', '“Oops! Let\'s build it again together.”', False), ('B', '“Stop making a mess!”', False),
        ('C', '“You\'re fine. Do it yourself.”', False), ('✎', 'Write your own…', True)]


def round2(t):
    return t > ROUND2_AT


# ------------------------------------------------------------------ visibility (story time t)
def vis_title(t): return within(t, -INTRO + 0.3, -INTRO + 3.3)
def vis_chapter(t): return t > -INTRO + 3.3
def vis_creator(t): return within(t, -INTRO + 3.6, START_AT + 0.5)
def vis_bubble(t): return within(t, 7.9, 14.6) or within(t, 23.4, 26.2)
def vis_options(t): return within(t, 11.5, 14.9) or within(t, 23.6, 26.7)
def vis_said(t): return within(t, 14.6, 15.6) or within(t, 26.4, 27.6)
def vis_feedback(t): return within(t, 15.6, 22.6) or within(t, 27.6, 35.4)
def vis_rewind(t): return within(t, 22.6, 23.4)
def vis_end(t): return within(t, 35.6, 39.6)


def opt_picked(i, t):
    r2 = round2(t)
    return (i == 0 and r2 and t > 26.0) or (i == 1 and not r2 and t > 14.2)


def opt_dim(i, t):
    if i > 2: return False
    r2 = round2(t)
    return ((not r2 and t > 14.2) or (r2 and t > 26.0)) and not opt_picked(i, t)


# ------------------------------------------------------------------ layouts (CSS px)
class CreatorL:
    W = 470; PAD = 20
    HEAD_Y = 22
    TABS_Y = 59; TABS_H = 41
    SEC_Y = 112
    VIEW = (66, 112, 338, 126)
    ARRL = (20, 155, 40, 40); ARRR = (410, 155, 40, 40)
    OPTNAME_Y = 246
    DOTS_Y = 273
    SUB_Y = 292; SW_Y = 313
    TRACK = (44, 156, 382, 30)
    SKIN_NAME_Y = 214; SKIN_SUB_Y = 241
    START = (20, 372, 430, 43)
    H = 433

    @staticmethod
    def tab_rect(i):
        tw = (430 - 8 - 16) / 5
        return (24 + i * (tw + 4), 63, tw, 33)

    @staticmethod
    def swatch_rect(i):
        return (135 + i * 42, 313, 32, 32)

    @staticmethod
    def knob_rect(skin):
        cx = 44 + 382 * skin
        return (cx - 19, 171 - 19, 38, 38)


CREATOR_POS = (W - 32 - CreatorL.W, (H - CreatorL.H) / 2)


@lru_cache(maxsize=None)
def options_layout():
    fk = FK('sans', 16)
    lh1, lh = 26.0, normal_lh(fk)
    y = 20 + normal_lh(FK('serif', 22)) + 12
    rows = []
    for key, txt, write in OPTS:
        lines, widths = wrap([(txt, fk, INK)], 293, first_indent=32)
        h = 13.5 + lh1 + (len(lines) - 1) * lh + 13.5
        rows.append((18, y, 324, h, lines))
        y += h + 8
    height = y + 18
    return rows, height


def options_pos():
    _, h = options_layout()
    return (W - 32 - 360, (H - h) / 2)


FB_MAX_H = 660


@lru_cache(maxsize=None)
def feedback_layout(r2):
    R = RESPONSES['warm' if r2 else 'harsh']
    L = {}
    who = FK('sans', 11, 700, ls=0.77)
    y = 16
    # you row
    you_lines, _ = wrap([(R['you'], FK('sans', 16, 700), INK)], 320)
    you_h = 10 + max(30, 15 + 4 + len(you_lines) * normal_lh(FK('sans', 16, 700))) + 10
    L['you'] = (18, y, 384, you_h, you_lines)
    y += you_h + 8
    q_lines, _ = wrap([(R['child'], FK('sansi', 16), INK)], 320)
    ch_h = 10 + max(30, 15 + 4 + len(q_lines) * 16 * 1.35) + 10
    L['child'] = (18, y, 384, ch_h, q_lines)
    y += ch_h + 12
    L['sec'] = y
    y += normal_lh(FK('serif', 19)) + 6
    rows = []
    for _ in INDICATORS:
        rows.append(y); y += 1 + 5 + 13.5 * 1.15 + 11 * 1.15 + 5
    L['ind'] = rows
    y += 10
    why_fk = FK('sans', 13); why_b = FK('sans', 13, 700)
    why_lines, _ = wrap([('Why: ', why_b, ACCENT), (R['why'], why_fk, INK)], 356)
    why_h = 10 + len(why_lines) * 13 * 1.45 + 10
    L['why'] = (20, y, 380, why_h, why_lines)
    y += why_h + 8
    note_lines, _ = wrap([(NOTE, FK('sans', 11), MUTED)], 380)
    L['note'] = (20, y, note_lines)
    y += len(note_lines) * 11 * 1.4
    if not r2:
        y += 10
        L['retry'] = (18, y, 384, 44)
        y += 44
    y += 16
    L['h'] = y
    k = min(1.0, FB_MAX_H / y)
    L['k'] = k
    L['pos'] = (W - 32 - 420 * k, (H - y * k) / 2)
    return L


# bubble: tail tip anchored here (tail points down-right toward the baby's head)
BUBBLE_TIP = (0.36 * W, 0.26 * H)


@lru_cache(maxsize=None)
def bubble_layout():
    fk = FK('sans', 19, 600)
    # CSS max-width is 280 (244 content); widened slightly so the first sentence stays on one line
    lines, widths = wrap([('Uh-oh… my tower fell down.\nCan you help me?', fk, INK)], 272)
    lh = 19 * 1.35
    bw = max(widths) + 36; bh = len(lines) * lh + 28
    bx = BUBBLE_TIP[0] - 0.88 * bw; by = BUBBLE_TIP[1] - 12 - bh
    return lines, lh, bw, bh, bx, by


# ------------------------------------------------------------------ element rects (screen px)
def screen_rect(name, t):
    g = t + INTRO
    cx0, cy0 = CREATOR_POS
    if name.startswith('tab:'):
        i = [c for c, _ in TABS].index(name[4:])
        x, y, w, h = CreatorL.tab_rect(i); return (cx0 + x, cy0 + y, w, h)
    st = creator_state(g)
    if name in ('arrL', 'arrR'):
        if st['tab'] == 'skin': return None
        x, y, w, h = CreatorL.ARRL if name == 'arrL' else CreatorL.ARRR
        return (cx0 + x, cy0 + y, w, h)
    if name.startswith('swatch:'):
        if st['tab'] != 'hair': return None
        x, y, w, h = CreatorL.swatch_rect(int(name[7:])); return (cx0 + x, cy0 + y, w, h)
    if name == 'knob':
        if st['tab'] != 'skin': return None
        x, y, w, h = CreatorL.knob_rect(st['skin']); return (cx0 + x, cy0 + y, w, h)
    if name == 'start':
        x, y, w, h = CreatorL.START; return (cx0 + x, cy0 + y, w, h)
    if name.startswith('opt'):
        i = 'ABC'.index(name[3])
        ox, oy = options_pos(); x, y, w, h, _ = options_layout()[0][i]
        return (ox + x, oy + y, w, h)
    if name == 'retry':
        L = feedback_layout(round2(t))
        if 'retry' not in L: return None
        k = L['k']; px, py = L['pos']; x, y, w, h = L['retry']
        return (px + x * k, py + y * k, w * k, h * k)
    return None


def center(name, t):
    r = screen_rect(name, t)
    if r is None or r[2] == 0:
        return (W * 0.8, H * 0.5)
    return (r[0] + r[2] * 0.55, r[1] + r[3] * 0.55)


def script_target(a):
    return {'tab': lambda: 'tab:' + a['cat'], 'next': lambda: 'arrR' if a['dir'] > 0 else 'arrL',
            'color': lambda: 'swatch:%d' % a['i'], 'drag': lambda: 'knob'}.get(a['do'], lambda: 'start')()


def build_moves():
    mv = []
    for i, a in enumerate(SCRIPT):
        at = a['at'] - INTRO
        nxt = SCRIPT[i + 1] if i + 1 < len(SCRIPT) else None
        end = a['keys'][-1][0] - INTRO + 0.3 if a['do'] == 'drag' else at + 0.4
        mv.append(dict(s=at - 0.85, a=at - 0.15, c=at, e=min(end, nxt['at'] - INTRO - 0.85) if nxt else end,
                       el=script_target(a), frm=script_target(SCRIPT[i - 1]) if i else (0.85, 0.95),
                       drag=a['do'] == 'drag'))
    mv += [dict(s=12.3, a=13.9, c=14.2, e=14.8, el='optB', frm=(0.8, 0.95), drag=False),
           dict(s=21.2, a=22.0, c=22.3, e=22.7, el='retry', frm=(0.6, 0.9), drag=False),
           dict(s=24.3, a=25.7, c=26.0, e=26.6, el='optA', frm=(0.8, 0.95), drag=False)]
    return mv


MOVES = build_moves()


def active_move(t):
    for m in MOVES:
        if within(t, m['s'], m['e']):
            return m
    return None


def hovered(el, t):
    m = active_move(t)
    return bool(m and m['el'] == el and t >= m['a'])


def cursor_down(t):
    m = active_move(t)
    if not m: return False
    return within(t, m['c'] - 0.05, m['e'] - 0.3) if m['drag'] else within(t, m['c'] - 0.05, m['c'] + 0.35)


def cursor_pos(t):
    m = active_move(t)
    if not m: return None
    tx, ty = center(m['el'], t)
    if isinstance(m['frm'], tuple):
        fx, fy = W * m['frm'][0], H * m['frm'][1]
    else:
        fx, fy = center(m['frm'], t)
    k = smooth(m['s'], m['a'], t)
    return (lerp(fx, tx, k), lerp(fy, ty, k) - math.sin(math.pi * k) * 40)


# ------------------------------------------------------------------ icons (64-unit viewBox)
HC = '#3a2a24'


def face_shapes(rx=18, ry=18, ch=4):
    return [('ellipse', 32, 36, rx, ry, '#f3cba8'), ('circle', 26, 36, 2.2, '#2a1d22'), ('circle', 38, 36, 2.2, '#2a1d22'),
            ('circle', 32 - rx * 0.62, 42, ch, '#ff9aa8', .7), ('circle', 32 + rx * 0.62, 42, ch, '#ff9aa8', .7),
            ('stroke', 'M29 44 q3 3 6 0', '#9a3d45', 2)]


BOW = [('path', 'M40 16 l8 -5 v10 z M40 16 l-8 -5 v10 z', '#ff5f8a'), ('circle', 40, 16, 2.5, '#ff5f8a')]
TUFT = [('stroke', 'M32 19 q7 -7 1 -11', HC, 3)]
TOPCAP = [('path', 'M14 33 C14 12 50 12 50 33 Q32 24 14 33 Z', HC)]
ICONS = {
    'gender': [face_shapes() + TUFT, face_shapes() + TUFT + BOW,
               face_shapes() + TUFT + [('path', 'M17 24 Q32 8 47 24 Z', '#7cc6ff'), ('rect', 40, 21, 12, 4, 2, '#7cc6ff')]],
    'face': [face_shapes(), face_shapes(15, 21, 3), face_shapes(21, 17, 6)],
    'hair': [face_shapes() + TUFT,
             [('rect', 12, 24, 40, 30, 12, HC)] + face_shapes() + TOPCAP,
             [('circle', 11, 30, 8, HC), ('circle', 53, 30, 8, HC)] + face_shapes() + TOPCAP,
             face_shapes() + [('circle', x + 1, y, 7, HC) for x, y in zip([14, 20, 27, 34, 41, 47, 51, 13], [28, 19, 14, 13, 15, 20, 28, 36])]],
    'outfit': [
        [('circle', 14, 24, 7, '#ffd46e'), ('circle', 50, 24, 7, '#ffd46e'), ('rect', 16, 14, 32, 40, 15, '#ffd46e'), ('ellipse', 32, 36, 9, 11, '#fff2cc')],
        [('rect', 12, 14, 40, 18, 8, '#ff9e80'), ('rect', 18, 24, 28, 30, 6, '#5f86c4'), ('rect', 20, 12, 4, 14, 0, '#5f86c4'),
         ('rect', 40, 12, 4, 14, 0, '#5f86c4'), ('circle', 24, 29, 2, '#ffd46e'), ('circle', 40, 29, 2, '#ffd46e')],
        [('circle', 20, 18, 6, '#f7a1bd'), ('circle', 44, 18, 6, '#f7a1bd'), ('path', 'M23 14 H41 L52 54 H12 Z', '#f7a1bd'),
         ('rect', 21, 27, 22, 4, 2, '#ffffff'), ('stroke_butt', 'M12 54 H52', '#ffffff', 3)],
        [('path', 'M18 12 H46 L54 22 L47 27 V36 H17 V27 L10 22 Z', '#8fd3b3'),
         ('path', 'M18 36 H46 L45 56 H35 L32 44 L29 56 H19 Z', '#6c7fb3')],
    ],
}


@lru_cache(maxsize=None)
def icon_img(cat, idx):
    """76x76 CSS px icon rendered at PPU (152 px)."""
    sp = Sprite(64, 64, ppu=76 * PPU / 64)
    for s in ICONS[cat][idx]:
        kind = s[0]
        if kind == 'ellipse':
            sp.ellipse(s[1], s[2], s[3], s[4], hexc(s[5]))
        elif kind == 'circle':
            a = int(255 * s[5]) if len(s) > 5 else 255
            sp.circle(s[1], s[2], s[3], hexc(s[4], a))
        elif kind == 'rect':
            sp.rrect(s[1], s[2], s[3], s[4], s[5], hexc(s[6]))
        elif kind == 'path':
            sp.path(s[1], fill=hexc(s[2]))
        elif kind == 'stroke':
            sp.path(s[1], stroke=hexc(s[2]), sw=s[3], cap_round=True)
        elif kind == 'stroke_butt':
            sp.path(s[1], stroke=hexc(s[2]), sw=s[3], cap_round=False)
    return sp.im


@lru_cache(maxsize=64)
def card_sprite(cat, idx, s100):
    s = s100 / 100
    sp = Sprite(96, 112)
    sp.rrect(0, 0, 96, 112, 18, WHITE, mix(hexc('#eee4e4'), ACCENT, s), 2)
    sp.paste(icon_img(cat, idx), 10, 18)
    return sp


# ------------------------------------------------------------------ panel renderers
def panel_bg(sp, w, h, r=20):
    sp.rrect(0, 0, w, h, r, PANEL)


@lru_cache(maxsize=32)
def render_chapter(num, text):
    fk = FK('sans', 15)
    tw = fk.width(text)
    w = 8 + 26 + 10 + tw + 16; h = 42
    sp = Sprite(w, h)
    sp.rrect(0, 0, w, h, 21, PANEL)
    sp.circle(8 + 13, 21, 13, ACCENT)
    sp.line_text(21, 8, 26, str(num), FK('sans', 13, 700), WHITE, align='c')
    sp.line_text(44, 0, 42, text, fk, INK)
    return with_shadow(sp.out(), 21, 4, 18, 0.12)


def render_card(kind):
    if kind == 'title':
        h1 = FK('serif', 44); p = FK('sans', 17)
        lines_p, wp = wrap([('A concept prototype: a virtual child that helps parents notice\n'
                             'their usual responses and see how a child might experience them.', p, MUTED)], 540)
        tags = ['Parenting education', 'Perspective-taking', 'Self-awareness']
        tfk = FK('sans', 13)
        tws = [tfk.width(s) + 26 for s in tags]
        content_w = max(max(wp), sum(tws) + 16, h1.width('Baby Sim'))
        w = min(620, content_w + 80)   # CSS caps at 560; widened so each sentence stays on one line
        cw = w - 80
        lines_p, wp = wrap([('A concept prototype: a virtual child that helps parents notice\n'
                             'their usual responses and see how a child might experience them.', p, MUTED)], cw)
        h1h = normal_lh(h1)
        tag_h = 4 + normal_lh(tfk) + 4 + 2
        h = 28 + h1h + 8 + len(lines_p) * 17 * 1.5 + 16 + tag_h + 28
        sp = Sprite(w, h)
        sp.rrect(0, 0, w, h, 22, PANEL)
        sp.line_text(w / 2, 28, h1h, 'Baby Sim', h1, INK, align='c')
        y = 28 + h1h + 8
        draw_lines(sp, lines_p, 40, y, 17 * 1.5, align='c', boxw=cw, widths=wp)
        y += len(lines_p) * 17 * 1.5 + 16
        x = (w - (sum(tws) + 16)) / 2
        for s, tw in zip(tags, tws):
            sp.rrect(x, y, tw, tag_h, tag_h / 2, CHIP, CHIPLINE, 1)
            sp.line_text(x + tw / 2, y, tag_h, s, tfk, INK, align='c')
            x += tw + 8
    else:
        h2 = FK('serif', 34); p = FK('sans', 17)
        txt = 'Which response sounds most like your usual habit?\nWhat might your child have felt in that moment?'
        lines_p, wp = wrap([(txt, p, MUTED)], 540)
        w = min(620, max(wp) + 80); cw = w - 80
        h2h = normal_lh(h2)
        h = 28 + h2h + 8 + len(lines_p) * 17 * 1.5 + 28
        sp = Sprite(w, h)
        sp.rrect(0, 0, w, h, 22, PANEL)
        sp.line_text(w / 2, 28, h2h, 'Reflect', h2, ACCENT, align='c')
        draw_lines(sp, lines_p, 40, 28 + h2h + 8, 17 * 1.5, align='c', boxw=cw, widths=wp)
    return with_shadow(sp.out(), 22, 10, 40, 0.18)


@lru_cache(maxsize=None)
def card_image(kind):
    return render_card(kind)


@lru_cache(maxsize=None)
def render_bubble():
    lines, lh, bw, bh, bx, by = bubble_layout()
    sp = Sprite(bw, bh + 12)
    sp.rrect(0, 0, bw, bh, 20, WHITE)
    R = bw * 0.88
    sp.polygon([(R - 12, bh - 1), (R, bh - 1), (R, bh + 12)], WHITE)
    draw_lines(sp, lines, 18, 14, lh)
    img = sp.out()
    sh, m = shadow_img(int(round(bw)), int(round(bh)), 20, 6, 24, 0.16)
    out = sh.copy()
    paste_clip(out, img, m, m)
    return out, m


@lru_cache(maxsize=64)
def render_options(state):
    """state: tuple of (hover, picked, dim) levels*100 per option."""
    rows, height = options_layout()
    sp = Sprite(360, height)
    panel_bg(sp, 360, height)
    hf = FK('serif', 22)
    sp.line_text(22, 20, normal_lh(hf), 'How would you respond?', hf, ACCENT)
    fk = FK('sans', 16); lh = normal_lh(fk)
    for i, ((key, txt, write), (x, y, w, h, lines)) in enumerate(zip(OPTS, rows)):
        hv, pk, dm = [v / 100 for v in state[i]]
        sub = Sprite(w, h)
        bg = mix(mix(WHITE, hexc('#f4f2ff'), hv), ACCENT, pk)
        bd = mix(mix(CHIPLINE, hexc('#8f86e8'), hv), ACCENT, pk)
        sub.rrect(0, 0, w, h, 14, bg, bd, 1.5, dashed=write)
        tcol = mix(MUTED if write else INK, WHITE, pk)
        bcol = mix(CHIP, (255, 255, 255, 64), pk)
        # letter circle, vertically centred on first line box
        sub.circle(15.5 + 12, 13.5 + 13, 12, bcol)
        sub.line_text(15.5 + 12, 13.5, 26, key, FK('sans', 13, 700), mix(MUTED if write else INK, WHITE, pk), align='c')
        for li, ln in enumerate(lines):
            top = 13.5 + (0 if li == 0 else 26 + (li - 1) * lh)
            lhh = 26 if li == 0 else lh
            for lx, wd, f2, _ in ln:
                sub.line_text(15.5 + lx, top, lhh, wd.rstrip(), fk, tcol)
        sp.paste_sprite(sub, x, y, scale=1 + 0.03 * pk, opacity=1 - 0.65 * dm)
    return with_shadow(sp.out(), 20, 10, 40, 0.16)


@lru_cache(maxsize=16)
def render_said(r2):
    fk = FK('sans', 18); fb = FK('sans', 18, 700)
    said = '“Oops! Let\'s build it again together.”' if r2 else '“Stop making a mess!”'
    w1 = fk.width('You said: '); w2 = fb.width(said)
    w = 20 + w1 + w2 + 20; h = 24 + normal_lh(fk)
    sp = Sprite(w, h)
    sp.rrect(0, 0, w, h, h / 2, INK)
    sp.line_text(20, 12, normal_lh(fk), 'You said:', fk, WHITE)
    sp.line_text(20 + w1, 12, normal_lh(fk), said, fb, WHITE)
    return sp.out(), 0


@lru_cache(maxsize=None)
def render_feedback_static(r2):
    L = feedback_layout(r2)
    R = RESPONSES['warm' if r2 else 'harsh']
    sp = Sprite(420, L['h'])
    panel_bg(sp, 420, L['h'])
    who = FK('sans', 11, 700, ls=0.77)
    # your response row
    x, y, w, h, lines = L['you']
    sp.rrect(x, y, w, h, 14, hexc('#f3eff0'))
    sp.circle(x + 12 + 15, y + 10 + 15, 15, INK)
    sp.line_text(x + 27, y + 10, 30, 'You', FK('sans', 12, 700), WHITE, align='c')
    tx = x + 12 + 30 + 10
    wv = sp.line_text(tx, y + 10, 15, 'YOUR RESPONSE', who, MUTED)
    pf = FK('sans', 11, 700); pw = pf.width(R['style']) + 16
    sp.rrect(tx + wv + 6, y + 10 + 0.5, pw, 14, 7, R['color'])
    sp.line_text(tx + wv + 6 + pw / 2, y + 10 + 0.5, 14, R['style'], pf, WHITE, align='c')
    lf = FK('sans', 16, 700)
    draw_lines(sp, lines, tx, y + 10 + 15 + 4, normal_lh(lf))
    # child row
    x, y, w, h, lines = L['child']
    sp.rrect(x, y, w, h, 14, hexc('#fff4f6'))
    sp.circle(x + 27, y + 25, 15, hexc('#ffd3e1'))
    em = emoji_img('🧸', int(round(18 * PPU)))
    sp.paste(em, x + 27 - 9, y + 25 - 9)
    sp.line_text(tx, y + 10, 15, 'WHAT THE CHILD MIGHT BE THINKING', who, MUTED)
    draw_lines(sp, lines, tx, y + 10 + 15 + 4, 16 * 1.35)
    # section head
    sf = FK('serif', 19); sh = normal_lh(sf)
    base = L['sec'] + (sh - sum(sf.metrics())) / 2 + sf.metrics()[0]
    sp.text(20, base, 'Development check-in', sf, ACCENT)
    sp.text(400, base, 'compared with before the moment', FK('sans', 11), MUTED, align='r')
    # indicator names
    nm = FK('sans', 13.5, 600); dmf = FK('sans', 11)
    for (name, dom, _, _), ry in zip(INDICATORS, L['ind']):
        sp.rrect(18, ry, 384, 1, 0, hexc('#f1e8e8'))
        sp.line_text(20, ry + 6, 13.5 * 1.15, name, nm, INK)
        sp.line_text(20, ry + 6 + 13.5 * 1.15, 11 * 1.15, dom, dmf, MUTED)
    # why box
    x, y, w, h, lines = L['why']
    sp.rrect(x, y, w, h, 12, hexc('#faf6f2'))
    draw_lines(sp, lines, x + 12, y + 10, 13 * 1.45)
    x, y, lines = L['note']
    draw_lines(sp, lines, x, y, 11 * 1.4)
    return sp


@lru_cache(maxsize=64)
def render_feedback(r2, ks, retry_state):
    L = feedback_layout(r2)
    R = RESPONSES['warm' if r2 else 'harsh']
    base = render_feedback_static(r2)
    sp = Sprite(base.w, base.h)
    sp.im = base.im.copy()
    col_x = 20 + (380 - 96 - 42 - 16) + 8
    dl_r = 400
    for (name, dom, harsh, warm), ry, k100 in zip(INDICATORS, L['ind'], ks):
        k = k100 / 1000
        delta = warm if r2 else harsh
        rh = 1 + 5 + 13.5 * 1.15 + 11 * 1.15 + 5
        cy = ry + 1 + (rh - 1) / 2
        sp.rrect(col_x, cy - 4.5, 96, 9, 4.5, hexc('#efe6e6'))
        fw = 96 * (BASE + delta * k) / 100
        sp.rrect(col_x, cy - 4.5, fw, 9, 4.5, R['color'] if k > 0 else hexc('#c9bdbd'))
        if k > 0.05:
            s = '%s %d' % ('▲' if delta > 0 else '▼', round(abs(delta) * k))
            sp.line_text(dl_r, cy - 7.5, 15, s, FK('sans', 12, 700), R['color'], align='r')
    if 'retry' in L:
        hv, pk = [v / 100 for v in retry_state]
        x, y, w, h = L['retry']
        sub = Sprite(w, h)
        sub.rrect(0, 0, w, h, 14, mix(mix(WHITE, hexc('#fff0f3'), hv), ACCENT, pk), ACCENT, 1.5)
        sub.line_text(w / 2, 0, h, '↺ Try a different response', FK('sans', 16, 600), mix(ACCENT, WHITE, pk), align='c')
        sp.paste_sprite(sub, x, y, scale=1 + 0.03 * pk)
    return with_shadow(sp.out(L['k']), int(round(20 * L['k'])), 10, 40, 0.16)


@lru_cache(maxsize=None)
def skin_track_img():
    w, h = 382, 30
    sp = Sprite(w, h)
    grad = Image.new('RGBA', (int(w * PPU), 1))
    for x in range(grad.width):
        grad.putpixel((x, 0), skin_at(x / (grad.width - 1)))
    grad = grad.resize((int(w * PPU), int(h * PPU)))
    mk = sp.rr_mask(0, 0, w, h, 15)
    m, X0, Y0 = mk
    g = grad.crop((X0, Y0, X0 + m.width, Y0 + m.height))
    g.putalpha(m)
    sp.im.alpha_composite(g, dest=(X0, Y0))
    # inset shadow: darker top edge
    ish = Image.new('L', sp.im.size, 0)
    ImageDraw.Draw(ish).rounded_rectangle([0, 0, sp.im.width - 1, sp.im.height - 1], radius=15 * PPU, fill=255)
    inner = Image.new('L', sp.im.size, 0)
    ImageDraw.Draw(inner).rounded_rectangle([0, 2 * PPU, sp.im.width - 1, sp.im.height - 1 + PPU], radius=15 * PPU, fill=255)
    inner = inner.filter(ImageFilter.GaussianBlur(2 * PPU))
    edge = ImageChops.subtract(ish, inner).point(lambda v: int(v * 0.3))
    dark = Image.new('RGBA', sp.im.size, (0, 0, 0, 0)); dark.putalpha(edge)
    sp.im.alpha_composite(dark)
    return sp.im


@lru_cache(maxsize=None)
def knob_shadow():
    return shadow_img(38 * PPU, 38 * PPU, 19 * PPU, 3 * PPU, 10 * PPU, 0.28, (0, 0, 0), False)


def creator_frame_state(t):
    g = t + INTRO
    st = creator_state(g)
    tab = st['tab']
    t0 = tab_since(g)
    tabs_state = []
    for cat, _ in TABS:
        act = trans(lambda u, c=cat: creator_state(u + INTRO)['tab'] == c, t, 0.2)
        hv = trans(lambda u, c=cat: hovered('tab:' + c, u), t, 0.2)
        tabs_state.append((int(act * 100), int(hv * 100)))
    start_hv = int(trans(lambda u: hovered('start', u), t, 0.2) * 100)
    start_pk = int(trans(lambda u: within(u, START_AT, START_AT + 0.6), t, 0.2) * 100)
    common = (tuple(tabs_state), start_hv, start_pk)
    if tab == 'skin':
        return ('skin', int(round(st['skin'] * 1000))) + common
    n = len(OPT_NAMES[tab]); idx = st[tab]
    # strip slide: last 'next' event in this tab
    cardW = 106; vw = 338
    posf = lambda i: vw / 2 - i * cardW - 48
    pos = posf(idx)
    for a in SCRIPT:
        if a['at'] > g: break
        if a['do'] == 'next' and a['at'] >= t0:
            p = (g - a['at']) / 0.45
            if p < 1:
                prev = int(clamp(idx - a['dir'], 0, n - 1))
                pos = lerp(posf(prev), posf(idx), STRIP_EASE(p))
    clampt = lambda u: max(u, t0 - INTRO)
    sels = tuple(int(trans(lambda u, i=i: (lambda s: s['tab'] == tab and s[tab] == i)(creator_state(clampt(u) + INTRO)), t, 0.3) * 100)
                 for i in range(n))
    arrows = []
    for name, d in (('arrL', -1), ('arrR', 1)):
        hv = trans(lambda u, nm=name: hovered(nm, u), t, 0.15)
        pr = trans(lambda u, dd=d: any(a['do'] == 'next' and within(u + INTRO, a['at'], a['at'] + 0.25) and a['dir'] == dd
                                       for a in SCRIPT), t, 0.15)
        arrows.append((int(hv * 100), int(pr * 100)))
    sw = ()
    if tab == 'hair':
        sw = tuple((int(trans(lambda u, i=i: creator_state(u + INTRO)['hairColor'] == i, t, 0.2) * 100),
                    int(trans(lambda u, i=i: hovered('swatch:%d' % i, u), t, 0.2) * 100)) for i in range(5))
    return ('car', tab, idx, int(round(pos * 2)), sels, tuple(arrows), sw) + common


@lru_cache(maxsize=48)
def render_creator(state):
    L = CreatorL
    sp = Sprite(L.W, L.H)
    panel_bg(sp, L.W, L.H)
    hf = FK('serif', 22)
    a, d = hf.metrics(); lhh = a + d
    base = L.HEAD_Y + a
    sp.text(24, base, 'Design your baby', hf, ACCENT)
    df = FK('sans', 13)
    dw = df.width('Surprise me')
    sp.text(446, base, 'Surprise me', df, MUTED, align='r')
    sp.paste(emoji_img('🎲', int(14 * PPU)), 446 - dw - 20, base - 12)
    # tabs
    if state[0] == 'skin':
        tabs_state, start_hv, start_pk = state[2], state[3], state[4]
    else:
        tabs_state, start_hv, start_pk = state[7], state[8], state[9]
    sp.rrect(20, L.TABS_Y, 430, L.TABS_H, 14, hexc('#f3ecec'))
    tfk = FK('sans', 14, 600)
    for i, ((cat, label), (act, hv)) in enumerate(zip(TABS, tabs_state)):
        act /= 100; hv /= 100
        x, y, w, h = L.tab_rect(i)
        if act > 0.01:
            sh, m = shadow_img(int(w * PPU), int(h * PPU), 10 * PPU, 2 * PPU, 8 * PPU, 0.12 * act)
            sp.paste(sh, x - m / PPU, y - m / PPU)
        bg = mix((255, 255, 255, int(153 * hv)), WHITE, act)
        if bg[3] > 0:
            sp.rrect(x, y, w, h, 10, bg)
        col = mix(mix(MUTED, INK, hv), ACCENT, act)
        sp.line_text(x + w / 2, y, h, label, tfk, col, align='c')
    of = FK('sans', 19, 700); ofh = normal_lh(of)
    sub = FK('sans', 12, 400, ls=0.72)
    if state[0] == 'skin':
        skin = state[1] / 1000
        tx, ty, tw, th = L.TRACK
        sp.paste(skin_track_img(), tx, ty)
        kx, ky, kw, kh = L.knob_rect(skin)
        sh, m = knob_shadow()
        sp.paste(sh, kx - m / PPU, ky - m / PPU)
        sp.circle(kx + 19, ky + 19, 19, skin_at(skin), WHITE, 4)
        sp.line_text(235, L.SKIN_NAME_Y, ofh, 'Skin color', of, INK, align='c')
        sp.line_text(235, L.SKIN_SUB_Y, 14, 'DRAG TO CHOOSE · EVERY CHILD IS UNIQUE', sub, MUTED, align='c')
    else:
        _, tab, idx, pos2, sels, arrows, sw = state[:7]
        pos = pos2 / 2
        vx, vy, vw, vh = L.VIEW
        view = Sprite(vw, vh)
        for i, s in enumerate(sels):
            s /= 100
            cx = pos + i * 106
            if cx > vw + 10 or cx + 96 < -10:
                continue
            sc = lerp(0.84, 1, s)
            if s > 0.01:
                shw, shh = int(96 * sc * PPU), int(112 * sc * PPU)
                sh, m = shadow_img(shw, shh, int(18 * sc * PPU), 4 * PPU, 14 * PPU, 0.22 * s, (214, 56, 90))
                view.paste(sh, cx + 48 - 48 * sc - m / PPU, 6 + 56 - 56 * sc - m / PPU)
            view.paste_sprite(card_sprite(tab, i, int(round(s * 100))), cx, 6, scale=sc, opacity=lerp(0.55, 1, s))
        # edge fade mask
        mw = view.im.width
        grad = Image.new('L', (mw, 1))
        for x in range(mw):
            u = x / (mw - 1)
            grad.putpixel((x, 0), int(255 * clamp(min(u / 0.2, (1 - u) / 0.2))))
        grad = grad.resize(view.im.size)
        view.im.putalpha(ImageChops.multiply(view.im.getchannel('A'), grad))
        sp.paste(view.im, vx, vy)
        for (name, (ax, ay, aw, ah)), (hv, pr), glyph in zip((('arrL', L.ARRL), ('arrR', L.ARRR)), arrows, ('‹', '›')):
            hv /= 100; pr /= 100
            asp = Sprite(40, 40)
            asp.circle(20, 20, 20, mix(mix(CHIP, hexc('#d9d4ff'), hv), ACCENT, pr))
            gf = FK('sans', 24)
            a2, d2 = gf.metrics()
            asp.text(20, 20 + a2 - (a2 + d2) / 2 - 1, glyph, gf, mix(INK, WHITE, pr), align='c')
            sp.paste_sprite(asp, ax, ay, scale=1 - 0.12 * pr)
        sp.line_text(235, L.OPTNAME_Y, ofh, OPT_NAMES[tab][idx], of, INK, align='c')
        # dots
        n = len(sels)
        widths = [lerp(7, 18, s / 100) for s in sels]
        total = sum(widths) + 6 * (n - 1)
        x = 235 - total / 2
        for wdt, s in zip(widths, sels):
            sp.rrect(x, L.DOTS_Y, wdt, 7, 3.5, mix(hexc('#e6dada'), ACCENT, s / 100))
            x += wdt + 6
        if tab == 'hair':
            sp.line_text(235, L.SUB_Y, 14, 'HAIR COLOR', sub, MUTED, align='c')
            for i, (sel, hv) in enumerate(sw):
                sel /= 100; hv /= 100
                x, y, w, h = L.swatch_rect(i)
                sc = max(1 + 0.15 * sel, 1 + 0.12 * hv)
                ssp = Sprite(40, 40)
                ring = lerp(1.5, 2.5, sel)
                ssp.circle(20, 20, 16 + ring, mix(hexc('#e0d4d4'), ACCENT, sel))
                ssp.circle(20, 20, 16, WHITE)
                ssp.circle(20, 20, 13, hexc(HAIR_COLORS[i]))
                sp.paste_sprite(ssp, x - 4, y - 4, scale=sc)
    # start button
    hv, pk = start_hv / 100, start_pk / 100
    x, y, w, h = L.START
    bsp = Sprite(w, h)
    bsp.rrect(0, 0, w, h, 14, mix(mix(INK, hexc('#5a4148'), hv), ACCENT, pk))
    bsp.line_text(w / 2, 0, h, 'Start the moment →', FK('sans', 16, 700), WHITE, align='c')
    sp.paste_sprite(bsp, x, y, scale=1 + 0.03 * pk)
    return with_shadow(sp.out(), 20, 10, 40, 0.16)


@lru_cache(maxsize=None)
def render_rewind():
    img = Image.new('RGBA', (W, H), (255, 250, 247, int(0.75 * 255)))
    sp = Sprite(W, 60)
    sp.line_text(W / 2, 0, 60, '↺ Let\'s try that moment again', FK('serif', 30), INK, align='c')
    img.alpha_composite(sp.out(), dest=(0, H // 2 - 30))
    return img


# cursor ------------------------------------------------------------
CURSOR_PATH = 'M4 3 L4 23 L9.5 18 L13 26 L16.5 24.5 L13 16.8 L20.5 16.8 Z'


@lru_cache(maxsize=32)
def cursor_img(scale100):
    """Cursor arrow scaled about (4,4); returns 1x image whose (0,0) is the cursor box origin - (8,8)."""
    s = scale100 / 100
    P = 4
    sp = Sprite(44, 44, ppu=P)
    pts = parse_path(CURSOR_PATH)[0][0]
    pts = [(8 + 4 + (x - 4) * s, 8 + 4 + (y - 4) * s) for x, y in pts]
    # outline: stroke drawn under the fill, half of it hidden by the fill
    sp.polygon(pts, hexc('#222222'))
    sp.polyline(pts + [pts[0]], hexc('#222222'), 1.6 * s, True)
    # inner white fill (inset polygon approximation: shrink toward centroid)
    sp.polygon(inset(pts, 0.8 * s), WHITE)
    img = sp.im.convert('RGBa').resize((44, 44), Image.LANCZOS).convert('RGBA')
    # drop-shadow(0 2px 3px rgba(0,0,0,.3))
    a = img.getchannel('A').filter(ImageFilter.GaussianBlur(1.5)).point(lambda v: int(v * 0.3))
    sh = Image.new('RGBA', img.size, (0, 0, 0, 0)); sh.putalpha(a)
    out = Image.new('RGBA', img.size, (0, 0, 0, 0))
    paste_clip(out, sh, 0, 2)
    out.alpha_composite(img)
    return out


def inset(pts, d):
    """Offset a simple polygon inward by d (miter)."""
    n = len(pts)
    area = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))
    sgn = 1 if area > 0 else -1
    lines = []
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0; L = math.hypot(dx, dy) or 1
        nx, ny = -dy / L * sgn, dx / L * sgn
        lines.append(((x0 + nx * d, y0 + ny * d), (x1 + nx * d, y1 + ny * d)))
    out = []
    for i in range(n):
        (a0, a1), (b0, b1) = lines[i - 1], lines[i]
        d1 = (a1[0] - a0[0], a1[1] - a0[1]); d2 = (b1[0] - b0[0], b1[1] - b0[1])
        den = d1[0] * d2[1] - d1[1] * d2[0]
        if abs(den) < 1e-9:
            out.append(b0); continue
        tt = ((b0[0] - a0[0]) * d2[1] - (b0[1] - a0[1]) * d2[0]) / den
        out.append((a0[0] + d1[0] * tt, a0[1] + d1[1] * tt))
    return out


@lru_cache(maxsize=64)
def ring_img(scale100, alpha100):
    s = scale100 / 100
    size = 60
    sp = Sprite(size, size)
    r = 18 * s
    if r > 0.5:
        sp.circle(size / 2, size / 2, r, None, hexc('#d6385a', int(255 * alpha100 / 100)), min(r, 3 * s))
    return sp.out()


# ------------------------------------------------------------------ frame
def ease_fade(fn, t, d=FADE):
    return trans(fn, t, d, n=12)


def compose(g):
    t = g - INTRO
    frame = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    drawn = False

    def put(img, x, y, op):
        nonlocal drawn
        if op <= 0.004:
            return
        paste_clip(frame, with_opacity(img, op), int(round(x)), int(round(y)))
        drawn = True

    # chapter pill
    op = ease_fade(vis_chapter, t)
    if op > 0:
        ci = -1 if t < 0 else next(i for i, (end, _) in enumerate(CHAPTERS) if t < end)
        txt = 'Design your baby' if t < 0 else CHAPTERS[ci][1]
        img, m = render_chapter(ci + 2, txt)
        put(img, 24 - m, 24 - m - 8 * (1 - op), op)
    # title
    op = ease_fade(vis_title, t)
    if op > 0:
        img, m = card_image('title')
        bw, bh = img.width - 2 * m, img.height - 2 * m
        put(img, W / 2 - bw / 2 - m, H / 2 - bh / 2 + 0.04 * bh * (1 - op) - m, op)
    # creator
    op = ease_fade(vis_creator, t)
    if op > 0:
        img, m = render_creator(creator_frame_state(t))
        x, y = CREATOR_POS
        put(img, x + 20 * (1 - op) - m, y - m, op)
    # bubble
    op = ease_fade(vis_bubble, t)
    if op > 0:
        img, m = render_bubble()
        _, _, bw, bh, bx, by = bubble_layout()
        put(img, bx - m, by + 8 * (1 - op) - m, op)
    # options
    op = ease_fade(vis_options, t)
    if op > 0:
        st = tuple((int(trans(lambda u, i=i: hovered('opt' + 'ABC'[i], u) if i < 3 else False, t, 0.2) * 100),
                    int(trans(lambda u, i=i: opt_picked(i, u), t, 0.2) * 100),
                    int(trans(lambda u, i=i: opt_dim(i, u), t, 0.2) * 100)) for i in range(4))
        img, m = render_options(st)
        x, y = options_pos()
        put(img, x + 20 * (1 - op) - m, y - m, op)
    # said
    op = ease_fade(vis_said, t)
    if op > 0:
        img, _ = render_said(round2(t))
        put(img, W / 2 - img.width / 2, H - 90 - img.height + 10 * (1 - op), op)
    # feedback
    op = ease_fade(vis_feedback, t)
    if op > 0:
        r2 = round2(t)
        fb0 = 28.0 if r2 else 16.0
        ks = tuple(int(round(smooth(fb0 + 0.4 + i * 0.22, fb0 + 1.4 + i * 0.22, t) * 1000)) for i in range(len(INDICATORS)))
        rs = (int(trans(lambda u: hovered('retry', u), t, 0.2) * 100),
              int(trans(lambda u: within(u, 22.3, 23), t, 0.2) * 100))
        img, m = render_feedback(r2, ks, rs)
        x, y = feedback_layout(r2)['pos']
        put(img, x + 20 * (1 - op) - m, y - m, op)
    # rewind
    op = ease_fade(vis_rewind, t)
    if op > 0:
        put(render_rewind(), 0, 0, op)
    # end card
    op = ease_fade(vis_end, t)
    if op > 0:
        img, m = card_image('end')
        bw, bh = img.width - 2 * m, img.height - 2 * m
        put(img, W / 2 - bw / 2 - m, H / 2 - bh / 2 + 0.04 * bh * (1 - op) - m, op)
    # cursor
    op = trans(lambda u: active_move(u) is not None, t, 0.25)
    if op > 0:
        # while fading out keep the last position
        tt = t
        if active_move(t) is None:
            for j in range(1, 13):
                tt = t - 0.25 * j / 12
                if active_move(tt): break
        pos = cursor_pos(tt)
        if pos:
            x, y = pos
            m = active_move(tt)
            dn = trans(cursor_down, tt, 0.12)
            # ring animation (.45s ease-out from the moment .down is added)
            if cursor_down(tt):
                t_on = tt
                while cursor_down(t_on - 1 / 96) and t_on > tt - 3:
                    t_on -= 1 / 96
                p = (tt - t_on) / 0.45
                if p < 1:
                    e = EASE_OUT(p)
                    rimg = ring_img(int(round(lerp(0.3, 1.4, e) * 100)), int(round((1 - e) * 100)))
                    put(rimg, x + 4 - 30, y + 4 - 30, op)
            cimg = cursor_img(int(round(lerp(1, 0.8, dn) * 100)))
            put(cimg, x - 8, y - 8, op)
    return frame if drawn else None


# ------------------------------------------------------------------ main
_BLANK = None


def blank_bytes():
    global _BLANK
    if _BLANK is None:
        import io
        b = io.BytesIO()
        Image.new('RGBA', (W, H), (0, 0, 0, 0)).save(b, 'PNG', optimize=True)
        _BLANK = b.getvalue()
    return _BLANK


def render_frame(f):
    g = (f - 1) / FPS
    img = compose(g)
    path = os.path.join(OUT_DIR, '%04d.png' % f)
    if img is None:
        with open(path, 'wb') as fh:
            fh.write(blank_bytes())
    else:
        img.save(path, 'PNG', compress_level=1)
    return f


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--start', type=int, default=1)
    ap.add_argument('--end', type=int, default=NFRAMES)
    ap.add_argument('--every', type=int, default=1)
    ap.add_argument('--jobs', type=int, default=min(4, os.cpu_count() or 4))  # 4 = M2 Air performance cores
    a = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    frames = list(range(max(1, a.start), min(NFRAMES, a.end) + 1, max(1, a.every)))
    t0 = time.time()
    # contiguous chunks per worker keep the lru caches warm
    if a.jobs > 1 and len(frames) > 8:
        chunk = max(1, len(frames) // (a.jobs * 4))
        with Pool(a.jobs) as pool:
            for i, _ in enumerate(pool.imap(render_frame, frames, chunksize=chunk)):
                if (i + 1) % 100 == 0:
                    print('  %d/%d frames (%.1fs)' % (i + 1, len(frames), time.time() - t0), flush=True)
    else:
        for f in frames:
            render_frame(f)
    print('rendered %d frames to %s in %.1fs' % (len(frames), OUT_DIR, time.time() - t0))


if __name__ == '__main__':
    main()
