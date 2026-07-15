#!/usr/bin/env python3
"""
generate_pollinations.py  (v3 — parallel generation)

Key change from v2: images are generated concurrently using
ThreadPoolExecutor (4 workers by default). This cuts the first-run
wall-clock time from ~28 minutes to ~7-8 minutes without hammering
Pollinations harder — the same number of requests go out, just
overlapping rather than queued.

Thread-safety notes:
  - Seeds are pre-assigned before the pool starts (no shared counter).
  - Index writes happen after all workers finish (no concurrent writes).
  - Console output uses a threading.Lock so lines don't interleave.

Subsequent runs skip already-indexed images, so weekly updates
(adding a handful of new catalogue entries) take 2-5 minutes regardless.
"""

import json
import re
import time
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT  = Path(__file__).resolve().parent.parent
IMAGES_DIR = REPO_ROOT / "images"
API_DIR    = REPO_ROOT / "api"
INDEX_PATH = API_DIR / "images.json"

POLLINATIONS_BASE = (
    "https://image.pollinations.ai/prompt/{prompt}"
    "?width={w}&height={h}&seed={seed}&model={model}"
    "&nologo=true&enhance=true&nofeed=true"
)

IMAGE_WIDTH   = 1344
IMAGE_HEIGHT  = 896
MODEL         = "flux"
MAX_WORKERS   = 4      # concurrent requests; safe for Pollinations free tier
RETRY_PAUSE   = 8.0    # seconds between retries on the SAME image (not between images)

QUALITY_SUFFIX = (
    ", sharp focus, high resolution, 4k, professional quality, "
    "no blur, no distortion, no watermark, no text"
)

CATALOGUE = {
    "business": [
        ("remote work",
         "overhead flat lay of a laptop, coffee cup, notebook and pen on a clean white desk, morning light from window, minimal"),
        ("team collaboration",
         "top-down view of diverse hands pointing at architectural blueprints on a conference table, planning session, natural light"),
        ("startup office",
         "wide shot of a bright modern open-plan office with standing desks, plants, large windows, empty, clean and airy"),
        ("business growth",
         "close-up of a hand drawing an upward arrow on a whiteboard with coloured markers, minimal background"),
        ("entrepreneur desk",
         "flat lay of a minimalist workspace: laptop, glasses, succulent plant, notebook on oak desk, warm morning light"),
    ],
    "nature": [
        ("forest path",
         "sunlit forest path with tall trees and dappled golden light filtering through leaves, peaceful, no people"),
        ("mountain lake",
         "calm alpine lake perfectly reflecting surrounding snow-capped mountains at golden hour, no people, wide angle"),
        ("wildflower meadow",
         "vast wildflower meadow in summer with red poppies and yellow flowers, blue sky, wide angle, no people"),
        ("ocean sunrise",
         "gentle waves washing over smooth sand on a beach at sunrise, soft pastel pink and orange sky, no people"),
        ("urban garden",
         "raised vegetable garden beds in a sunny urban backyard with tomatoes and herbs growing, warm afternoon light, no people"),
    ],
    "technology": [
        ("circuit board macro",
         "extreme macro photograph of a green circuit board with gold components and copper traces, vivid detail, dark background"),
        ("server room",
         "modern data center corridor with blue LED-lit server racks receding into the distance, dramatic lighting, no people"),
        ("code on screen",
         "close-up of a dark-themed code editor on a monitor showing colourful syntax-highlighted code, slight glow, no people"),
        ("smartphone flatlay",
         "flat lay of a modern smartphone face-down next to a coffee cup and succulent on a white marble surface, minimal"),
        ("smart home devices",
         "collection of smart home devices arranged on a white table: speaker, tablet, smart bulb, cable, overhead shot"),
    ],
    "people": [
        ("reading hands",
         "close-up of relaxed hands holding an open paperback book, sunlight falling across the pages, warm tones"),
        ("creative hands",
         "close-up of hands sketching in a spiral notebook with a fine pen, wooden desk, natural window light"),
        ("connection hands",
         "overhead close-up of two pairs of hands gently clasped together on a light oak table, warm afternoon sunlight"),
        ("typing hands",
         "close-up of hands typing on a slim laptop keyboard, clean white desk, soft indoor light, minimal"),
        ("chef hands",
         "close-up of hands slicing a ripe red tomato on a wooden chopping board, professional kitchen counter, natural light"),
    ],
    "abstract": [
        ("colour smoke",
         "swirling purple orange and teal coloured smoke against a pure black background, flowing, artistic, studio"),
        ("geometric minimal",
         "arrangement of clean pastel geometric shapes circles triangles rectangles on white background, studio lighting"),
        ("water macro",
         "extreme macro of water droplets on a glass surface refracting coloured light, jewel tones, black background"),
        ("bokeh golden",
         "out-of-focus golden bokeh circles on a dark background, warm and festive, smooth gradient"),
        ("paper layers",
         "neatly arranged layers of torn white and cream paper textures, overhead flat lay, soft shadows, minimal"),
    ],
    "food": [
        ("avocado toast",
         "overhead flat lay of avocado toast on sourdough with poached egg, microgreens and chilli flakes, white ceramic plate, bright natural light"),
        ("latte art",
         "close-up of a flat white coffee with a leaf latte art pattern in a wide ceramic cup on a wooden cafe table, warm tones"),
        ("grain bowl",
         "overhead flat lay of a colourful grain bowl with roasted vegetables chickpeas and tahini on a light grey surface, natural light"),
        ("farmers market",
         "overhead flat lay of fresh seasonal vegetables carrots tomatoes courgettes on a wooden market table, vibrant colours"),
        ("sourdough loaf",
         "close-up of a freshly baked sourdough loaf with a cracked scored crust on a dark wooden board, warm kitchen light"),
    ],
    "travel": [
        ("cobblestone village",
         "charming narrow cobblestone street lined with flower boxes in a European village, golden hour light, no people"),
        ("airport terminal",
         "wide angle interior of a bright modern airport terminal with floor-to-ceiling windows and natural light, no people, airy"),
        ("desert highway",
         "straight empty two-lane highway cutting through red desert landscape toward distant mountains at sunset, dramatic sky"),
        ("tropical water",
         "aerial view of an overwater bungalow in impossibly clear turquoise tropical water, white sand visible below, no people"),
        ("city reflection",
         "city skyline perfectly reflected in a still river at blue hour, long exposure, lights streaking, no people"),
    ],
}

