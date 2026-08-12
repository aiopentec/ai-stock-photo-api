#!/usr/bin/env python3
"""
generate_dalle.py — Stock photo generation via DALL-E 3

Drop-in replacement for generate_pollinations.py when you need
reliable hands, people and fine detail.

Cost: $0.08/image HD 1792x1024 = ~$2.80 for 35 images (one-time)
      ~$0.80/week for 10 new weekly additions

Requires:
  pip install openai
  export OPENAI_API_KEY=sk-...   (or GitHub Actions secret)
"""

import base64
import json
import os
import re
import sys
import time
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime, timezone

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: openai package not installed. Run: pip install openai")
    sys.exit(1)

REPO_ROOT  = Path(__file__).resolve().parent.parent
IMAGES_DIR = REPO_ROOT / "images"
API_DIR    = REPO_ROOT / "api"
INDEX_PATH = API_DIR / "images.json"

DALLE_SIZE        = "1536x1024"
DALLE_QUALITY     = "high"
DALLE_MODEL       = "gpt-image-1"
IMAGE_WIDTH       = 1536
IMAGE_HEIGHT      = 1024
MAX_NEW_PER_RUN   = 3      # images generated per weekly run; increase when ready

# DALL-E 3 rate limit: 5 images/min on Tier 1
# 3 workers x 15s pause keeps well under that
MAX_WORKERS   = 3
REQUEST_PAUSE = 15.0

