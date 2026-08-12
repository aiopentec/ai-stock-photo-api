#!/usr/bin/env python3
"""
generate_pollinations.py (v4) — Free fallback via Pollinations.ai
Used automatically when OPENAI_API_KEY is not set.
Includes negative prompts and redesigned people category.
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
    "&nologo=true&enhance=true&nofeed=true&negative={negative}"
)

IMAGE_WIDTH  = 1344
IMAGE_HEIGHT = 896
MODEL        = "flux"
MAX_WORKERS  = 4
RETRY_PAUSE  = 8.0

QUALITY_SUFFIX = ", sharp focus, high resolution, 4k, professional quality, no watermark, no text"

NEGATIVE_PROMPT = urllib.parse.quote(
    "deformed fingers, extra fingers, fused fingers, missing fingers, "
    "malformed hands, bad anatomy, disfigured, poorly drawn, "
    "blurry, low quality, watermark, text, logo", safe=""
)

CATALOGUE = {
    "business": [
        ("remote work",         "overhead flat lay of a laptop coffee cup notebook and pen on a clean white desk, morning light, minimal"),
        ("team collaboration",  "top-down flat lay of architectural blueprints with technical pens ruler compass and coffee cup on a dark oak conference table, no people, no hands"),
        ("startup office",      "wide shot of a bright modern open-plan office with standing desks plants and large windows, empty, golden hour light"),
        ("growth",              "close-up of one hand drawing an upward arrow on a whiteboard with a blue marker, minimal, white background"),
        ("entrepreneur desk",   "overhead flat lay of a minimal workspace: slim laptop glasses succulent plant leather notebook on oak desk, warm morning light"),
    ],
    "nature": [
        ("forest path",         "sunlit forest path with tall trees and dappled golden light filtering through leaves, peaceful, no people"),
        ("mountain lake",       "calm alpine lake perfectly reflecting snow-capped mountains at golden hour, no people, wide angle"),
        ("wildflower meadow",   "vast wildflower meadow in summer with red poppies and yellow flowers, blue sky, wide angle, no people"),
        ("ocean sunrise",       "gentle waves washing over smooth sand on a beach at sunrise, pastel pink and orange sky, no people"),
        ("urban garden",        "raised vegetable garden beds in a sunny urban backyard with tomatoes and herbs, warm afternoon light, no people"),
    ],
    "technology": [
        ("circuit board macro", "extreme macro of a green circuit board with gold components and copper traces, dark background"),
        ("server room",         "modern data center corridor with blue LED server racks receding into the distance, no people"),
        ("code on screen",      "dark-themed code editor on a monitor showing colourful syntax-highlighted code, no people"),
        ("smartphone flatlay",  "flat lay of a smartphone face-down next to a coffee cup and succulent on white marble, minimal"),
        ("smart home devices",  "smart home devices arranged on a white table: speaker tablet bulb cables, overhead shot"),
    ],
    "people": [
        ("window silhouette",   "silhouette of a person standing at a large window looking at a misty city below, moody light, face not visible"),
        ("forest walker",       "person walking away along a misty autumn forest path, seen from behind, golden leaves, cosy jacket"),
        ("park friends",        "two friends sitting on a park bench seen from behind, sunny afternoon, autumn trees, warm light"),
        ("cafe worker",         "over-the-shoulder view of a person typing on a laptop in a warm cafe, coffee cup beside them, face not visible"),
        ("chef hands",          "close-up of hands slicing a ripe red tomato on a wooden chopping board, professional kitchen, natural light"),
    ],
    "abstract": [
        ("colour smoke",        "swirling purple orange and teal coloured smoke against black background, flowing, artistic"),
        ("geometric minimal",   "arrangement of clean pastel geometric shapes circles triangles rectangles on white background, studio lighting"),
        ("water macro",         "extreme macro of water droplets on glass refracting coloured light into jewel tones, black background"),
        ("bokeh golden",        "out-of-focus golden bokeh circles on dark background, warm, smooth depth of field"),
        ("paper layers",        "layered torn white and cream paper textures, overhead flat lay, soft shadows, minimal"),
    ],
    "food": [
        ("avocado toast",       "overhead flat lay of avocado toast on sourdough with poached egg microgreens and chilli flakes, white ceramic plate, natural light"),
        ("latte art",           "close-up of a flat white coffee with leaf latte art in a ceramic cup on a wooden cafe table, warm tones"),
        ("grain bowl",          "overhead flat lay of a colourful grain bowl with roasted vegetables chickpeas and tahini, light grey surface"),
        ("farmers market",      "overhead flat lay of fresh vegetables carrots tomatoes courgettes on a wooden market table, vibrant colours"),
        ("sourdough loaf",      "close-up of a freshly baked sourdough loaf with cracked crust on dark wooden board, warm kitchen light"),
    ],
    "travel": [
        ("cobblestone village", "charming narrow cobblestone street with flower boxes in a European village, golden hour light, no people"),
        ("airport terminal",    "wide angle interior of a bright modern airport terminal with floor-to-ceiling windows, no people"),
        ("desert highway",      "straight empty highway cutting through red desert landscape toward mountains at sunset"),
        ("tropical water",      "aerial view of an overwater bungalow in clear turquoise water, white sand below, no people"),
        ("city reflection",     "city skyline reflected in a still river at blue hour, long exposure, no people"),
    ],
}

_print_lock = threading.Lock()
def tprint(*args): 
    with _print_lock: print(*args, flush=True)

def slugify(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")

def build_url(prompt, seed):
    encoded = urllib.parse.quote(prompt + QUALITY_SUFFIX, safe="")
    return POLLINATIONS_BASE.format(
        prompt=encoded, w=IMAGE_WIDTH, h=IMAGE_HEIGHT,
        seed=seed, model=MODEL, negative=NEGATIVE_PROMPT,
    )

def generate_one(task):
    filename  = task["filename"]
    dest_path = task["dest_path"]
    seed      = task["seed"]
    tprint(f"  [start] {task['category']}/{task['keyword']}  seed={seed}")
    for attempt in range(3):
        try:
            req = urllib.request.Request(build_url(task["prompt"], seed),
                                         headers={"User-Agent": "stock-photo-bot/4.0"})
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = resp.read()
            if len(data) < 10_000:
                tprint(f"  [small] {filename} attempt {attempt+1}")
                time.sleep(RETRY_PAUSE); continue
            dest_path.write_bytes(data)
            size_kb = len(data) // 1024
            tprint(f"  [ok]    {filename}  {size_kb} KB")
            return {"passed": True, "entry": {
                "filename": filename, "source_keyword": task["keyword"],
                "source_category": task["category"], "size_kb": size_kb,
                "width": IMAGE_WIDTH, "height": IMAGE_HEIGHT,
                "prompt": task["prompt"] + QUALITY_SUFFIX, "seed": seed,
            }}
        except Exception as exc:
            tprint(f"  [err]   {filename} attempt {attempt+1}: {exc}")
            time.sleep(RETRY_PAUSE)
    tprint(f"  [fail]  {filename}")
    return {"passed": False, "filename": filename}

def load_index():
    if INDEX_PATH.exists():
        try: return json.loads(INDEX_PATH.read_text())
        except: pass
    return {"total_images": 0, "generated_at": None, "images": []}

def main():
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    API_DIR.mkdir(parents=True, exist_ok=True)
    index    = load_index()
    existing = {img["filename"] for img in index["images"]}
    tasks, seed = [], 3000
    for category, items in CATALOGUE.items():
        for keyword, prompt in items:
            filename = f"{category}_{slugify(keyword)}_1.png"
            seed += 1
            if filename in existing: continue
            tasks.append({"category": category, "keyword": keyword, "prompt": prompt,
                          "filename": filename, "dest_path": IMAGES_DIR / filename, "seed": seed})
    if not tasks:
        print("All catalogue images already exist."); return
    print(f"Generating {len(tasks)} images via Pollinations (free) with {MAX_WORKERS} workers\n")
    t0 = time.time()
    new_entries, failed = [], []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(generate_one, task): task for task in tasks}
        for future in as_completed(futures):
            result = future.result()
            if result["passed"]: new_entries.append(result["entry"])
            else: failed.append(result["filename"])
    new_entries.sort(key=lambda e: (e["source_category"], e["source_keyword"]))
    index["images"].extend(new_entries)
    index["total_images"] = len(index["images"])
    index["generated_at"] = datetime.now(timezone.utc).isoformat()
    INDEX_PATH.write_text(json.dumps(index, indent=2))
    print(f"\nFinished in {(time.time()-t0)/60:.1f}m | Generated: {len(new_entries)} | Failed: {len(failed)} | Total: {index['total_images']}")

if __name__ == "__main__":
    main()
