#!/usr/bin/env python3
"""Draw the Vigil app icon and pack it into build/vigil.icns.

macOS (Big Sur+) icon grammar: a squircle that fills ~80% of the canvas with
transparent margin around it, a soft drop shadow, and one clear symbol — the
viewfinder brackets + live green dot Vigil uses everywhere.

  ./venv/bin/python make_icon.py
"""
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter

S = 1024
MARGIN = 100                      # Apple's grid: icon body ≈ 824/1024
BODY = S - 2 * MARGIN
RADIUS = int(BODY * 0.225)

img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

# Soft drop shadow (offset down, heavily blurred) — how first-party icons sit.
shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(shadow)
d.rounded_rectangle([MARGIN, MARGIN + 14, S - MARGIN, S - MARGIN + 14],
                    radius=RADIUS, fill=(0, 0, 0, 110))
shadow = shadow.filter(ImageFilter.GaussianBlur(22))
img.alpha_composite(shadow)

# Body: subtle top-lit vertical gradient on the graphite surface.
body = Image.new("RGBA", (S, S), (0, 0, 0, 0))
grad = Image.new("RGBA", (S, S), (0, 0, 0, 0))
gd = ImageDraw.Draw(grad)
top, bottom = (28, 33, 41), (13, 16, 21)
for y in range(MARGIN, S - MARGIN):
    t = (y - MARGIN) / BODY
    col = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,)
    gd.line([(MARGIN, y), (S - MARGIN, y)], fill=col)
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle(
    [MARGIN, MARGIN, S - MARGIN, S - MARGIN], radius=RADIUS, fill=255)
body.paste(grad, (0, 0), mask)
img.alpha_composite(body)

# 1px light edge on top of the squircle ("lit from above").
edge = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(edge).rounded_rectangle(
    [MARGIN, MARGIN, S - MARGIN, S - MARGIN], radius=RADIUS,
    outline=(255, 255, 255, 26), width=3)
img.alpha_composite(edge)

# Symbol: four viewfinder brackets + green live dot.
d = ImageDraw.Draw(img)
col = (146, 156, 170, 255)
w = int(S * 0.040)
inset = int(S * 0.315)
L = int(S * 0.135)
lo, hi = inset, S - inset

def cap(x, y):
    d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=col)

for (cx, cy, dx, dy) in ((lo, lo, 1, 1), (hi, lo, -1, 1),
                         (lo, hi, 1, -1), (hi, hi, -1, -1)):
    d.line([(cx, cy + dy * L), (cx, cy), (cx + dx * L, cy)],
           fill=col, width=w, joint="curve")
    cap(cx, cy + dy * L); cap(cx + dx * L, cy)

cr = int(S * 0.118)
c = S // 2
glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(glow).ellipse([c - cr * 1.8, c - cr * 1.8, c + cr * 1.8, c + cr * 1.8],
                             fill=(47, 179, 125, 70))
img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(30)))
d.ellipse([c - cr, c - cr, c + cr, c + cr], fill=(62, 207, 142, 255))
# small specular highlight on the dot
d.ellipse([c - cr * 0.45, c - cr * 0.62, c + cr * 0.1, c - cr * 0.12],
          fill=(255, 255, 255, 60))

os.makedirs("build", exist_ok=True)

# Windows .ico — same art, full-bleed (Windows icons carry no built-in margin,
# so the squircle is scaled up to use the canvas like other taskbar icons).
full = img.crop((MARGIN - 24, MARGIN - 24, S - MARGIN + 24, S - MARGIN + 24))
full.resize((256, 256), Image.LANCZOS).save(
    "build/vigil.ico",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("build/vigil.ico written")

# macOS .icns (needs Apple's iconutil, so only on a Mac)
if sys.platform == "darwin":
    iconset = "build/vigil.iconset"
    os.makedirs(iconset, exist_ok=True)
    for s in (16, 32, 128, 256, 512):
        img.resize((s, s), Image.LANCZOS).save(f"{iconset}/icon_{s}x{s}.png")
        img.resize((s * 2, s * 2), Image.LANCZOS).save(f"{iconset}/icon_{s}x{s}@2x.png")
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", "build/vigil.icns"],
                   check=True)
    print("build/vigil.icns written")
