#!/usr/bin/env python3
"""One-off: draws icon.png (1024x1024) for the macOS app icon. Not part of
the runtime app — requires Pillow, which is a dev-only tool dependency."""
from PIL import Image, ImageDraw

SIZE = 1024
BG = (30, 41, 59)  # dark slate, matches the app's dark theme
CELL_EMPTY = (51, 65, 85)
CELL_FILLED = (52, 211, 153)  # accent green, matches --nz-bg family
RADIUS = 200

img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)
draw.rounded_rectangle([0, 0, SIZE, SIZE], radius=RADIUS, fill=BG)

# a small sparse-matrix grid, mostly empty cells with a few filled ones
cols, rows = 5, 5
pad = 190
gap = 18
cell = (SIZE - 2 * pad - gap * (cols - 1)) // cols
filled = {(0, 1), (1, 3), (2, 2), (3, 0), (3, 4), (4, 2)}

for r in range(rows):
    for c in range(cols):
        x0 = pad + c * (cell + gap)
        y0 = pad + r * (cell + gap)
        color = CELL_FILLED if (r, c) in filled else CELL_EMPTY
        draw.rounded_rectangle([x0, y0, x0 + cell, y0 + cell], radius=cell // 6, fill=color)

img.save("icon.png")
print("wrote icon.png")
