#!/usr/bin/env python3
"""Generate simple dark iOS launch screens (solid #04040F + centered Monarch icon).
Nothing fancy: one flat brand-dark background with the app icon centered."""
import os
from PIL import Image

BG = (4, 4, 15, 255)          # #04040F — matches theme_color / background_color
ICON = "/home/operator/projects/command-center/web/public/icon-512.png"
OUT = "/home/operator/projects/command-center/web/public/splash"

# (device_px_w, device_px_h, dpr)  — modern iPhone portrait set
DEVICES = [
    (1290, 2796, 3),  # 14/15/16 Pro Max, 15/16 Plus
    (1179, 2556, 3),  # 14 Pro, 15, 15 Pro, 16
    (1284, 2778, 3),  # 12/13 Pro Max, 14 Plus
    (1170, 2532, 3),  # 12, 13, 14, 13 Pro
    (1125, 2436, 3),  # X, XS, 11 Pro, 12/13 mini
    (1242, 2688, 3),  # XS Max, 11 Pro Max
    (828, 1792, 2),   # XR, 11
    (750, 1334, 2),   # SE 2/3, 8, 7, 6s
]

os.makedirs(OUT, exist_ok=True)
icon = Image.open(ICON).convert("RGBA")

links = []
for w, h, dpr in DEVICES:
    canvas = Image.new("RGBA", (w, h), BG)
    side = int(min(w, h) * 0.30)
    ic = icon.resize((side, side), Image.LANCZOS)
    canvas.alpha_composite(ic, ((w - side) // 2, (h - side) // 2))
    name = f"splash-{w}x{h}.png"
    canvas.convert("RGB").save(os.path.join(OUT, name), "PNG", optimize=True)
    cw, ch = w // dpr, h // dpr
    media = (f"screen and (device-width: {cw}px) and (device-height: {ch}px) "
             f"and (-webkit-device-pixel-ratio: {dpr}) and (orientation: portrait)")
    links.append(f'    <link rel="apple-touch-startup-image" media="{media}" href="/splash/{name}" />')
    print(f"wrote {name}  ({cw}x{ch} @{dpr}x)")

with open(os.path.join(OUT, "_link_tags.html"), "w") as f:
    f.write("\n".join(links) + "\n")
print("\n--- link tags written to splash/_link_tags.html ---")
