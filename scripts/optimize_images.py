#!/usr/bin/env python3
"""
optimize_images.py

Runs automatically after each generation step. Does two things:

1. PNG -> WebP  (if not already WebP)
   Before: ~2.0-2.7 MB per PNG
   After : ~200-400 KB per WebP @ quality 85  (~80% smaller)

2. Thumbnail generation  (if not already created)
   480x320 WebP in images/thumbs/  @ quality 80  (~25-45 KB each)
   Gallery cards load thumbnails; full image only loads in the modal.

After the first run all images will be WebP with thumbnails and
this script becomes a fast no-op for already-optimised images.
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
THUMB_W       = 480
THUMB_H       = 320


def make_thumbnail(source_path: Path, stem: str) -> str | None:
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    thumb_path = THUMBS_DIR / (stem + ".webp")
    try:
        with Image.open(source_path) as img:
            fitted = ImageOps.fit(img.convert("RGB"),
                                  (THUMB_W, THUMB_H), Image.LANCZOS)
            fitted.save(thumb_path, "WEBP", quality=THUMB_QUALITY, method=4)
        return "thumbs/" + thumb_path.name
    except Exception as exc:
        print(f"  [thumb err] {source_path.name}: {exc}")
        return None


def main():
    if not INDEX_PATH.exists():
        print("No api/images.json — nothing to optimise")
        return

    index       = json.loads(INDEX_PATH.read_text())
    images      = index.get("images", [])
    converted   = 0
    thumbs_made = 0
    saved_kb    = 0

    for img in images:
        filename    = img.get("filename", "")
        has_thumb   = bool(img.get("thumbnail"))

        # ── PNG -> WebP ────────────────────────────────────────────────────────
        if filename.endswith(".png"):
            png_path = IMAGES_DIR / filename
            if not png_path.exists():
                print(f"  [skip] {filename} not on disk")
                continue

            webp_name = filename[:-4] + ".webp"
            webp_path = IMAGES_DIR / webp_name

            try:
                with Image.open(png_path) as im:
                    im.convert("RGB").save(webp_path, "WEBP",
                                           quality=WEBP_QUALITY, method=6)

                orig = png_path.stat().st_size // 1024
                new  = webp_path.stat().st_size // 1024
                pct  = int((1 - new / max(orig, 1)) * 100)
                png_path.unlink()

                img["filename"] = webp_name
                img["size_kb"]  = new
                saved_kb       += (orig - new)
                converted      += 1
                print(f"  {filename} -> {webp_name}  "
                      f"({orig}KB -> {new}KB, {pct}% smaller)")

                # Thumbnail from the new WebP
                thumb = make_thumbnail(webp_path, webp_name[:-5])
                if thumb:
                    img["thumbnail"] = thumb
                    thumbs_made += 1

            except Exception as exc:
                print(f"  [err] {filename}: {exc}")
            continue

        # ── Existing WebP missing thumbnail ────────────────────────────────────
        if filename.endswith(".webp") and not has_thumb:
            webp_path = IMAGES_DIR / filename
            if not webp_path.exists():
                continue
            thumb = make_thumbnail(webp_path, filename[:-5])
            if thumb:
                img["thumbnail"] = thumb
                thumbs_made += 1
                print(f"  [thumb] {filename}")

    if converted == 0 and thumbs_made == 0:
        print("All images already optimised — nothing to do")
        return

    index["total_images"] = len(images)
    INDEX_PATH.write_text(json.dumps(index, indent=2))
    print(f"\nConverted : {converted} PNG -> WebP  (saved {saved_kb/1024:.1f} MB)")
    print(f"Thumbnails: {thumbs_made} created in images/thumbs/")


if __name__ == "__main__":
    main()
