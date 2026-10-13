"""Cinematic 2D animation renderer (Pillow + numpy only, no downloads, no GPU).

Multi-character scenes, parallax backgrounds, camera moves, lighting/bloom, colour grade,
vignette, film grain, rain/lightning/fireflies. Works in three layouts:
  landscape : 2.39:1 letterboxed cinema frame inside 16:9   (long videos)
  portrait  : full 9:16 frame                                 (Shorts)
  thumb     : clean 16:9 frame without bars                  (thumbnails)
"""
import math
import random as _random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

SS = 2                      # supersampling for backgrounds
WW = 2300                   # world width (world units)
HORIZON, FEET, WCY = 392, 468, 268
K = 0.58                    # character scale (world units per design unit)

LAYOUTS = {
    "landscape": dict(AW=1280, AH=536, FW=1280, FH=720, S=1.0, fg_h=190, sky_len=392,
                      spacing={1: 0, 2: 420, 3: 340, 4: 290, 5: 250}, sun_dx=410, ff_wide=.88, ff_med=.83, fh=.43,
                      zoom=dict(wide=1.0, medium=1.32, close=1.75, two=1.18)),
    "portrait": dict(AW=720, AH=1280, FW=720, FH=1280, S=1.05, fg_h=330, sky_len=800,
                     spacing={1: 0, 2: 300, 3: 235, 4: 195, 5: 170}, sun_dx=170, ff_wide=.62, ff_med=.66, fh=.34,
                     zoom=dict(wide=0.95, medium=1.45, close=2.1, two=1.2)),
    "thumb": dict(AW=1280, AH=720, FW=1280, FH=720, S=1.0, fg_h=220, sky_len=520,
                  spacing={1: 0, 2: 420, 3: 340, 4: 290, 5: 250}, sun_dx=410, ff_wide=.88, ff_med=.80, fh=.42,
                  zoom=dict(wide=1.0, medium=1.32, close=1.75, two=1.18)),
}


class _Layout:
    pass


LY = _Layout()


def set_layout(name: str) -> None:
    LY.__dict__.update(LAYOUTS[name])
    LY.name = name
    LY.BAR = (LY.FH - LY.AH) // 2 if name == "landscape" else 0


set_layout("landscape")

# ------------------------------------------------------------------ palettes
PAL = {
    "village_day": dict(sky=((70, 150, 232), (252, 228, 180)), far=(150, 172, 200), mid=(150, 160, 100), tree=(78, 98, 58), ground=(198, 160, 110),
                        ground2=(170, 134, 92), wall=(226, 200, 160), roof=(172, 88, 62), fg=(96, 78, 48), shadow=(140, 108, 72),
                        tint=(1.03, 1.0, 0.94), con=1.07, vig=0.36, bloom=0.30, sun=(1560, 120), cl=("w", 4), birds=True, dry=True, lit=False),
    "sunset": dict(sky=((70, 50, 125), (255, 160, 85)), far=(135, 75, 115), mid=(105, 60, 100), tree=(55, 32, 72), ground=(130, 85, 85),
                   ground2=(105, 66, 72), wall=(170, 115, 110), roof=(90, 45, 65), fg=(44, 24, 52), shadow=(80, 50, 64),
                   tint=(1.06, 0.97, 0.93), con=1.08, vig=0.42, bloom=0.45, sun=(1150, 378), cl=("d", 3), birds=True, dry=True, lit=True),
    "rain": dict(sky=((32, 42, 62), (95, 110, 130)), far=(58, 72, 92), mid=(46, 64, 72), tree=(24, 40, 42), ground=(62, 76, 82),
                 ground2=(48, 60, 68), wall=(120, 118, 118), roof=(60, 52, 56), fg=(16, 26, 28), shadow=(36, 46, 52),
                 tint=(0.92, 0.99, 1.08), con=1.1, vig=0.5, bloom=0.5, cl=("g", 14), rain=True, lit=True),
    "night": dict(sky=((4, 8, 30), (36, 46, 100)), far=(24, 34, 70), mid=(20, 30, 60), tree=(10, 18, 34), ground=(28, 44, 52),
                  ground2=(20, 34, 40), wall=(70, 70, 100), roof=(35, 32, 60), fg=(8, 14, 22), shadow=(14, 24, 30),
                  tint=(0.9, 0.97, 1.1), con=1.08, vig=0.5, bloom=0.6, moon=(1500, 130), stars=True, fireflies=True, cl=("n", 3), lit=True),
    "forest": dict(sky=((60, 140, 170), (215, 238, 205)), far=(110, 150, 150), mid=(62, 122, 82), tree=(30, 92, 52), ground=(72, 124, 62),
                   ground2=(58, 104, 52), wall=(0, 0, 0), roof=(0, 0, 0), fg=(20, 62, 32), shadow=(40, 88, 46),
                   tint=(0.98, 1.04, 0.98), con=1.07, vig=0.42, bloom=0.30, sun=(1560, 130), cl=("w", 3), birds=True, huts=False, trees=15, big_trees=True),
    "space": dict(sky=((6, 4, 24), (62, 30, 112)), far=(52, 30, 92), mid=(64, 46, 104), tree=(0, 0, 0), ground=(94, 92, 112),
                  ground2=(74, 72, 94), wall=(0, 0, 0), roof=(0, 0, 0), fg=(0, 0, 0), shadow=(58, 56, 78),
                  tint=(0.96, 0.97, 1.08), con=1.1, vig=0.5, bloom=0.5, stars=True, planet=(1500, 140), huts=False, trees=0, nofg=True, cl=("n", 0)),
}
SETTINGS = list(PAL)
CLOUDCOL = dict(w=(255, 255, 255), d=(98, 62, 98), g=(66, 76, 92), n=(40, 52, 95))

