#!/usr/bin/env python3
"""
Write the site's photos from the originals, using _src/photos.json.

    python3 _src/photos.py "/path/to/folder of originals"

For each entry: crop (fractions of the original), blur any listed boxes
(house numbers), resize to each width and save WebP as
assets/img/<name>-<width>.webp. An entry with "out" and "size" is saved once
as a JPEG at that path instead (the 1200x630 social share image). Needs Pillow (pip install pillow); the site
build itself (build.py) stays stdlib-only and only reads photos.json.
"""
import json
import os
import sys

from PIL import Image, ImageFilter, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "assets", "img")
DEFAULT_WIDTHS = [800, 1200]


def main(src_dir):
    with open(os.path.join(HERE, "photos.json"), encoding="utf-8") as f:
        photos = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    os.makedirs(OUT, exist_ok=True)
    for key, p in photos.items():
        im = ImageOps.exif_transpose(Image.open(os.path.join(src_dir, p["source"]))).convert("RGB")
        w, h = im.size
        for box in p.get("blur", []):
            px = tuple(int(v * d) for v, d in zip(box, (w, h, w, h)))
            im.paste(im.crop(px).filter(ImageFilter.GaussianBlur(12)), px[:2])
        l, t, r, b = p["crop"]
        im = im.crop((int(l * w), int(t * h), int(r * w), int(b * h)))
        if p.get("soften"):  # hero photos sit under a dark overlay; softening halves the bytes
            im = im.filter(ImageFilter.GaussianBlur(p["soften"]))
        if p.get("out"):  # fixed-size JPEG, e.g. the social share image
            out = im.resize(tuple(p["size"]), Image.LANCZOS)
            path = os.path.join(HERE, "..", p["out"])
            out.save(path, "JPEG", quality=p.get("quality", 82), optimize=True, progressive=True)
            print(f"{key:18} {p['out']}  {out.width}x{out.height}  {os.path.getsize(path) // 1024} KB")
            continue
        for width in p.get("widths", DEFAULT_WIDTHS):
            width = min(width, im.width)
            out = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
            path = os.path.join(OUT, f"{p['name']}-{width}.webp")
            out.save(path, "WEBP", quality=p.get("quality", 50), method=6)
            print(f"{key:18} {os.path.relpath(path, os.path.join(HERE, '..'))}  {out.width}x{out.height}  {os.path.getsize(path) // 1024} KB")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
