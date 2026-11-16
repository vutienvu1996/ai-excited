#!/usr/bin/env python3
"""The Whale That Outgrew Its Snow Globe — ai-excited-01 entry.

Draws the whole poster procedurally with the Python standard library only:
a hand-written PNG encoder (zlib + struct), a small span rasterizer
(gradient sky, discs, ellipses, scanline polygons, thick polylines,
Catmull-Rom spine + tapered disc-tube whale), and a hand-made 5x7
bitmap font for the single word "WOW!".

Deterministic: one fixed seed, no time, no network, no input files.
Writes $MAKEFUN_OUTPUT_DIR/entry.png (else /output/entry.png).
"""
import math
import os
import random
import struct
import zlib

W, H = 1024, 1024
SEED = 20261117
rng = random.Random(SEED)

# ---------------------------------------------------------------- palette
INK       = (16, 28, 54)      # near-black navy (outlines, text)
SKY_TOP   = (11, 16, 48)      # deep indigo
SKY_MID   = (14, 38, 74)
SKY_LOW   = (16, 66, 84)      # teal near the desk
WOOD      = (74, 46, 27)
WOOD_DARK = (46, 27, 15)
WOOD_LINE = (38, 22, 12)
GOLD      = (245, 184, 30)
GOLD_HI   = (255, 214, 90)
GOLD_RAY  = (247, 197, 49)
ORANGE    = (232, 114, 42)
WHALE     = (46, 95, 143)     # steel blue body
WHALE_DK  = (31, 74, 115)     # fins / shading
SHEEN     = (91, 147, 196)    # back sheen
BELLY     = (223, 241, 251)   # ice-white belly
GLASS     = (207, 232, 245)
WATER     = (43, 122, 153)
ISLAND    = (20, 88, 110)
LIGHT_RED = (210, 59, 46)
BEAM      = (255, 230, 163)
SPRAY_W   = (255, 255, 255)
SPRAY_C   = (159, 220, 245)
SPRAY_B   = (111, 195, 232)

buf = bytearray(W * H * 3)


# ---------------------------------------------------------------- rasterizer
def hspan(y, x0, x1, color):
    if y < 0 or y >= H:
        return
    x0 = max(0, int(x0))
    x1 = min(W - 1, int(x1))
    if x1 < x0:
        return
    base = (y * W + x0) * 3
    buf[base:base + (x1 - x0 + 1) * 3] = bytes(color) * (x1 - x0 + 1)


def rect(x0, y0, w, h, color):
    for y in range(int(y0), int(y0 + h)):
        hspan(y, x0, x0 + w - 1, color)


def blend_px(x, y, color, a):
    if x < 0 or x >= W or y < 0 or y >= H:
        return
    i = (y * W + x) * 3
    buf[i] = int(buf[i] + (color[0] - buf[i]) * a)
    buf[i + 1] = int(buf[i + 1] + (color[1] - buf[i + 1]) * a)
    buf[i + 2] = int(buf[i + 2] + (color[2] - buf[i + 2]) * a)


def disc(cx, cy, r, color):
    r = int(r)
    if r <= 0:
        return
    for y in range(max(0, int(cy) - r), min(H, int(cy) + r + 1)):
        dy = y - cy
        dx = int(max(0.0, r * r - dy * dy) ** 0.5)
        hspan(y, cx - dx, cx + dx, color)


def ellipse(cx, cy, rx, ry, color):
    rx, ry = int(rx), int(ry)
    if rx <= 0 or ry <= 0:
        return
    for y in range(max(0, int(cy) - ry), min(H, int(cy) + ry + 1)):
        dy = (y - cy) / ry
        dx = int(rx * max(0.0, 1.0 - dy * dy) ** 0.5)
        hspan(y, cx - dx, cx + dx, color)