_r = _random.Random(11)
STARS = [(_r.uniform(0, WW), _r.uniform(-800, 300), _r.uniform(0, 6.3), _r.uniform(1.4, 3.2)) for _ in range(260)]
CLOUDS = [(_r.uniform(0, WW), _r.uniform(-260, 190), _r.uniform(0.8, 1.5), _r.uniform(6, 16)) for _ in range(18)]
RAIN = [(_r.uniform(0, 1500), _r.uniform(0, 1400), _r.uniform(0.7, 1.4), _r.uniform(16, 30), _r.randint(60, 150)) for _ in range(420)]
FIREFLY = [(_r.uniform(200, WW - 200), _r.uniform(250, 440), _r.uniform(0, 6.3)) for _ in range(30)]
BIRDS = [(_r.uniform(0, WW), _r.uniform(-60, 200), _r.uniform(18, 36)) for _ in range(5)]
CRACKS = [[(x + _r.uniform(-30, 30) * k, HORIZON + 30 + k * 26) for k in range(7)] for x in range(0, WW, 120)]
GRASS = [(i * 36 + (i * 37 % 19), 22 + (i * 53 % 34)) for i in range(-6, WW // 36 + 6)]
PUDDLES = [(1000, 440, 70), (1500, 455, 90), (700, 430, 55), (1850, 425, 60), (400, 450, 80)]
BIG = 3000

# ------------------------------------------------------------------ camera / layers
def lay(cam, f):
    cx, cy, z = cam
    return (WW / 2 + (cx - WW / 2) * f, WCY + (cy - WCY) * f, 1 + (z - 1) * f)


def P(l, x, y):
    return ((x - l[0]) * l[2] * LY.S + LY.AW / 2) * SS, ((y - l[1]) * l[2] * LY.S + LY.AH / 2) * SS


def poly(d, l, pts, fill):
    d.polygon([P(l, x, y) for x, y in pts], fill=fill)


def ell(d, l, x, y, rx, ry, fill):
    cx, cy = P(l, x, y); z = l[2] * LY.S * SS
    d.ellipse([cx - rx * z, cy - ry * z, cx + rx * z, cy + ry * z], fill=fill)


def mix(a, b, t):
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))


def far_ridge(x): return 330 - 38 * math.sin(x * 0.0042 + 1.3) - 22 * math.sin(x * 0.011 + 0.4)
def mid_ridge(x): return 386 - 22 * math.sin(x * 0.006 + 2) - 10 * math.sin(x * 0.017)


_gradcol = {}