# ── Catalogue ────────────────────────────────────────────────────────────────
# Written as natural sentences - DALL-E 3 follows prose better than tags.
# "Photograph of" framing consistently gives photo-realistic results.
CATALOGUE = {
    "business": [
        ("remote work",
         "A clean overhead photograph of a modern home office desk with a slim laptop, ceramic coffee mug, open notebook and pen, shot from directly above in bright natural window light. Minimal and uncluttered."),
        ("team collaboration",
         "A top-down photograph of architectural blueprints spread across a dark oak conference table with technical pens, a brass compass and two coffee cups arranged around the edges. No people. Professional and atmospheric."),
        ("startup office",
         "A wide-angle photograph of a bright modern open-plan startup office with standing desks, hanging plants, exposed brick and floor-to-ceiling windows. Empty of people, late afternoon golden light streaming in."),
        ("growth",
         "A clean glass whiteboard showing a bold upward-trending arrow and a simple bar chart drawn in blue marker. Bright office background, no people, no hands, professional and minimal."),
        ("entrepreneur desk",
         "An overhead flat-lay photograph of a minimal workspace: a thin silver laptop, reading glasses, a small succulent in a white pot, and a leather-bound notebook on a pale oak desk, warm morning light from the left."),
    ],
    "nature": [
        ("forest path",
         "A photograph of a sunlit forest path winding through tall ancient trees with golden light filtering through the canopy and dappled shadows on the ground. Peaceful, no people, slight morning mist."),
        ("mountain lake",
         "A wide-angle photograph of a perfectly still alpine lake mirroring the snow-capped mountains and blue sky at golden hour. No people, breathtaking reflection, ultra-clear water."),
        ("wildflower meadow",
         "A photograph of a vast wildflower meadow in full summer bloom with red poppies, yellow buttercups and white daisies stretching to the horizon under a clear blue sky. No people, warm natural light."),
        ("ocean sunrise",
         "A long-exposure photograph of gentle waves washing softly over smooth dark sand on an empty beach at sunrise, with a pastel pink and orange sky reflected in the wet sand. No people."),
        ("urban garden",
         "A photograph of a thriving urban rooftop garden with raised wooden beds growing tomatoes, herbs and flowers, overlooking a city skyline in warm afternoon light. No people."),
    ],
    "technology": [
        ("circuit board macro",
         "An extreme close-up macro photograph of a vivid green circuit board with gold through-hole components, copper traces and surface-mount chips, shot against a dark background with precise studio lighting."),
        ("server room",
         "A photograph taken along the corridor of a modern data center, with rows of blue LED-lit server racks receding into the distance. No people, atmospheric and precise."),
        ("code on screen",
         "A photograph of a large monitor showing colourful syntax-highlighted code in a dark theme editor, soft blue glow on the desk. No people, no faces."),
        ("smartphone flatlay",
         "An overhead flat-lay photograph of a modern smartphone placed face-down beside a ceramic espresso cup and a small succulent on white marble. Clean and minimal."),
        ("smart home devices",
         "An overhead photograph of smart home devices — a cylindrical speaker, smart display, smart bulb and braided cables — neatly arranged on a white surface with soft shadows."),
    ],
    "people": [
        # DALL-E 3 handles people anatomy correctly. These prompts use
        # natural poses in good lighting for consistently clean results.
        ("window silhouette",
         "A moody atmospheric photograph of a person standing at a tall rain-streaked window, looking out over a misty city. The person faces away from camera, warm room light creating a gentle glow around their outline. No face visible."),
        ("forest walker",
         "A photograph of a young person walking away from the camera along a misty autumn forest trail, wearing a cosy knit jacket with a backpack, surrounded by golden fallen leaves. Shot from behind, soft natural light."),
        ("park friends",
         "A warm photograph of two friends sitting on a wooden park bench seen from behind, looking out at a golden autumn park. Relaxed body language, late afternoon sun filtering through the trees behind them."),
        ("cafe worker",
         "An over-the-shoulder photograph of a person working on a laptop in a cosy independent café. A latte in a ceramic cup beside them, warm bokeh in the background. Shot from behind, face not visible."),
        ("chef hands",
         "A close-up photograph of a professional chef's hands carefully slicing a ripe red tomato on a wooden chopping board. Fresh basil leaves and other vegetables in the background. Sharp focus on the hands and knife, natural light."),
    ],
    "abstract": [
        ("colour smoke",
         "A fine-art photograph of swirling purple, burnt orange and teal coloured smoke against a pure black background, the smoke forming elegant flowing curves and translucent layers."),
        ("geometric minimal",
         "A clean studio photograph of an arrangement of matte pastel geometric shapes — circles, triangles and rectangles in blush pink, sage green and warm beige — on a white surface with soft precise shadows."),
        ("water macro",
         "An extreme macro photograph of water droplets on glass, each droplet refracting coloured light into jewel tones of teal, amber and magenta against a deep black background."),
        ("bokeh golden",
         "A fine-art photograph of soft golden bokeh circles of varying sizes against a deep dark background. Shot on a fast prime lens for perfectly smooth circular bokeh. Warm and festive."),
        ("paper layers",
         "An overhead flat-lay photograph of neatly layered and torn sheets of white, cream and pale grey paper with subtle texture, creating a minimal composition with precise soft shadows."),
    ],
    "food": [
        ("avocado toast",
         "An overhead flat-lay food photograph of sourdough avocado toast with a perfectly poached egg, microgreens, chilli flakes and sea salt on a wide white ceramic plate. Bright natural light from the side."),
        ("latte art",
         "A close-up photograph of a flat white coffee with a beautifully executed tulip latte art pattern in a wide ceramic cup on a wooden café table. Warm ambient light."),
        ("grain bowl",
         "An overhead flat-lay food photograph of a nourishing grain bowl with roasted sweet potato, chickpeas, avocado, microgreens and a tahini drizzle on a light grey linen surface, natural side light."),
        ("farmers market",
         "An overhead flat-lay photograph of a vibrant selection of fresh seasonal vegetables — heirloom tomatoes, rainbow carrots, courgettes and fresh herbs — arranged naturally on a worn wooden market table."),
        ("sourdough loaf",
         "A close-up photograph of a freshly baked artisan sourdough loaf with a beautifully scored crust on a dark wooden board in a warm kitchen. Slight steam rising from the crust."),
    ],
    "travel": [
        ("cobblestone village",
         "A photograph of a charming narrow cobblestone street in a sun-drenched southern European village, lined with terracotta flower pots and stone buildings glowing in golden hour light. No people."),
        ("airport terminal",
         "A wide-angle photograph of the interior of a grand modern airport terminal with soaring floor-to-ceiling windows flooding the space with natural light. No people."),
        ("desert highway",
         "A photograph of a straight two-lane highway cutting through a vast red desert landscape toward distant purple mountains under a dramatic sunset sky with streaked clouds."),
        ("tropical water",
         "An aerial photograph of an overwater bungalow surrounded by impossibly clear turquoise water, the sandy ocean floor visible below the surface. No people."),
        ("city reflection",
         "A long-exposure photograph of a vibrant city skyline perfectly reflected in a completely still river at blue hour, building lights creating shimmering trails in the water."),
    ],
}

_print_lock = threading.Lock()

def tprint(*args):
    with _print_lock:
        print(*args, flush=True)