def poly(pts, color):
    n = len(pts)
    ymin = max(0, int(min(p[1] for p in pts)))
    ymax = min(H - 1, int(max(p[1] for p in pts)))
    for y in range(ymin, ymax + 1):
        xs = []
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            if (y1 <= y < y2) or (y2 <= y < y1):
                xs.append(x1 + (y - y1) / (y2 - y1) * (x2 - x1))
        xs.sort()
        for i in range(0, len(xs) - 1, 2):
            hspan(y, xs[i], xs[i + 1], color)


def thick_line(x1, y1, x2, y2, w, color):
    dx, dy = x2 - x1, y2 - y1
    ln = math.hypot(dx, dy)
    if ln == 0:
        disc(x1, y1, w / 2, color)
        return
    nx, ny = -dy / ln * w / 2, dx / ln * w / 2
    poly([(x1 + nx, y1 + ny), (x2 + nx, y2 + ny),
          (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)], color)
    disc(x1, y1, w / 2, color)
    disc(x2, y2, w / 2, color)


def thick_polyline(pts, w, color):
    for a, b in zip(pts, pts[1:]):
        thick_line(a[0], a[1], b[0], b[1], w, color)


def glow(cx, cy, rad, color, peak):
    """Smooth radial glow, per-pixel falloff (no banding)."""
    for y in range(max(0, cy - rad), min(H, cy + rad + 1)):
        dy = y - cy
        for x in range(max(0, cx - rad), min(W, cx + rad + 1)):
            dx = x - cx
            d = math.sqrt(dx * dx + dy * dy)
            if d >= rad:
                continue
            f = 1.0 - d / rad
            blend_px(x, y, color, peak * f * f)


def lerp(a, b, t):
    return a + (b - a) * t


def lerp_color(c1, c2, t):
    return (int(lerp(c1[0], c2[0], t)),
            int(lerp(c1[1], c2[1], t)),
            int(lerp(c1[2], c2[2], t)))


# ---------------------------------------------------------------- curves
def catmull_path(pts, radii, per_seg=28):
    """Catmull-Rom through control points; radii interpolated the same way."""
    P = [pts[0]] + list(pts) + [pts[-1]]
    R = [radii[0]] + list(radii) + [radii[-1]]
    spine, rr = [], []
    for i in range(len(P) - 3):
        p0, p1, p2, p3 = P[i], P[i + 1], P[i + 2], P[i + 3]
        r0, r1, r2, r3 = R[i], R[i + 1], R[i + 2], R[i + 3]
        for j in range(per_seg):
            t = j / per_seg
            t2, t3 = t * t, t * t * t
            x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t
                       + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                       + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
            y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t
                       + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                       + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
            r = 0.5 * ((2 * r1) + (-r0 + r2) * t
                       + (2 * r0 - 5 * r1 + 4 * r2 - r3) * t2
                       + (-r0 + 3 * r1 - 3 * r2 + r3) * t3)
            spine.append((x, y))
            rr.append(max(4.0, r))
    spine.append(pts[-1])
    rr.append(radii[-1])
    return spine, rr


def tube(spine, radii, color):
    for (x, y), r in zip(spine, radii):
        disc(int(x), int(y), int(r), color)


def offset_spine(spine, radii, side, frac):
    """Spine shifted toward one side (perp of travel direction).

    side=+1 shifts down-right (belly side for a tail->head diagonal),
    side=-1 shifts up-left (back side).
    """
    out = []
    n = len(spine)
    for i, (x, y) in enumerate(spine):
        x0, y0 = spine[max(0, i - 1)]
        x1, y1 = spine[min(n - 1, i + 1)]
        dx, dy = x1 - x0, y1 - y0
        ln = math.hypot(dx, dy) or 1.0
        # (-dy, dx) is the down-right perpendicular for up-right travel
        out.append((x + side * (-dy / ln) * radii[i] * frac,
                    y + side * (dx / ln) * radii[i] * frac))
    return out


# ---------------------------------------------------------------- 5x7 font
FONT = {
    "W": ["#...#", "#...#", "#...#", "#.#.#", "#.#.#", "#.#.#", ".#.#."],
    "O": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "!": ["..#..", "..#..", "..#..", "..#..", "..#..", ".....", "..#.."],
}


