#!/usr/bin/env python3
"""
Generate favicon.png from logo.jpg for Google search results.
Creates a square PNG (96x96) - Google requires min 48x48, square.

Run when you change the logo:
  python3 generate_favicon.py
"""
import os
from PIL import Image

LOGO_PATH = os.path.join('static', 'logo.jpg')
FAVICON_PATH = os.path.join('static', 'favicon.png')

def main():
    if not os.path.exists(LOGO_PATH):
        print(f"Logo not found: {LOGO_PATH}")
        return 1

    img = Image.open(LOGO_PATH).convert("RGBA")
    w, h = img.size

    # Center-crop to square
    size = min(w, h)
    left = (w - size) // 2
    top = (h - size) // 2
    img = img.crop((left, top, left + size, top + size))

    # Resize to 96x96 (covers both 48 and 96 for high-DPI)
    img = img.resize((96, 96), Image.Resampling.LANCZOS)

    # Make near-black background transparent so favicon looks good on light search result backgrounds
    data = list(img.getdata())
    new_data = []
    for item in data:
        r, g, b, a = item
        if r < 30 and g < 30 and b < 30:
            new_data.append((r, g, b, 0))
        else:
            new_data.append(item)
    img.putdata(new_data)

    img.save(FAVICON_PATH, "PNG")
    print(f"Created {FAVICON_PATH} (96x96)")
    return 0

if __name__ == "__main__":
    exit(main())