def slugify(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")

def load_index():
    if INDEX_PATH.exists():
        try:
            return json.loads(INDEX_PATH.read_text())
        except json.JSONDecodeError:
            pass
    return {"total_images": 0, "generated_at": None, "images": []}

def download_url(url, dest_path):
    """Download image from a URL (DALL-E 3 style response)."""
    req = urllib.request.Request(url, headers={"User-Agent": "stock-photo-bot/dalle"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    dest_path.write_bytes(data)
    return len(data) // 1024

def save_b64(b64_data, dest_path):
    """Save base64-encoded image (gpt-image-1 style response)."""
    data = base64.b64decode(b64_data)
    dest_path.write_bytes(data)
    return len(data) // 1024

def generate_one(task, client):
    category  = task["category"]
    keyword   = task["keyword"]
    prompt    = task["prompt"]
    filename  = task["filename"]
    dest_path = task["dest_path"]

    tprint(f"  [start] {category}/{keyword}")

    for attempt in range(3):
        try:
            response = client.images.generate(
                model=DALLE_MODEL,
                prompt=prompt,
                size=DALLE_SIZE,
                quality=DALLE_QUALITY,
                n=1,
            )
            # gpt-image-1 returns base64; dall-e-3 returned a URL.
            # Handle both so the script works regardless of which model is active.
            item = response.data[0]
            if getattr(item, 'b64_json', None):
                size_kb = save_b64(item.b64_json, dest_path)
                revised_prompt = prompt
            elif getattr(item, 'url', None):
                size_kb = download_url(item.url, dest_path)
                revised_prompt = getattr(item, 'revised_prompt', None) or prompt
            else:
                tprint(f"  [err]   {filename}: no image data in response")
                time.sleep(REQUEST_PAUSE)
                continue

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
                    "prompt":          revised_prompt,
                    "model":           DALLE_MODEL,
                },
            }

        except Exception as exc:
            err = str(exc)
            if "rate_limit" in err.lower() or "429" in err:
                tprint(f"  [rate]  {filename} — waiting 60s")
                time.sleep(60)
                continue
            if "content_policy" in err.lower():
                tprint(f"  [skip]  {filename} — content policy")
                return {"passed": False, "filename": filename}
            tprint(f"  [err]   {filename} attempt {attempt+1}: {exc}")
            time.sleep(REQUEST_PAUSE)

    return {"passed": False, "filename": filename}

def main():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set.")
        print("Set it at https://platform.openai.com/api-keys")
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    API_DIR.mkdir(parents=True, exist_ok=True)

    index    = load_index()
    existing = {img["filename"] for img in index["images"]}

    tasks = []
    for category, items in CATALOGUE.items():
        for keyword, prompt in items:
            filename = f"{category}_{slugify(keyword)}_1.png"
            if filename in existing:
                continue
            tasks.append({
                "category":  category,
                "keyword":   keyword,
                "prompt":    prompt,
                "filename":  filename,
                "dest_path": IMAGES_DIR / filename,
            })

    if not tasks:
        print("All catalogue images already exist.")
        return

    # Limit to MAX_NEW_PER_RUN per weekly run to control spend.
    # Increase this constant when ready to scale.
    if len(tasks) > MAX_NEW_PER_RUN:
        print(f"Limiting to {MAX_NEW_PER_RUN} images this run "
              f"({len(tasks)} pending total — rest will generate in future runs)")
        tasks = tasks[:MAX_NEW_PER_RUN]

    print(f"Generating {len(tasks)} images via {DALLE_MODEL} ({DALLE_QUALITY}, {DALLE_SIZE})")
    print(f"Check platform.openai.com/docs for current {DALLE_MODEL} pricing\n")

    t0 = time.time()
    new_entries, failed = [], []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(generate_one, task, client): task for task in tasks}
        for future in as_completed(futures):
            result = future.result()
            if result["passed"]:
                new_entries.append(result["entry"])
            else:
                failed.append(result["filename"])
            time.sleep(REQUEST_PAUSE / MAX_WORKERS)

    new_entries.sort(key=lambda e: (e["source_category"], e["source_keyword"]))
    index["images"].extend(new_entries)
    index["total_images"] = len(index["images"])
    index["generated_at"] = datetime.now(timezone.utc).isoformat()
    INDEX_PATH.write_text(json.dumps(index, indent=2))

    print(f"\nFinished in {int((time.time()-t0)/60)}m")
    print(f"  Generated: {len(new_entries)}  |  Failed: {len(failed)}  |  Total: {index['total_images']}")
    if failed:
        print("  Failed:", ", ".join(failed))

if __name__ == "__main__":
    main()
