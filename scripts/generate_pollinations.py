#!/usr/bin/env python3
"""
generate_pollinations.py  (v4 — negative prompts + people redesign)

Changes from v3:
  - NEGATIVE_PROMPT added to every URL: explicitly rejects deformed/extra/
    fused fingers and bad anatomy. This is the single biggest quality fix
    for any prompt involving hands.
  - business/team_collaboration replaced with a flat-lay of objects (no hands).
    Multiple hands from bird's-eye view is the hardest possible anatomy prompt;
    an object-only composition conveys the same concept with zero risk.
  - people category completely redesigned: silhouettes, from-behind shots, and
    long-distance figures. Real human presence, zero face/anatomy exposure.
    chef_hands is kept because it works (tomato is foreground, hands are secondary).
  - Parallel workers (4) retained from v3.
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

IMAGE_WIDTH  = 1344
IMAGE_HEIGHT = 896
MODEL        = "flux"
MAX_WORKERS  = 4
RETRY_PAUSE  = 8.0

QUALITY_SUFFIX = (
    ", sharp focus, high resolution, 4k, professional quality, "
    "no watermark, no text, no logo"
)

# Applied to every request via URL parameter.
# Explicit rejection matters more than prompt wording alone.
NEGATIVE_PROMPT = urllib.parse.quote(
    "deformed fingers, extra fingers, fused fingers, missing fingers, "
    "malformed hands, bad anatomy, disfigured, poorly drawn, "
    "blurry, out of focus, low quality, grainy, noisy, "
    "watermark, text, logo, signature, border, frame",
    safe=""
)

POLLINATIONS_BASE = (
    "https://image.pollinations.ai/prompt/{prompt}"
    "?width={w}&height={h}&seed={seed}&model={model}"
    "&nologo=true&enhance=true&nofeed=true"
    "&negative={negative}"
)

CATALOGUE = {
    "business": [
        ("remote work",
         "overhead flat lay of a laptop, coffee cup, notebook and pen on a clean white desk, morning light from window, minimal"),
        # team_collaboration: was "diverse hands pointing at blueprints" — replaced with
        # an object-only flat lay. Same business concept, zero anatomy risk.
        ("team collaboration",
         "top-down flat lay of large architectural blueprints with technical pens, ruler, compass and coffee cup on a dark oak conference table, professional planning session, no people, no hands"),
        ("startup office",
         "wide shot of a bright modern open-plan office with standing desks, plants and large windows, empty, clean and airy, golden hour light"),
        ("business growth",
         "close-up of a hand drawing a clean upward arrow on a whiteboard with a blue marker, white background, minimal, one hand only"),
        ("entrepreneur desk",
         "flat lay of a minimalist workspace: slim laptop, reading glasses, succulent plant, leather notebook on an oak desk, warm morning light"),
    ],
    "nature": [
        ("forest path",
         "sunlit forest path with tall trees and dappled golden light filtering through leaves, peaceful, misty background, no people"),
        ("mountain lake",
         "calm alpine lake perfectly reflecting surrounding snow-capped mountains at golden hour, no people, wide angle, mirror reflection"),
        ("wildflower meadow",
         "vast wildflower meadow in summer with red poppies and yellow flowers, blue sky, wide angle, no people"),
        ("ocean sunrise",
         "gentle waves washing over smooth sand on a beach at sunrise, soft pastel pink and orange sky, no people, long exposure"),
        ("urban garden",
         "raised vegetable garden beds in a sunny urban backyard with tomatoes, herbs and flowers growing, warm afternoon light, no people"),
    ],
    "technology": [
        ("circuit board macro",
         "extreme macro photograph of a green circuit board with gold components and copper traces, vivid detail, dark background"),
        ("server room",
         "modern data center corridor with blue LED-lit server racks receding into the distance, dramatic lighting, no people"),
        ("code on screen",
         "close-up of a dark-themed code editor on a monitor showing colourful syntax-highlighted code, slight blue glow, no people"),
        ("smartphone flatlay",
         "flat lay of a modern smartphone face-down next to a coffee cup and small succulent on a white marble surface, clean, minimal"),
        ("smart home devices",
         "collection of smart home devices neatly arranged on a white table: smart speaker, tablet, bulb and cables, overhead shot"),
    ],
    "people": [
        # Redesigned: silhouettes + from-behind shots + long-distance figures.
        # These give genuine human presence while completely avoiding face and
        # full-anatomy failure modes. chef_hands kept because it works well.
        ("window silhouette",
         "silhouette of a person standing at a large rain-streaked window looking at a misty city below, moody atmospheric light, peaceful, face not visible"),
        ("forest walker",
         "person walking away along a misty forest path in autumn, seen from behind, golden leaves, dappled light, cosy jacket, adventure and solitude"),
        ("park friends",
         "two friends sitting on a wooden park bench seen from behind, sunny afternoon, autumn trees, easy relaxed conversation, warm light"),
        ("cafe worker",
         "over-the-shoulder view of a person typing on a laptop in a warm independent cafe, coffee cup on table, blurred background, cosy and focused, face not visible"),
        ("chef hands",
         "close-up of hands slicing a ripe red tomato on a wooden chopping board in a professional kitchen, fresh basil leaves visible, natural light"),
    ],
    "abstract": [
        ("colour smoke",
         "swirling purple orange and teal coloured smoke against a pure black background, flowing, artistic, studio photography"),
        ("geometric minimal",
         "arrangement of clean pastel geometric shapes circles triangles rectangles on pure white background, studio lighting, shadows"),
        ("water macro",
         "extreme macro of water droplets on a glass surface refracting coloured light into jewel tones, black background"),
        ("bokeh golden",
         "out-of-focus golden bokeh circles on a rich dark background, warm and festive, smooth depth of field"),
        ("paper layers",
         "neatly arranged layers of torn white and cream paper textures, overhead flat lay, subtle soft shadows, minimal"),
    ],
    "food": [
        ("avocado toast",
         "overhead flat lay of avocado toast on sourdough with poached egg, microgreens and chilli flakes, white ceramic plate, bright natural light"),
        ("latte art",
         "close-up of a flat white coffee with a perfect leaf latte art pattern in a wide ceramic cup on a cafe table, warm natural tones"),
        ("grain bowl",
         "overhead flat lay of a colourful grain bowl with roasted vegetables, chickpeas, tahini and fresh herbs on a light grey surface"),
        ("farmers market",
         "overhead flat lay of fresh seasonal vegetables carrots tomatoes courgettes herbs on a wooden market table, vibrant natural colours"),
        ("sourdough loaf",
         "close-up of a freshly baked sourdough loaf with a cracked scored crust on a dark wooden board, warm kitchen light, steam rising"),
    ],
    "travel": [
        ("cobblestone village",
         "charming narrow cobblestone street lined with flower boxes in a southern European village, golden hour warm light, no people"),
        ("airport terminal",
         "wide angle interior of a bright modern airport terminal with floor-to-ceiling windows and dramatic natural light, no people, airy perspective"),
        ("desert highway",
         "straight empty two-lane highway cutting through red desert landscape toward distant mountains at sunset, dramatic cloudscape"),
        ("tropical water",
         "aerial view of an overwater bungalow in impossibly clear turquoise tropical water, white sand visible below, no people"),
        ("city reflection",
         "city skyline perfectly reflected in a perfectly still river at blue hour, long exposure, light trails, no people"),
    ],
}

_print_lock = threading.Lock()

def tprint(*args):
    with _print_lock:
        print(*args, flush=True)

def slugify(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")

def build_url(prompt, seed):
    full = prompt + QUALITY_SUFFIX
    encoded = urllib.parse.quote(full, safe="")
    return POLLINATIONS_BASE.format(
        prompt=encoded, w=IMAGE_WIDTH, h=IMAGE_HEIGHT,
        seed=seed, model=MODEL, negative=NEGATIVE_PROMPT,
    )

def generate_one(task):
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
                url, headers={"User-Agent": "stock-photo-bot/4.0"}
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = resp.read()

            if len(data) < 10_000:
                tprint(f"  [small] {filename} attempt {attempt+1} ({len(data)} B)")
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

    tprint(f"  [fail]  {filename}")
    return {"passed": False, "filename": filename}

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

    tasks = []
    seed  = 3000   # new seed range for v4 so prompts don't collide with v3
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
        print("All catalogue images already exist. Run regenerate.py to re-generate specific ones.")
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
    new_entries.sort(key=lambda e: (e["source_category"], e["source_keyword"]))

    index["images"].extend(new_entries)
    index["total_images"] = len(index["images"])
    index["generated_at"] = datetime.now(timezone.utc).isoformat()
    INDEX_PATH.write_text(json.dumps(index, indent=2))

    print(f"\nFinished in {elapsed/60:.1f} min")
    print(f"  Generated: {len(new_entries)}  |  Failed: {len(failed)}  |  Total: {index['total_images']}")
    if failed:
        print("  Failed files (run regenerate.py on these):")
        for f in failed:
            print(f"    python scripts/regenerate.py {f}")

if __name__ == "__main__":
    main()