def draw_text(text, cx, cy, scale, color):
    gw, gh = 5 * scale, 7 * scale
    gap = scale + 1
    total = len(text) * gw + (len(text) - 1) * gap
    x = cx - total // 2
    y = cy - gh // 2
    for ch in text:
        for row, line in enumerate(FONT[ch]):
            for col, c in enumerate(line):
                if c == "#":
                    rect(x + col * scale, y + row * scale, scale, scale, color)
        x += gw + gap


def starburst(cx, cy, spikes, r_out, r_in, color):
    pts = []
    for i in range(spikes * 2):
        ang = math.pi * i / spikes - math.pi / 2
        r = r_out if i % 2 == 0 else r_in
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    poly(pts, color)


# ---------------------------------------------------------------- scene
def draw_sky():
    for y in range(H):
        if y < 512:
            c = lerp_color(SKY_TOP, SKY_MID, y / 512)
        else:
            c = lerp_color(SKY_MID, SKY_LOW, (y - 512) / 512)
        hspan(y, 0, W - 1, c)


def draw_stars():
    for _ in range(150):
        x, y = rng.randrange(0, W), rng.randrange(0, 860)
        if x < 310 and y < 310:      # keep the badge area clean
            continue
        r = rng.choice([1, 1, 1, 2])
        shade = rng.choice([(255, 255, 255), (255, 255, 255),
                            (200, 225, 245), (159, 195, 232)])
        disc(x, y, r, shade)
    for _ in range(12):              # cross sparkles
        x, y = rng.randrange(330, 1000), rng.randrange(40, 700)
        s = rng.randrange(5, 9)
        thick_line(x - s, y, x + s, y, 2, (255, 255, 255))
        thick_line(x, y - s, x, y + s, 2, (255, 255, 255))


def draw_desk():
    for y in range(884, H):
        c = lerp_color(WOOD, WOOD_DARK, (y - 884) / 140)
        hspan(y, 0, W - 1, c)
    hspan(884, 0, W - 1, (122, 82, 48))
    for y in (922, 956, 990):
        hspan(y, 0, W - 1, WOOD_LINE)
        hspan(y + 1, 0, W - 1, (58, 36, 20))


def draw_globe():
    cx, cy, R = 195, 722, 116
    # desk shadow under the globe
    for yy in range(880, 906):
        dy = (yy - 892) / 14
        dx = int(165 * (1 - dy * dy) ** 0.5) if abs(dy) < 1 else 0
        for xx in range(cx - dx, cx + dx + 1):
            blend_px(xx, yy, (0, 0, 0), 0.45)
    # glass tint
    for yy in range(cy - R, cy + R + 1):
        dy = yy - cy
        dx = int((R * R - dy * dy) ** 0.5)
        for xx in range(cx - dx, cx + dx + 1):
            blend_px(xx, yy, (120, 190, 215), 0.16)
    # water + island inside
    ellipse(cx, cy + 56, 96, 34, WATER)
    ellipse(cx, cy + 66, 72, 26, ISLAND)
    # lighthouse (red/white tower, gold lamp, beam to the crack)
    rect(cx - 8, 707, 16, 56, (245, 245, 245))
    rect(cx - 8, 707, 16, 14, LIGHT_RED)
    rect(cx - 8, 735, 16, 14, LIGHT_RED)
    rect(cx - 11, 701, 22, 7, INK)
    disc(cx, 697, 6, GOLD_HI)
    poly([(cx, 697), (318, 606), (324, 640)], BEAM)
    # rim + upper-left highlight
    for k in range(120):
        a = 2 * math.pi * k / 120
        disc(int(cx + R * math.cos(a)), int(cy + R * math.sin(a)), 5, GLASS)
    for k in range(26):
        a = math.radians(185 + k * 3)
        disc(int(cx + R * math.cos(a)), int(cy + R * math.sin(a)), 7,
             (240, 248, 255))
    # wooden stand
    ellipse(cx, 845, 96, 22, (90, 58, 34))
    ellipse(cx, 841, 96, 20, (110, 72, 42))


