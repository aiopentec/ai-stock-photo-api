#!/usr/bin/env python3
"""
optimize_images.py

Runs after each generation step. Handles three cases:
  1. PNG files         -> convert to WebP + create thumbnail
  2. WebP files that contain PNG data (saved without Pillow) -> recompress + thumbnail
  3. WebP files missing a thumbnail -> create thumbnail only

After the first successful run, this becomes a fast no-op.
"""

import json
from pathlib import Path
from PIL import Image, ImageOps

REPO_ROOT    = Path(__file__).resolve().parent.parent
IMAGES_DIR   = REPO_ROOT / "images"
THUMBS_DIR   = IMAGES_DIR / "thumbs"
INDEX_PATH   = REPO_ROOT / "api" / "images.json"

WEBP_QUALITY  = 85
THUMB_QUALITY = 80
THUMB_W, THUMB_H = 480, 320

PNG_MAGIC = b'\x89PNG\r\n\x1a\n'

def is_png_data(path: Path) -> bool:
    """Return True if file contains PNG bytes despite having .webp extension."""
    try:
        with open(path, 'rb') as f:
            return f.read(8) == PNG_MAGIC
    except Exception:
        return False

def make_thumbnail(source_path: Path, stem: str) -> str | None:
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    tp = THUMBS_DIR / (stem + ".webp")
    try:
        with Image.open(source_path) as img:
            ImageOps.fit(img.convert("RGB"),
                         (THUMB_W, THUMB_H), Image.LANCZOS).save(
                tp, "WEBP", quality=THUMB_QUALITY, method=4)
        return "thumbs/" + tp.name
    except Exception as exc:
        print(f"  [thumb err] {source_path.name}: {exc}")
        return None

def convert_to_webp(source_path: Path, dest_path: Path) -> int:
    """Convert any image (PNG or PNG-masquerading-as-WebP) to proper WebP."""
    with Image.open(source_path) as img:
        img.convert("RGB").save(dest_path, "WEBP",
                                quality=WEBP_QUALITY, method=6)
    return dest_path.stat().st_size // 1024

def main():
    if not INDEX_PATH.exists():
        print("No api/images.json — nothing to optimise")
        return

    index       = json.loads(INDEX_PATH.read_text())
    images      = index.get("images", [])
    converted   = 0
    recompressed = 0
    thumbs_made = 0
    saved_kb    = 0

    for img in images:
        filename  = img.get("filename", "")
        has_thumb = bool(img.get("thumbnail"))
        if not filename:
            continue

        # ── Case 1: PNG file ──────────────────────────────────────────────────
        if filename.endswith(".png"):
            png_path  = IMAGES_DIR / filename
            if not png_path.exists():
                print(f"  [skip] {filename} not on disk")
                continue

            webp_name = filename[:-4] + ".webp"
            webp_path = IMAGES_DIR / webp_name

            orig_kb = png_path.stat().st_size // 1024
            try:
                new_kb = convert_to_webp(png_path, webp_path)
                png_path.unlink()

                img["filename"] = webp_name
                img["size_kb"]  = new_kb
                saved_kb       += (orig_kb - new_kb)
                converted      += 1
                pct = int((1 - new_kb / max(orig_kb, 1)) * 100)
                print(f"  {filename} -> {webp_name}  "
                      f"({orig_kb}KB -> {new_kb}KB, {pct}% smaller)")

                thumb = make_thumbnail(webp_path, webp_name[:-5])
                if thumb:
                    img["thumbnail"] = thumb
                    thumbs_made += 1
            except Exception as exc:
                print(f"  [err] {filename}: {exc}")
            continue

        # ── Case 2: WebP file containing PNG data (saved without Pillow) ─────
        if filename.endswith(".webp"):
            webp_path = IMAGES_DIR / filename
            if not webp_path.exists():
                continue

            if is_png_data(webp_path):
                orig_kb = webp_path.stat().st_size // 1024
                try:
                    tmp = webp_path.with_suffix(".tmp")
                    new_kb = convert_to_webp(webp_path, tmp)
                    tmp.replace(webp_path)

                    img["size_kb"] = new_kb
                    saved_kb      += (orig_kb - new_kb)
                    recompressed  += 1
                    pct = int((1 - new_kb / max(orig_kb, 1)) * 100)
                    print(f"  [recompress] {filename}  "
                          f"({orig_kb}KB -> {new_kb}KB, {pct}% smaller)")
                except Exception as exc:
                    print(f"  [err recompress] {filename}: {exc}")

            # Generate thumbnail if missing (whether or not we recompressed)
            if not has_thumb:
                thumb = make_thumbnail(webp_path, filename[:-5])
                if thumb:
                    img["thumbnail"] = thumb
                    thumbs_made += 1
                    if not is_png_data(webp_path):
                        print(f"  [thumb] {filename}")

    if converted == 0 and recompressed == 0 and thumbs_made == 0:
        print("All images already optimised — nothing to do")
        return

    index["total_images"] = len(images)
    INDEX_PATH.write_text(json.dumps(index, indent=2))

    print(f"\nConverted    : {converted} PNG -> WebP")
    print(f"Recompressed : {recompressed} fake-WebP -> real WebP")
    print(f"Thumbnails   : {thumbs_made} created")
    print(f"Space saved  : {saved_kb/1024:.1f} MB")

if __name__ == "__main__":
    main()
