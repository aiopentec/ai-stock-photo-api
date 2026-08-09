#!/usr/bin/env python3
"""
generate_sitemap.py

Builds sitemap.xml after each generation run. Includes:
  - Standard sitemap entries for the gallery and about page
  - Google Image Sitemap extension (image:image) for every photo
    so Google Image Search can discover and index individual images.

The image sitemap is the single biggest SEO multiplier for a
stock photo site — it gets individual images surfaced in Google
Image Search for their keywords without needing separate HTML pages.

Run automatically after generate_dalle.py / generate_pollinations.py
in the GitHub Actions workflow.
"""

import json
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT  = Path(__file__).resolve().parent.parent
INDEX_PATH = REPO_ROOT / "api" / "images.json"
SITEMAP    = REPO_ROOT / "sitemap.xml"

BASE_URL   = "https://aiopentec.github.io/ai-stock-photo-api"


def load_index():
    if INDEX_PATH.exists():
        try:
            return json.loads(INDEX_PATH.read_text())
        except json.JSONDecodeError:
            pass
    return {"images": []}


def make_title(keyword, category):
    """Human-readable title for Google Image Search results."""
    keyword_clean = keyword.replace("_", " ").title()
    category_clean = category.replace("_", " ").title()
    return f"Free {keyword_clean} Stock Photo — {category_clean} | AI Stock Photos"


def main():
    index  = load_index()
    images = index.get("images", [])
    today  = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset',
        '  xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"',
        '  xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">',
        "",
    ]

    # ── Static pages ──────────────────────────────────────────────────────────
    static_pages = [
        (BASE_URL + "/",           "1.0", "weekly",  today),
        (BASE_URL + "/about.html", "0.7", "monthly", today),
    ]

    for url, priority, changefreq, lastmod in static_pages:
        lines += [
            "  <url>",
            f"    <loc>{url}</loc>",
            f"    <lastmod>{lastmod}</lastmod>",
            f"    <changefreq>{changefreq}</changefreq>",
            f"    <priority>{priority}</priority>",
            "  </url>",
            "",
        ]

    # ── Image entries (Google Image Sitemap) ──────────────────────────────────
    # Each image entry is added to the gallery page URL with an image: block.
    # Google picks these up for Image Search without needing individual pages.
    # Group all images under the gallery URL as separate image: entries.
    if images:
        lines.append("  <url>")
        lines.append(f"    <loc>{BASE_URL}/</loc>")
        for img in images:
            filename = img.get("filename", "")
            keyword  = img.get("source_keyword", filename.replace("_", " "))
            category = img.get("source_category", "general")
            title    = make_title(keyword, category)
            img_url  = f"{BASE_URL}/images/{filename}"

            lines += [
                "    <image:image>",
                f"      <image:loc>{img_url}</image:loc>",
                f"      <image:title>{title}</image:title>",
                f"      <image:caption>Free AI stock photo of {keyword}, generated with DALL-E 3. Free for commercial use.</image:caption>",
                "    </image:image>",
            ]
        lines.append("  </url>")
        lines.append("")

    lines.append("</urlset>")

    SITEMAP.write_text("\n".join(lines))

    print(f"sitemap.xml written: {len(static_pages)} pages + {len(images)} image entries")


if __name__ == "__main__":
    main()