def draw_whale():
    ctrl = [(170, 838), (255, 792), (360, 712), (480, 610),
            (600, 505), (710, 405), (800, 322)]
    radii = [24, 48, 78, 98, 104, 96, 84]
    spine, rr = catmull_path(ctrl, radii)
    # dark rim, then body
    tube(spine, [r + 6 for r in rr], INK)
    tube(spine, rr, WHALE)
    # back sheen (upper side) and belly (lower side, stops before the head
    # so the head stays blue and reads as a whale, not a round face)
    tube(offset_spine(spine, rr, -1, 0.42),
         [r * 0.50 for r in rr], SHEEN)
    cut = int(len(spine) * 0.82)
    tube(offset_spine(spine[:cut], rr[:cut], +1, 0.30),
         [r * 0.58 for r in rr[:cut]], BELLY)
    # rounded head, kept blue; a small snout bump stretches it up-right
    disc(836, 296, 76, WHALE)
    disc(872, 266, 52, WHALE)
    # dorsal fin (upper side, ~62% along) and pectoral fin (lower, ~48%)
    i_d = int(len(spine) * 0.62)
    x, y = spine[i_d]
    x0, y0 = spine[i_d - 6]
    x1, y1 = spine[i_d + 6]
    dx, dy = x1 - x0, y1 - y0
    ln = math.hypot(dx, dy)
    ux, uy = dy / ln, -dx / ln          # up-left perpendicular
    dxn, dyn = dx / ln, dy / ln
    poly([(x - dxn * 40 + ux * 8, y - dyn * 40 + uy * 8),
          (x + dxn * 40 + ux * 8, y + dyn * 40 + uy * 8),
          (x + ux * 95, y + uy * 95)], WHALE_DK)
    i_p = int(len(spine) * 0.48)
    x, y = spine[i_p]
    x0, y0 = spine[i_p - 6]
    x1, y1 = spine[i_p + 6]
    dx, dy = x1 - x0, y1 - y0
    ln = math.hypot(dx, dy)
    dxn, dyn = dx / ln, dy / ln
    ux, uy = dy / ln, -dx / ln          # up-left perpendicular
    # down-right perpendicular is (-ux, -uy): the fin points below the body
    poly([(x - dxn * 42, y - dyn * 42),
          (x + dxn * 42, y + dyn * 42),
          (x - ux * 92, y - uy * 92)], WHALE_DK)
    # tail flukes smashing out low-left
    poly([(192, 812), (96, 748), (168, 852)], WHALE)
    poly([(192, 850), (104, 912), (168, 822)], WHALE)
    poly([(192, 812), (96, 748), (168, 852)], WHALE_DK)  # shade one fluke
    # eye (focal point, on the blue of the head), jaw line, blowhole
    disc(806, 252, 13, INK)
    disc(802, 248, 4, (255, 255, 255))
    mouth = []
    for k in range(13):
        t = k / 12
        mx = lerp(lerp(762, 830, t), lerp(830, 888, t), t)
        my = lerp(lerp(322, 352, t), lerp(352, 318, t), t)
        mouth.append((mx, my))
    thick_polyline(mouth, 5, INK)
    disc(840, 216, 4, INK)
    disc(856, 224, 4, INK)
    # spout: droplets fanning up from the blowhole
    for k in range(26):
        t = k / 25
        sx = 845 + (k % 5 - 2) * 18 * t + rng.uniform(-8, 8)
        sy = 208 - t * 80 + rng.uniform(-8, 8)
        disc(int(sx), int(sy), rng.choice([2, 3, 3, 4]),
             rng.choice([SPRAY_W, SPRAY_C, SPRAY_B]))