# ── Thread-safe console output ─────────────────────────────────────────────
_print_lock = threading.Lock()

def tprint(*args):
    with _print_lock:
        print(*args, flush=True)


# ── URL builder ────────────────────────────────────────────────────────────
def slugify(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")

def build_url(prompt, seed):
    full = prompt + QUALITY_SUFFIX
    encoded = urllib.parse.quote(full, safe="")
    return POLLINATIONS_BASE.format(
        prompt=encoded, w=IMAGE_WIDTH, h=IMAGE_HEIGHT,
        seed=seed, model=MODEL,
    )


# ── Single-image worker ────────────────────────────────────────────────────
def generate_one(task):
    """
    task = {category, keyword, prompt, filename, dest_path, seed}
    Returns a result dict (passed=True/False, entry or reason).
    """
    category  = task["category"]
    keyword   = task["keyword"]
    filename  = task["filename"]
    dest_path = task["dest_path"]
    seed      = task["seed"]
    url       = build_url(task["prompt"], seed)

    tprint(f"  [start] {category}/{keyword}  seed={seed}")

    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "stock-photo-bot/3.0"}
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = resp.read()

            if len(data) < 10_000:
                tprint(f"  [small] {filename} attempt {attempt+1} ({len(data)} B) — retry")
                time.sleep(RETRY_PAUSE)
                continue

            dest_path.write_bytes(data)
            size_kb = len(data) // 1024
            tprint(f"  [ok]    {filename}  {size_kb} KB")
            return {
                "passed": True,
                "entry": {
                    "filename":        filename,
                    "source_keyword":  keyword,
                    "source_category": category,
                    "size_kb":         size_kb,
                    "width":           IMAGE_WIDTH,
                    "height":          IMAGE_HEIGHT,
                    "prompt":          task["prompt"] + QUALITY_SUFFIX,
                    "seed":            seed,
                },
            }

        except Exception as exc:
            tprint(f"  [err]   {filename} attempt {attempt+1}: {exc}")
            time.sleep(RETRY_PAUSE)

    tprint(f"  [fail]  {filename} — skipped after 3 attempts")
    return {"passed": False, "filename": filename}


# ── Main ───────────────────────────────────────────────────────────────────
def load_index():
    if INDEX_PATH.exists():
        try:
            return json.loads(INDEX_PATH.read_text())
        except json.JSONDecodeError:
            pass
    return {"total_images": 0, "generated_at": None, "images": []}


def main():
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    API_DIR.mkdir(parents=True, exist_ok=True)

    index    = load_index()
    existing = {img["filename"] for img in index["images"]}

    # Build task list with pre-assigned seeds (thread-safe — no shared counter)
    tasks = []
    seed  = 2000
    for category, items in CATALOGUE.items():
        for keyword, prompt in items:
            filename = f"{category}_{slugify(keyword)}_1.png"
            seed += 1
            if filename in existing:
                continue
            tasks.append({
                "category":  category,
                "keyword":   keyword,
                "prompt":    prompt,
                "filename":  filename,
                "dest_path": IMAGES_DIR / filename,
                "seed":      seed,
            })

    if not tasks:
        print("Nothing to generate — all catalogue images already exist.")
        return

    print(f"Generating {len(tasks)} images with {MAX_WORKERS} parallel workers...\n")
    t0 = time.time()

    new_entries = []
    failed      = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(generate_one, task): task for task in tasks}
        for future in as_completed(futures):
            result = future.result()
            if result["passed"]:
                new_entries.append(result["entry"])
            else:
                failed.append(result["filename"])

    elapsed = time.time() - t0
    print(f"\nFinished in {elapsed/60:.1f} min")
    print(f"  Generated : {len(new_entries)}")
    print(f"  Failed    : {len(failed)}")
    if failed:
        for f in failed:
            print(f"    - {f}")

    # Sort so index order is stable (as_completed order is non-deterministic)
    new_entries.sort(key=lambda e: (e["source_category"], e["source_keyword"]))

    index["images"].extend(new_entries)
    index["total_images"]  = len(index["images"])
    index["generated_at"]  = datetime.now(timezone.utc).isoformat()
    INDEX_PATH.write_text(json.dumps(index, indent=2))

    print(f"  Index total: {index['total_images']} images")


if __name__ == "__main__":
    main()