def sky_frame(name, hs):
    """Vertical sky gradient whose bottom colour sits exactly at the horizon row `hs` (screen px)."""
    key = (name, LY.AH, LY.sky_len)
    if key not in _gradcol:
        top, bot = PAL[name]["sky"]
        rows = 2 * LY.AH * SS
        hr = int(1.5 * LY.AH * SS)
        u = np.clip((np.arange(rows) - (hr - LY.sky_len * SS)) / (LY.sky_len * SS), 0, 1) ** 1.3
        _gradcol[key] = (np.array(top)[None, :] * (1 - u[:, None]) + np.array(bot)[None, :] * u[:, None]).astype(np.uint8)
    col = _gradcol[key]
    hr = int(1.5 * LY.AH * SS)
    s0 = int(max(0, min(hr - hs * SS, len(col) - LY.AH * SS)))
    seg = col[s0:s0 + LY.AH * SS]
    return Image.fromarray(np.repeat(seg[:, None, :], LY.AW * SS, axis=1))


def gl(glows, l, x, y, r, col, s=1.0):
    sx, sy = P(l, x, y); glows.append((sx / SS, sy / SS, r * l[2] * LY.S, col, s))


def bg_frame(name, t, cam, prog, chars_x, glows):
    p = PAL[name]
    L0, L1, L2, L3, L4, L5 = (lay(cam, f) for f in (0.04, 0.12, 0.2, 0.45, 0.75, 1.0))
    hs = P(L5, 0, HORIZON)[1] / SS
    img = sky_frame(name, hs); d = ImageDraw.Draw(img)
    land = LY.name != "portrait"
    if p.get("stars"):
        for x, y, ph, r in STARS:
            sx, sy = P(L0, x, y); rr = r * (0.6 + 0.4 * math.sin(t * 2 + ph)) * SS * 0.8
            if -10 < sx < LY.AW * SS + 10 and -10 < sy < LY.AH * SS:
                d.ellipse([sx - rr, sy - rr, sx + rr, sy + rr], fill=(255, 255, 235))
    if p.get("sun"):
        sx = p["sun"][0] if name == "sunset" else 1150 + LY.sun_dx
        sy = p["sun"][1]; big = name == "sunset"
        rr = 125 if big else 62
        ell(d, L0, sx, sy, rr, rr, (255, 225, 150) if big else (255, 240, 190)); ell(d, L0, sx, sy, rr * .74, rr * .74, (255, 248, 205))
        gl(glows, L0, sx, sy, 300 if big else 130, (255, 190, 110) if big else (255, 235, 170), 0.8)
    if p.get("moon"):
        mx = 1150 + LY.sun_dx; my = p["moon"][1]
        ell(d, L0, mx, my, 52, 52, (246, 241, 216)); ell(d, L0, mx + 24, my - 12, 46, 46, (16, 24, 66))
        gl(glows, L0, mx, my, 200, (170, 190, 255), 0.7)
    if p.get("planet"):
        px = 1150 + LY.sun_dx
        ell(d, L0, px, p["planet"][1], 90, 90, (225, 130, 90)); ell(d, L0, px - 26, p["planet"][1] - 22, 22, 22, (205, 108, 72))
        ell(d, L0, px + 30, p["planet"][1] + 30, 30, 18, (210, 118, 80))
        gl(glows, L0, px, p["planet"][1], 240, (255, 150, 110), 0.35)
    kind, cnt = p["cl"]
    if kind == "d":
        cnt = 3 + int(10 * min(1, prog))
    col = CLOUDCOL[kind]; bigc = 1.7 if kind == "g" else 1.0
    for i, (x0, y0, sc, sp) in enumerate(CLOUDS[:cnt]):
        x = (x0 + t * sp) % (WW + 600) - 300; y = y0 * (0.7 if kind == "g" else 1.0)
        for dx, dy, rx, ry in ((0, 0, 70, 30), (-52, 10, 48, 24), (54, 10, 52, 24), (0, -20, 46, 30)):
            ell(d, L1, x + dx * sc * bigc, y + dy * sc * bigc, rx * sc * bigc, ry * sc * bigc, col)
    if p.get("birds"):
        for x0, y0, sp in BIRDS:
            x = (x0 + t * sp) % (WW + 400) - 200; y = y0 + math.sin(t * 0.9 + x0) * 12
            fl = math.sin(t * 9 + x0) * 8; c = (40, 30, 50) if name == "sunset" else (60, 70, 90)
            for sg in (-1, 1):
                d.line([P(L2, x, y), P(L2, x + sg * 15, y - fl)], fill=c, width=3)
    poly(d, L2, [(x, far_ridge(x)) for x in range(-300, WW + 301, 40)] + [(WW + 300, BIG), (-300, BIG)], p["far"])
    poly(d, L3, [(x, mid_ridge(x)) for x in range(-300, WW + 301, 40)] + [(WW + 300, BIG), (-300, BIG)], p["mid"])
    if p.get("huts", True):
        for x in range(250, WW, 400):
            y = mid_ridge(x) + 10
            poly(d, L3, [(x - 60, y - 64), (x + 60, y - 64), (x + 60, y), (x - 60, y)], p["wall"])
            poly(d, L3, [(x - 74, y - 64), (x + 74, y - 64), (x + 40, y - 102), (x - 40, y - 102)], p["roof"])
            poly(d, L3, [(x - 12, y - 40), (x + 12, y - 40), (x + 12, y), (x - 12, y)], mix(p["wall"], (0, 0, 0), 0.55))
            wc = (255, 205, 110) if p["lit"] else mix(p["wall"], (0, 0, 0), 0.4)
            poly(d, L3, [(x + 28, y - 52), (x + 46, y - 52), (x + 46, y - 34), (x + 28, y - 34)], wc)
            if p["lit"]:
                gl(glows, L3, x + 37, y - 43, 56, (255, 180, 80), 0.9)
    sway = 9 if name == "rain" else 3
    ntrees = p.get("trees", 9)
    for i in range(ntrees):
        x = 120 + i * (2300 // max(1, ntrees)) + (i * 41 % 60); y = 412; sw = math.sin(t * 1.2 + i) * sway
        big = p.get("big_trees")
        th = 110 if big else 78
        poly(d, L4, [(x - 8, y), (x + 8, y), (x + 5, y - th), (x - 5, y - th)], mix(p["tree"], (0, 0, 0), 0.35))
        r = 52 if big else (28 if p.get("dry") else 42)
        for dx, dy, rr in ((0, -th - 14, r), (-r * 0.8, -th, r * 0.8), (r * 0.8, -th, r * 0.8)):
            ell(d, L4, x + dx + sw, y + dy, rr, rr * 0.9, p["tree"])
    poly(d, L5, [(-600, HORIZON), (WW + 600, HORIZON), (WW + 600, BIG), (-600, BIG)], p["ground"])
    poly(d, L5, [(-600, HORIZON), (WW + 600, HORIZON), (WW + 600, HORIZON + 16), (-600, HORIZON + 16)], mix(p["ground"], p["sky"][1], 0.35))
    poly(d, L5, [(1090, HORIZON), (1210, HORIZON), (1700, BIG), (600, BIG)], p["ground2"])
    if p.get("dry"):
        for cr in CRACKS:
            d.line([P(L5, x + (k % 2) * 14, y) for k, (x, y) in enumerate(cr)], fill=mix(p["ground2"], (0, 0, 0), 0.25), width=int(2 * SS))
    if p.get("rain"):
        for k, (x, y, rr) in enumerate(PUDDLES):
            ell(d, L5, x, y, rr, rr * 0.16, mix(p["ground"], (130, 150, 175), 0.5))
            q = (t * 0.9 + k * 0.37) % 1.0
            cx, cy = P(L5, x, y); z = L5[2] * LY.S * SS
            d.ellipse([cx - rr * q * 0.7 * z, cy - rr * q * 0.12 * z, cx + rr * q * 0.7 * z, cy + rr * q * 0.12 * z], outline=(190, 205, 225), width=SS)
    for cx in chars_x:
        ell(d, L5, cx, FEET + 5, 56, 10, p["shadow"])
    if p.get("fireflies"):
        for i, (x0, y0, ph) in enumerate(FIREFLY):
            x = x0 + 40 * math.sin(t * 0.6 + ph); y = y0 + 25 * math.sin(t * 0.9 + ph * 2); b = 0.5 + 0.5 * math.sin(t * 2.2 + ph * 3)
            ell(d, L5, x, y, 2.6, 2.6, (230, 255, 150)); gl(glows, L5, x, y, 26, (210, 255, 120), 0.8 * b)
    if name in ("village_day", "sunset", "forest"):
        for i in range(40):
            x = (i * 131 + t * 14) % (WW + 200) - 100; y = 300 + (i * 53) % 150 - (t * 6 + i * 9) % 40
            ell(d, L5, x, y, 1.8, 1.8, (255, 245, 210))
    return img


def fg_overlay(name, t, cam):
    p = PAL[name]
    if p.get("nofg"):
        return None
    Lf = lay(cam, 1.2); Hh = LY.fg_h
    ov = Image.new("RGBA", (LY.AW * SS, Hh * SS), (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
    z = min(Lf[2] * LY.S, 1.35) * SS
    col = mix(p["fg"], p["ground"], 0.22) + (255,)
    amp = 7 if name == "rain" else 3
    for i, (x, h) in enumerate(GRASS):
        bx = P(Lf, x, 0)[0]; by = Hh * SS + 4 * SS; sw = math.sin(t * 1.5 + i * 0.7) * amp
        w = 7 * z; hh = h * 0.8 * z
        d.polygon([(bx - w, by), (bx + w, by), (bx + w * .6 + sw * z * .6, by - hh * .6), (bx + sw * z, by - hh), (bx - w * .5 + sw * z * .6, by - hh * .55)], fill=col)
    return ov.reduce(SS)


def rain_overlay(t):
    ov = Image.new("RGBA", (LY.AW, LY.AH), (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
    for x0, y0, sp, ln, al in RAIN:
        x = (x0 - t * 110 * sp) % (LY.AW + 200) - 100; y = (y0 + t * 880 * sp) % (LY.AH + 120) - 60
        d.line([(x, y), (x - ln * 0.22, y + ln)], fill=(205, 220, 240, al), width=2 if sp > 1.15 else 1)
    return ov


# ------------------------------------------------------------------ characters
AGE = dict(child=dict(leg=56, body=122, bw=98, hr=92), adult=dict(leg=92, body=186, bw=142, hr=80), elder=dict(leg=82, body=170, bw=136, hr=77))
CW, CHH = 420, 520


def make_sprite(ch, t, speaking, amp, emo, ph, nod, RS=1.2):
    a = AGE[ch.get("age", "adult")]; leg, body, bw, hr = a["leg"], a["body"], a["bw"], a["hr"]
    skin = _rgb(ch.get("skin", "#e8b98a")); shirt = _rgb(ch.get("color", "#3b82f6")); hair = _rgb(ch.get("hair", "#2b1b17"))
    pants = _rgb(ch.get("pants", "#334155")); dark = (55, 38, 38)
    img = Image.new("RGBA", (int(CW * RS), int(CHH * RS)), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    X = lambda x: (CW / 2 + x) * RS
    Y = lambda y: (CHH - 20 + y) * RS

    def e(cx, cy, rx, ry, fill=None, outline=None, w=1):
        d.ellipse([X(cx - rx), Y(cy - ry), X(cx + rx), Y(cy + ry)], fill=fill, outline=outline, width=max(1, int(w * RS)))

    def ln(x0, y0, x1, y1, w, fill):
        d.line([X(x0), Y(y0), X(x1), Y(y1)], fill=fill, width=max(1, int(w * RS))); e(x0, y0, w / 2, w / 2, fill); e(x1, y1, w / 2, w / 2, fill)

    def pg(pts, fill): d.polygon([(X(x), Y(y)) for x, y in pts], fill=fill)
    bob = math.sin(t * 2.4 + ph) * 2.5 + (abs(math.sin(t * 9)) * amp * 6 if speaking else 0)
    top = -(leg + body) - bob
    aw = 22 if ch.get("age") == "child" else 28
    if ch.get("outfit") == "dress":
        for sx in (-18, 18): ln(sx, -leg * 0.5, sx, -8, 20, skin); e(sx + 6, -5, 22, 11, (50, 40, 50))
        pg([(-bw * .42, top + 8), (bw * .42, top + 8), (bw * .8, -leg * .42), (-bw * .8, -leg * .42)], shirt)
        e(0, top + 30, bw * .44, 36, shirt)
        pg([(-bw * .8, -leg * .42), (bw * .8, -leg * .42), (bw * .82, -leg * .42 + 16), (-bw * .82, -leg * .42 + 16)], mix(shirt, (255, 255, 255), 0.25))
        if ch.get("shawl"):
            pg([(-bw * .45, top + 6), (-bw * .15, top), (bw * .5, -leg - 20), (bw * .2, -leg - 30)], _rgb(ch["shawl"]))
    else:
        lw = 34 if ch.get("age") != "child" else 26
        for sx in (-bw * .22, bw * .22): ln(sx, -leg, sx, -10, lw, pants); e(sx + 7, -6, lw * .82, 13, (40, 36, 48))
        d.rounded_rectangle([X(-bw / 2), Y(top), X(bw / 2), Y(-leg + 12)], radius=bw * .36 * RS, fill=shirt)
        pg([(-14, top + 2), (14, top + 2), (0, top + 28)], mix(shirt, (255, 255, 255), 0.35))
    sh_y = top + 30
    bx0 = -bw / 2 - 18 + math.sin(t * 2 + ph) * 3
    ln(-bw / 2 + 8, sh_y, bx0, -leg - body * .3, aw, shirt); e(bx0, -leg - body * .3, aw * .7, aw * .7, skin)
    if speaking:
        hx2 = bw / 2 + 40 + math.sin(t * 7) * 20 * amp; hy2 = sh_y + 20 - amp * 70 + math.sin(t * 7 + 1) * 12 * amp
    else:
        hx2 = bw / 2 + 18; hy2 = -leg - body * .3 + math.sin(t * 2 + ph) * 3
    ln(bw / 2 - 8, sh_y, hx2, hy2, aw, shirt); e(hx2, hy2, aw * .7, aw * .7, skin)
    hxo = 6 if ch.get("age") == "elder" else 0
    hy = top - hr * .8 - nod
    style = ch.get("hairstyle", "short"); fs = hr / 88
    if style == "bun": e(hxo, hy - 6, hr * 1.06, hr * 1.08, hair); e(hxo, hy - hr * 1.1, hr * .4, hr * .4, hair)
    elif style == "long": d.rounded_rectangle([X(hxo - hr * 1.05), Y(hy - hr * .9), X(hxo + hr * 1.05), Y(hy + hr * 1.9)], radius=hr * .6 * RS, fill=hair)
    elif style == "pigtails":
        for sg in (-1, 1): e(hxo + sg * hr * 1.08, hy + hr * .3, hr * .28, hr * .5, hair)
    for sg in (-1, 1): e(hxo + sg * hr * .97, hy + 4, hr * .17, hr * .22, skin)
    e(hxo, hy, hr, hr * 1.02, skin)
    if style == "cap":
        cc = _rgb(ch.get("hatcolor", "#ef4444")); e(hxo, hy - hr * .36, hr * 1.03, hr * .74, cc); e(hxo, hy + hr * .27, hr * .9, hr * .74, skin)
        e(hxo + hr * .66, hy - hr * .23, hr * .59, hr * .12, cc); e(hxo, hy - hr * 1.08, hr * .1, hr * .1, (255, 255, 255))
    elif style == "pagdi":
        cc = _rgb(ch.get("hatcolor", "#f8fafc")); e(hxo, hy - hr * .5, hr * 1.14, hr * .8, cc); e(hxo, hy + hr * .3, hr * .9, hr * .74, skin)
        for k in range(3): ln(hxo - hr * .95, hy - hr * (.2 + .3 * k), hxo + hr * .95, hy - hr * (.45 + .3 * k), 5, mix(cc, (90, 90, 110), 0.35))
        e(hxo + hr * .95, hy - hr * .75, hr * .3, hr * .22, cc)
    else:
        e(hxo, hy - hr * .36, hr * 1.03, hr * .74, hair); e(hxo, hy + hr * .27, hr * .9, hr * .74, skin)
    off = 7 * fs; ex = [hxo - 34 * fs + off, hxo + 34 * fs + off]; ey = hy - 4 * fs
    for sg in (-1, 1): e(hxo + sg * 58 * fs + off, hy + 28 * fs, 14 * fs, 10 * fs, (255, 165, 160))
    blink = ((t + ph * .8) % 3.6) < 0.13
    big = (1.22 if emo == "surprised" else (0.82 if emo == "sad" else 1.0)) * (1.1 if ch.get("age") == "child" else 1.0)
    for x in ex:
        e(x, ey, 19 * fs, 2.6 if blink else 22 * fs * big, (255, 255, 255))
        if not blink: e(x + 5 * fs, ey + 2, 10 * fs, 10 * fs, (45, 30, 30)); e(x + 8 * fs, ey - 3, 3.5 * fs, 3.5 * fs, (255, 255, 255))
    by0 = hy - 36 * fs
    lift = {"surprised": (-14, -14), "happy": (-5, -5), "thinking": (2, -12)}.get(emo, (0, 0))
    for k, x in enumerate(ex):
        a0, a1 = (((5, -5) if k == 0 else (-5, 5)) if emo == "sad" else (lift[k], lift[k]))
        ln(x - 17 * fs, by0 + a0, x + 17 * fs, by0 + a1, 5, hair if ch.get("age") == "elder" else dark)
    if ch.get("glasses"):
        for x in ex: e(x, ey, 28 * fs, 28 * fs, outline=(40, 40, 70), w=4)
        ln(ex[0] + 28 * fs, ey, ex[1] - 28 * fs, ey, 4, (40, 40, 70))
    mx, my = hxo + off, hy + 46 * fs
    if ch.get("mustache"):
        for sg in (-1, 1): e(mx + sg * 15 * fs, my - 14 * fs, 21 * fs, 8 * fs, hair)
    if speaking:
        ry = (4 + amp * 24) * fs; rx = (18 - amp * 4 + (5 if emo == "happy" else 0)) * fs
        e(mx, my + ry * .3, rx, ry, (140, 35, 50))
        if ry > 14 * fs: e(mx, my + ry * .75, rx * .6, ry * .3, (240, 120, 130))
    elif emo == "surprised": e(mx, my + 4, 11 * fs, 14 * fs, (140, 35, 50))
    else:
        w = (26 if emo == "happy" else 20) * fs
        if emo == "sad": d.arc([X(mx - w), Y(my + 2), X(mx + w), Y(my + w * 1.1)], 200, 340, fill=(110, 40, 50), width=max(1, int(6 * RS)))
        else: d.arc([X(mx - w), Y(my - w * .55), X(mx + w), Y(my + w * .55)], 20, 160, fill=(110, 40, 50), width=max(1, int(6 * RS)))
    if ch.get("bindi"): e(hxo + off * .5, hy - hr * .42, 5 * fs, 5 * fs, (200, 30, 40))
    if ch.get("age") == "elder":
        for k in (-1, 1): ln(hxo + k * 20 * fs, hy - hr * .5, hxo + k * 42 * fs, hy - hr * .5, 2, mix(skin, (0, 0, 0), 0.25))
    return img


def _rgb(h):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ------------------------------------------------------------------ frame composition
_vig = {}


def vig_mask(s):
    key = (s, LY.AW, LY.AH)
    if key not in _vig:
        yy, xx = np.mgrid[0:LY.AH, 0:LY.AW].astype(np.float32)
        r = ((xx / LY.AW - .5) ** 2 * 1.3 + (yy / LY.AH - .5) ** 2 * 1.9)
        _vig[key] = (1 - s * np.clip(r * 1.7, 0, 1) ** 1.4)[:, :, None].astype(np.float32)
    return _vig[key]


_grain_cache = {}


def grain(i):
    key = (LY.AW, LY.AH)
    if key not in _grain_cache:
        _grain_cache[key] = np.random.default_rng(1).standard_normal((4, LY.AH, LY.AW), dtype=np.float32)[:, :, :, None] * 0.012
    return _grain_cache[key][i % 4]


def compose(plan, t, f, si, cam, cur, flash, fade, intro=False):
    """Render one frame -> uint8 array (FH, FW, 3)."""
    sc = plan["scenes"][si]; name = sc["setting"]; p = PAL[name]
    prog = (t - sc["t0"]) / max(0.1, sc["t1"] - sc["t0"])
    cx, cy, z = cam
    cx += 3 * math.sin(t * .9); cy += 2 * math.sin(t * 1.3 + 1)
    cam = (cx, cy, z)
    glows = []
    cast = sc["cast"]; line = plan["tl"][cur] if cur >= 0 else None
    spk = line["who"] if line and t < line["start"] + line["dur"] else None
    xs = {c: sc["cast_x"][c] for c in cast}
    base = bg_frame(name, t, cam, prog, list(xs.values()), glows).reduce(SS).convert("RGB")
    L5 = lay(cam, 1.0)
    for c in cast:
        ch = plan["chars"][c]; sp = spk == c; amp = 0.0
        if sp:
            env = line["env"]; amp = float(env[min(len(env) - 1, int((t - line["start"]) * plan["fps"]))])
        if spk is not None and spk != c and spk in xs: tx = xs[spk]
        elif sp: tx = min((v for k, v in xs.items() if k != c), key=lambda v: abs(v - xs[c]), default=xs[c] + 1)
        else: tx = 1150
        face = 1 if tx >= xs[c] else -1
        emo = "neutral"
        if line and line["who"] != -1:
            emo = line["emo"] if sp else (line["emo"] if line["emo"] in ("happy", "sad", "surprised") else "neutral")
        if intro: emo = "neutral"
        nod = 3 * math.sin(t * 3 + c) if (not sp and spk is not None and emo != "neutral") else 0
        need = K * ch.get("scale", 1.0) * z * LY.S
        rs = min(1.5, max(0.7, need * 1.5))
        spr = make_sprite(ch, t, sp, amp, emo, c * 1.7, nod, rs)
        if face < 0: spr = ImageOps.mirror(spr)
        s = need / rs
        sx, sy = P(L5, xs[c], FEET); sx /= SS; sy /= SS
        w, h = int(spr.width * s), int(spr.height * s)
        if sx + w < -50 or sx - w > LY.AW + 50: continue
        small = spr.resize((max(1, w), max(1, h)), Image.BILINEAR)
        base.paste(small, (int(sx - CW / 2 * rs * s), int(sy - (CHH - 20) * rs * s)), small)
    fg = fg_overlay(name, t, cam)
    if fg is not None: base.paste(fg, (0, LY.AH - fg.height), fg)
    if p.get("rain"):
        ov = rain_overlay(t); base.paste(ov, (0, 0), ov)
    G = Image.new("RGB", (LY.AW // 2, LY.AH // 2)); gd = ImageDraw.Draw(G)
    for x, y, r, col, s_ in glows:
        c = tuple(min(255, int(v * s_)) for v in col)
        gd.ellipse([x / 2 - r / 2, y / 2 - r / 2, x / 2 + r / 2, y / 2 + r / 2], fill=c)
    bloom = np.asarray(G.filter(ImageFilter.GaussianBlur(10)).resize((LY.AW, LY.AH), Image.BILINEAR), dtype=np.float32) / 255
    arr = np.asarray(base, dtype=np.float32) / 255
    arr = arr + bloom * p["bloom"]
    arr = (arr - .5) * p["con"] + .5
    arr = arr * np.array(p["tint"], dtype=np.float32)
    lum = arr.mean(2, keepdims=True)
    arr[..., 2:3] += (1 - lum) * .035; arr[..., 0:1] += lum * .025
    arr = arr * vig_mask(p["vig"]) + grain(f)
    arr += flash * .5
    arr *= fade
    out = np.zeros((LY.FH, LY.FW, 3), np.uint8)
    out[LY.BAR:LY.BAR + LY.AH] = (np.clip(arr, 0, 1) * 255).astype(np.uint8)
    return out


# ------------------------------------------------------------------ worker entry points (multiprocessing)
_PL = None


def init_worker(plan):
    global _PL
    _PL = plan
    set_layout(plan["layout"])


def render_frame(f):
    P_ = _PL; si = int(P_["fscene"][f])
    if si < 0:
        return bytes(LY.FW * LY.FH * 3)
    t = f / P_["fps"]
    intro = si == 0 and int(P_["fline"][f]) < 0
    return compose(P_, t, f, si, tuple(P_["cam"][f]), int(P_["fline"][f]), float(P_["flash"][f]), float(P_["fade"][f]), intro).tobytes()