def draw_cracks_and_shards():
    # top-right crack (head exit) + low-left crack (tail exit)
    thick_polyline([(277, 640), (290, 626), (282, 618), (298, 608),
                    (312, 602)], 4, (255, 255, 255))
    thick_polyline([(290, 626), (304, 630), (312, 624)], 3, (255, 255, 255))
    thick_polyline([(113, 804), (101, 818), (107, 826), (91, 840)], 4,
                   (255, 255, 255))
    # glass shards along the breach path
    shard_cols = [(255, 255, 255), (191, 230, 247), (127, 208, 234),
                  (232, 246, 255)]
    for _ in range(26):
        t = rng.random()
        bx = lerp(300, 800, t)
        by = lerp(630, 320, t)
        px, py = bx + rng.uniform(-95, 95), by + rng.uniform(-70, 70)
        s = rng.uniform(8, 24)
        a = rng.uniform(0, 2 * math.pi)
        pts = [(px + s * math.cos(a), py + s * math.sin(a)),
               (px + s * 0.55 * math.cos(a + 2.4), py + s * 0.55 * math.sin(a + 2.4)),
               (px + s * 0.5 * math.cos(a + 4.6), py + s * 0.5 * math.sin(a + 4.6))]
        poly(pts, rng.choice(shard_cols))
    for _ in range(8):                   # shards near the tail crack
        px, py = 100 + rng.uniform(-45, 45), 822 + rng.uniform(-40, 40)
        s = rng.uniform(6, 16)
        a = rng.uniform(0, 2 * math.pi)
        pts = [(px + s * math.cos(a), py + s * math.sin(a)),
               (px + s * 0.5 * math.cos(a + 2.2), py + s * 0.5 * math.sin(a + 2.2)),
               (px + s * 0.45 * math.cos(a + 4.4), py + s * 0.45 * math.sin(a + 4.4))]
        poly(pts, rng.choice(shard_cols))


def draw_spray():
    for _ in range(110):
        t = rng.random()
        bx = lerp(lerp(320, 560, t), lerp(560, 810, t), t)
        by = lerp(lerp(610, 380, t), lerp(380, 300, t), t)
        px, py = bx + rng.uniform(-55, 55), by + rng.uniform(-45, 45)
        disc(int(px), int(py), rng.choice([2, 2, 3, 3, 4, 5]),
             rng.choice([SPRAY_W, SPRAY_W, SPRAY_C, SPRAY_B]))
    for _ in range(10):                  # fast streaks along the path
        t = rng.random()
        bx = lerp(lerp(320, 560, t), lerp(560, 810, t), t)
        by = lerp(lerp(610, 380, t), lerp(380, 300, t), t)
        thick_line(bx - 14, by + 10, bx + 14, by - 10, 3, SPRAY_C)


def draw_badge():
    starburst(152, 148, 14, 130, 98, ORANGE)
    starburst(152, 148, 14, 120, 90, GOLD)
    draw_text("WOW!", 156, 150, 8, INK)


def draw_scene():
    draw_sky()
    draw_stars()
    glow(775, 295, 340, GOLD, 0.80)
    glow(775, 295, 170, GOLD_HI, 0.85)
    for tip in [(690, -15), (800, -15), (905, 55), (455, 140)]:
        dx, dy = tip[0] - 775, tip[1] - 295
        ln = math.hypot(dx, dy)
        nx, ny = -dy / ln * 10, dx / ln * 10
        poly([(775 + nx, 295 + ny), (775 - nx, 295 - ny), tip], GOLD_RAY)
    draw_desk()
    draw_globe()
    draw_whale()
    draw_cracks_and_shards()
    draw_spray()
    draw_badge()


# ---------------------------------------------------------------- PNG output
def encode_png(w, h, data):
    def chunk(tag, payload):
        out = struct.pack(">I", len(payload)) + tag + payload
        return out + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += data[y * w * 3:(y + 1) * w * 3]
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + chunk(b"IEND", b""))


def main():
    outdir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(outdir, exist_ok=True)
    draw_scene()
    png = encode_png(W, H, buf)
    with open(os.path.join(outdir, "entry.png"), "wb") as f:
        f.write(png)


if __name__ == "__main__":
    main()
