#!/usr/bin/env python3
"""
generate_pollinations.py

Generates stock photos via Pollinations.ai (no API key, no account, no cost)
and writes api/images.json in the exact schema the existing index.html expects:

  {
    "total_images": N,
    "generated_at": "...",
    "images": [
      {
        "filename":        "business_remote_work_1.png",
        "source_keyword":  "remote work",
        "source_category": "business",
        "size_kb":         312,
        "width":           1280,
        "height":          853,
        "prompt":          "...",
        "seed":            42
      },
      ...
    ]
  }

Pollinations endpoint:
  https://image.pollinations.ai/prompt/{encoded_prompt}
  ?width=1280&height=853&seed={seed}&model=flux-realism&nologo=true&enhance=false

- `flux-realism` produces the most stock-photo-like output of the available
   free models. Switch to `flux` for more stylised images.
- `nologo=true`  suppresses the Pollinations watermark overlay.
- `enhance=false` skips their prompt-rewriting layer so you get exactly
   what you asked for, which matters for consistent stock photo framing.
- No rate-limit header is published; 1 request / 2s is safe in practice.

LICENSE NOTE: Pollinations routes requests across multiple open models.
The licensing of output images therefore depends on which model handled
each request — Pollinations does not contractually guarantee a specific
output license. The CC0 badge in index.html is NOT safe as written.
Replace it with: "AI-generated — verify licensing for your specific use"
until you pin to a model with confirmed permissive output terms.
"""

import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parent.parent
IMAGES_DIR = REPO_ROOT / "images"
API_DIR    = REPO_ROOT / "api"
INDEX_PATH = API_DIR / "images.json"

POLLINATIONS_BASE = "https://image.pollinations.ai/prompt/{prompt}?width={w}&height={h}&seed={seed}&model={model}&nologo=true&enhance=false"

IMAGE_WIDTH  = 1280
IMAGE_HEIGHT = 853    # 3:2 ratio — standard landscape stock photo
MODEL        = "flux-realism"
PAUSE_SECS   = 2.5   # between requests; don't hammer the free endpoint

# ---------------------------------------------------------------------------
# Keyword catalogue — maps each category to a list of (keyword, prompt) pairs.
# Prompt wording is intentional: "professional stock photograph" + framing
# cues consistently push flux-realism toward clean, usable results over
# stylised art. Keep prompts under ~200 chars for reliable URL encoding.
# ---------------------------------------------------------------------------
CATALOGUE = {
    "business": [
        ("remote work",         "professional stock photograph of a person working on a laptop at home, natural window light, modern desk, shallow depth of field, no text"),
        ("team meeting",        "professional stock photograph of a diverse business team in a bright conference room, candid discussion, modern office, no text"),
        ("startup office",      "professional stock photograph of an open-plan startup office with people collaborating, natural light, plants, no text"),
        ("business handshake",  "professional stock photograph of two people shaking hands in a modern office, trust and partnership, bright background, no text"),
        ("entrepreneur",        "professional stock photograph of a confident entrepreneur at a standing desk, city view through window, no text"),
    ],
    "nature": [
        ("forest path",         "professional stock photograph of a sunlit forest path with dappled light through trees, peaceful, shallow depth of field, no people"),
        ("mountain lake",       "professional stock photograph of a calm alpine lake reflecting surrounding mountains at golden hour, no people, no text"),
        ("wildflower meadow",   "professional stock photograph of a wildflower meadow in summer light, bees, natural colours, wide angle, no text"),
        ("ocean waves",         "professional stock photograph of gentle waves on a sandy beach at sunrise, soft pastel sky, no people, no text"),
        ("urban garden",        "professional stock photograph of a small community garden in a city, raised beds, vegetables, warm light, no text"),
    ],
    "technology": [
        ("circuit board",       "professional macro stock photograph of a green circuit board with components, sharp details, bokeh background, no text"),
        ("ai data center",      "professional stock photograph of a modern server room with blue LED lighting, rows of servers, no people, no text"),
        ("coding screen",       "professional stock photograph of code on a monitor screen with dark theme, blurred developer in background, no text"),
        ("smartphone flat lay", "professional stock photograph of a modern smartphone and coffee cup flat lay on white desk, minimal, no text on screen"),
        ("wireless network",    "professional stock photograph of wifi router glowing on a desk in a home office, soft bokeh background, no text"),
    ],
    "people": [
        ("woman reading",       "professional stock photograph of a young woman reading a book in a cosy armchair by a window, warm light, no text"),
        ("friends laughing",    "professional stock photograph of a diverse group of friends laughing together outdoors in a park, candid, natural light, no text"),
        ("senior couple",       "professional stock photograph of a happy senior couple walking in a park holding hands, autumn leaves, warm light, no text"),
        ("student studying",    "professional stock photograph of a university student studying with books and laptop in a library, focused, no text"),
        ("chef cooking",        "professional stock photograph of a chef preparing food in a professional kitchen, action shot, warm light, no text"),
    ],
    "abstract": [
        ("colourful smoke",     "professional abstract stock photograph of colourful smoke swirls against black background, purple orange teal, artistic, no text"),
        ("geometric shapes",    "professional abstract stock photograph of clean geometric shapes in soft pastel colours, minimal, studio lighting, no text"),
        ("water ripples",       "professional abstract macro stock photograph of water ripples in metallic blue tones, meditative, no text"),
        ("bokeh lights",        "professional abstract stock photograph of golden bokeh lights on dark background, festive, shallow depth of field, no text"),
        ("paper texture",       "professional stock photograph of layered torn paper texture in white and cream tones, minimal, flat lay, no text"),
    ],
    "food": [
        ("avocado toast",       "professional food stock photograph of avocado toast on sourdough with poached egg, overhead shot, bright natural light, no text"),
        ("coffee flat white",   "professional food stock photograph of a flat white coffee with latte art in ceramic cup, cafe setting, warm bokeh, no text"),
        ("fresh salad bowl",    "professional food stock photograph of a colourful grain bowl with vegetables, overhead shot on marble surface, natural light, no text"),
        ("farmers market",      "professional stock photograph of fresh vegetables at a farmers market stall, colourful produce, natural light, no text"),
        ("sourdough bread",     "professional food stock photograph of a freshly baked sourdough loaf on a wooden board, rustic kitchen, warm light, no text"),
    ],
    "travel": [
        ("cobblestone street",  "professional travel stock photograph of a charming cobblestone street in a European village, golden hour, no people, no text"),
        ("airport terminal",    "professional stock photograph of a modern airport terminal with large windows and sunlight, travellers walking, no text"),
        ("road trip highway",   "professional travel stock photograph of an empty highway through desert landscape at sunset, dramatic sky, no text"),
        ("tropical beach hut",  "professional travel stock photograph of an overwater bungalow in clear turquoise tropical water, aerial view, no text"),
        ("city skyline night",  "professional travel stock photograph of a city skyline reflected in water at night, long exposure, no text"),
    ],
}


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def build_url(prompt: str, seed: int) -> str:
    encoded = urllib.parse.quote(prompt, safe="")
    return POLLINATIONS_BASE.format(
        prompt=encoded,
        w=IMAGE_WIDTH,
        h=IMAGE_HEIGHT,
        seed=seed,
        model=MODEL,
    )


