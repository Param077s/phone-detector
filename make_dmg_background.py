#!/usr/bin/env python3
"""Draw the Vigil install-window background (build/dmg-bg.png), on-brand and
2x for retina. The real Vigil.app and Applications icons are placed on top by
create-dmg; this only paints the backdrop, arrow, and text between them.

If anything here fails, we still write a plain dark background so the DMG build
can proceed.
"""
import os

W, H = 1280, 840                       # 2x of the 640x420 install window
BG = (11, 13, 16)                      # --bg  #0B0D10
GREEN = (47, 179, 125)                 # --accent #2FB37D
TEXT = (232, 235, 239)                 # --text
MUTED = (120, 129, 140)                # --text-3-ish
os.makedirs("build", exist_ok=True)
OUT = "build/dmg-bg.png"


def _font(size, bold=False):
    from PIL import ImageFont
    candidates = [
        "/System/Library/Fonts/SFNSDisplay.ttf",
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _center(draw, xy, text, font, fill):
    x, y = xy
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    draw.text((x - (r - l) / 2, y - (b - t) / 2), text, font=font, fill=fill)


def build():
    from PIL import Image, ImageDraw, ImageChops, ImageFilter

    img = Image.new("RGB", (W, H), BG)

    # soft cool glow in the centre for depth
    glow = ImageChops.invert(Image.radial_gradient("L").resize((W, H)))
    tint = Image.new("RGB", (W, H), (23, 29, 37))
    img = Image.composite(tint, img, glow.point(lambda v: int(v * 0.55)))

    d = ImageDraw.Draw(img, "RGBA")

    # ---- brand: rounded "surveillance frame" mark + wordmark, top centre ----
    mx, my, s = 556, 92, 52            # mark top-left + size
    d.rounded_rectangle([mx, my, mx + s, my + s], radius=15, fill=(28, 34, 42))
    arm, w = 15, 5
    corners = [
        [(mx + 14, my + 14 + arm), (mx + 14, my + 14), (mx + 14 + arm, my + 14)],
        [(mx + s - 14 - arm, my + 14), (mx + s - 14, my + 14), (mx + s - 14, my + 14 + arm)],
        [(mx + s - 14, my + s - 14 - arm), (mx + s - 14, my + s - 14), (mx + s - 14 - arm, my + s - 14)],
        [(mx + 14 + arm, my + s - 14), (mx + 14, my + s - 14), (mx + 14, my + s - 14 - arm)],
    ]
    for c in corners:
        d.line(c, fill=(122, 133, 140), width=w, joint="curve")
    d.ellipse([mx + s / 2 - 8, my + s / 2 - 8, mx + s / 2 + 8, my + s / 2 + 8], fill=GREEN)
    _center(d, (W / 2 + 44, my + s / 2 + 2), "Vigil", _font(46), TEXT)

    # ---- arrow from the app (left) toward Applications (right) ----
    ay = 400
    x1, x2 = 500, 780
    d.line([(x1, ay), (x2 - 22, ay)], fill=GREEN, width=9)
    d.polygon([(x2, ay), (x2 - 26, ay - 16), (x2 - 26, ay + 16)], fill=GREEN)

    # ---- instructions ----
    _center(d, (W / 2, 612), "Drag  Vigil  into  Applications", _font(34), TEXT)
    _center(d, (W / 2, 686), "AI phone detection · everything runs on this device", _font(24), MUTED)

    img = img.filter(ImageFilter.SMOOTH_MORE)
    img.save(OUT)
    print("wrote", OUT)


try:
    build()
except Exception as e:                 # never block the DMG build
    print("background render failed (%s) — writing plain dark backdrop" % e)
    try:
        from PIL import Image
        Image.new("RGB", (W, H), BG).save(OUT)
    except Exception as e2:
        print("could not write fallback background:", e2)
        raise SystemExit(0)