def fetch_image(url: str, dest_path: Path, retries: int = 3) -> int | None:
    """Download image to dest_path, return file size in KB or None on failure."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "stock-photo-bot/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()

            # Reject obviously truncated or blank responses
            if len(data) < 10_000:
                print(f"    [warn] attempt {attempt+1}: response too small ({len(data)} bytes), retrying")
                time.sleep(PAUSE_SECS * 2)
                continue

            dest_path.write_bytes(data)
            return len(data) // 1024

        except Exception as exc:
            print(f"    [warn] attempt {attempt+1} failed: {exc}")
            time.sleep(PAUSE_SECS * 2)

    return None


def load_existing_index() -> dict:
    if INDEX_PATH.exists():
        try:
            return json.loads(INDEX_PATH.read_text())
        except json.JSONDecodeError:
            pass
    return {"total_images": 0, "generated_at": None, "images": []}


def main():
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    API_DIR.mkdir(parents=True, exist_ok=True)

    index = load_existing_index()
    existing_filenames = {img["filename"] for img in index["images"]}

    new_entries = []
    seed = 1000  # deterministic starting seed; incremented per image

    for category, items in CATALOGUE.items():
        print(f"\n── {category.upper()} ──")

        for keyword, prompt in items:
            filename = f"{category}_{slugify(keyword)}_1.png"

            if filename in existing_filenames:
                print(f"  [skip] {filename} already in index")
                seed += 1
                continue

            dest_path = IMAGES_DIR / filename
            url = build_url(prompt, seed)

            print(f"  [gen]  {keyword}")
            print(f"         seed={seed}  →  {filename}")

            size_kb = fetch_image(url, dest_path)

            if size_kb is None:
                print(f"  [fail] {filename} — skipped after retries")
            else:
                entry = {
                    "filename":        filename,
                    "source_keyword":  keyword,
                    "source_category": category,
                    "size_kb":         size_kb,
                    "width":           IMAGE_WIDTH,
                    "height":          IMAGE_HEIGHT,
                    "prompt":          prompt,
                    "seed":            seed,
                }
                new_entries.append(entry)
                print(f"  [ok]   {size_kb} KB")

            seed += 1
            time.sleep(PAUSE_SECS)

    # Merge and write index
    index["images"].extend(new_entries)
    index["total_images"] = len(index["images"])
    index["generated_at"] = datetime.now(timezone.utc).isoformat()

    INDEX_PATH.write_text(json.dumps(index, indent=2))

    print(f"\n✓ Done: {len(new_entries)} new images")
    print(f"  Total in index: {index['total_images']}")
    print(f"  Written to:     {INDEX_PATH}")


if __name__ == "__main__":
    main()
