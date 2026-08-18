#!/usr/bin/env python3
"""
generate_dalle.py — Stock photo generation via OpenAI gpt-image-1

Generates images from the CATALOGUE below, skipping any that already
exist in api/images.json. MAX_NEW_PER_RUN controls spend per weekly run.

Cost: ~$0.29/image at high quality (gpt-image-1, 1536x1024)
      3 images/week = ~$0.87/week = ~$3.76/month

To add new weekly content: append new (keyword, prompt) tuples to any
category in CATALOGUE. The weekly run automatically picks up the first
MAX_NEW_PER_RUN entries not yet in the index.
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

DALLE_SIZE    = "1536x1024"
DALLE_QUALITY = "high"
DALLE_MODEL   = "gpt-image-1"
IMAGE_WIDTH   = 1536
IMAGE_HEIGHT  = 1024

MAX_NEW_PER_RUN = 3      # images per weekly run; increase when ready to scale
MAX_WORKERS     = 3
REQUEST_PAUSE   = 15.0

# ── CATALOGUE ──────────────────────────────────────────────────────────────────
# Add new (keyword, prompt) tuples to any category to queue future images.
# The weekly run generates the first MAX_NEW_PER_RUN entries not yet in index.
# Keyword becomes part of the filename: {category}_{slugify(keyword)}_1.png
# IMPORTANT: keyword must NOT start with the category name or filename gets
# a double prefix. E.g. use "growth" not "business growth" in "business".
CATALOGUE = {
    "business": [
        # ── Generated ──────────────────────────────────────
        ("remote work",
         "Overhead flat lay of a modern home office desk with a slim laptop, ceramic coffee mug, open notebook and pen, bright natural window light. Minimal and professional."),
        ("team collaboration",
         "Top-down flat lay of architectural blueprints spread across a dark oak conference table with technical pens, a brass compass and coffee cups. No people. Professional planning atmosphere."),
        ("startup office",
         "Wide-angle view of a bright modern open-plan startup office with standing desks, hanging plants and floor-to-ceiling windows. Empty of people, golden late afternoon light."),
        ("growth",
         "A clean glass whiteboard showing a bold upward-trending arrow and a simple bar chart drawn in blue marker. Bright office background, no people, no hands, professional and minimal."),
        ("entrepreneur desk",
         "Overhead flat-lay of a minimal workspace: a thin silver laptop, reading glasses, small succulent plant, leather notebook on a pale oak desk. Warm morning light from left."),
        # ── Pending — added weekly ─────────────────────────
        ("coworking space",
         "Wide photograph of a bright modern coworking space with long communal tables, pendant lights, plants and large windows. Several empty MacBooks open on tables. No faces visible."),
        ("business meeting",
         "Overhead flat lay of a round meeting table with notebooks, pens, a laptop and coffee cups arranged neatly. No people. Clean, professional, natural light."),
        ("brainstorm wall",
         "A glass wall covered with colourful sticky notes and mind-map diagrams in a bright modern office. No people, wide angle, natural light."),
        ("coffee meeting",
         "Two ceramic coffee cups on a wooden café table with a small notebook and pen between them. Warm bokeh background. No people, overhead angle."),
        ("business plan",
         "Flat lay of a business plan document, a fountain pen, reading glasses and a small succulent on a white desk. Clean and professional. No people."),
    ],
    "nature": [
        # ── Generated ──────────────────────────────────────
        ("forest path",
         "A sunlit forest path winding through tall trees with golden light filtering through the canopy. Peaceful, no people, soft morning mist."),
        ("mountain lake",
         "A perfectly still alpine lake mirroring snow-capped mountains at golden hour. No people, wide angle, breathtaking reflection."),
        ("wildflower meadow",
         "A vast wildflower meadow in full summer bloom with red poppies and yellow flowers under a clear blue sky. No people, warm natural light."),
        ("ocean sunrise",
         "Gentle waves washing over smooth sand on an empty beach at sunrise. Soft pastel pink and orange sky reflected in the wet sand. No people."),
        ("urban garden",
         "A thriving urban rooftop garden with raised wooden beds growing tomatoes, herbs and flowers. City skyline in the warm background. No people."),
        # ── Pending ────────────────────────────────────────
        ("autumn forest",
         "A wide path through a deciduous forest in full autumn colour, golden and red leaves covering the ground and hanging from the trees. Soft light, no people."),
        ("spring garden",
         "A lush spring garden in full bloom with pink cherry blossoms, tulips and fresh green grass. Soft morning light, no people."),
        ("mountain sunset",
         "A dramatic mountain range silhouetted against a vivid orange and purple sunset sky. Wide angle, no people, no buildings."),
        ("desert dunes",
         "Sweeping golden sand dunes in a vast desert under a deep blue sky, long shadows from the dune ridges. No people, wide angle."),
        ("tropical rainforest",
         "Dense tropical rainforest with massive ferns, hanging vines and dappled light filtering through the canopy. No people, lush and green."),
    ],
    "technology": [
        # ── Generated ──────────────────────────────────────
        ("circuit board macro",
         "Extreme close-up macro of a vivid green circuit board with gold components and copper traces against a dark background."),
        ("server room",
         "A modern data center corridor with blue LED-lit server racks receding into the distance. No people, atmospheric."),
        ("code on screen",
         "A large monitor showing colourful syntax-highlighted code in a dark theme editor. Soft blue glow on the desk. No people."),
        ("smartphone flat lay",
         "Overhead flat-lay of a modern smartphone placed face-down beside a ceramic espresso cup and small succulent on white marble. Minimal."),
        ("smart home devices",
         "Overhead flat-lay of smart home devices neatly arranged on a white surface: speaker, display, smart bulb and braided cables."),
        # ── Pending ────────────────────────────────────────
        ("solar panels roof",
         "Aerial view of a house roof covered with sleek black solar panels, surrounded by green garden. No people, bright sunny day."),
        ("electric car charging",
         "A modern electric car plugged into a white charging station in a bright clean garage. No people, minimal background."),
        ("3d printer",
         "Close-up of a 3D printer in action, extruding white filament to build a small geometric object. Blue light, dark background."),
        ("VR headset",
         "A modern VR headset and controllers placed on a white surface with a blurred tech background. Clean, minimal, no people."),
        ("drone aerial",
         "A consumer drone hovering against a clear blue sky, photographed from below at a slight angle. Minimal background, sharp detail."),
    ],
    "people": [
        # ── Generated ──────────────────────────────────────
        ("window silhouette",
         "Silhouette of a person standing at a large rain-streaked window looking out over a misty city. Moody atmospheric light. Face not visible."),
        ("forest walker",
         "A person walking away along a misty autumn forest trail. Seen from behind, cosy jacket and backpack. Golden fallen leaves."),
        ("park friends",
         "Two friends sitting on a wooden park bench seen from behind. Golden autumn park scene, warm late afternoon sunlight."),
        ("cafe worker",
         "Over-the-shoulder view of a person typing on a laptop in a warm café. A latte beside them, warm bokeh background. Face not visible."),
        ("chef hands",
         "Close-up of a professional chef's hands carefully slicing a ripe red tomato on a wooden chopping board. Fresh basil nearby, natural light."),
        # ── Pending ────────────────────────────────────────
        ("yoga silhouette",
         "Silhouette of a person in a yoga warrior pose on a hilltop against a vivid orange and pink sunrise sky. Peaceful and inspiring. Face not visible."),
        ("runner sunrise",
         "A lone runner seen from behind on an empty coastal path at sunrise, ocean to one side. Warm golden light, energetic atmosphere."),
        ("cyclist path",
         "A cyclist seen from behind riding along a scenic tree-lined country path in autumn. Dappled light, relaxed pace."),
        ("couple sunset",
         "Two people sitting together on a clifftop watching a vivid ocean sunset. Seen from behind, silhouetted against the sky. Romantic."),
        ("reading cafe",
         "A person sitting alone in a cosy window seat of a café, reading a book, seen in profile. Warm afternoon light, coffee on the table."),
    ],
    "abstract": [
        # ── Generated ──────────────────────────────────────
        ("colour smoke",
         "Swirling purple, burnt orange and teal coloured smoke against a pure black background. Elegant flowing curves and translucent layers."),
        ("geometric minimal",
         "Clean studio arrangement of matte pastel geometric shapes in blush pink, sage green and warm beige on a white surface with soft shadows."),
        ("water macro",
         "Extreme macro of water droplets on glass refracting coloured light into jewel tones of teal, amber and magenta against black."),
        ("bokeh golden",
         "Soft golden bokeh circles against a deep dark background. Shot on a fast prime lens, perfectly smooth circular bokeh. Warm and festive."),
        ("paper layers",
         "Neatly layered torn sheets of white, cream and pale grey paper textures in an overhead flat-lay with subtle soft shadows."),
        # ── Pending ────────────────────────────────────────
        ("neon bokeh",
         "Blurred neon lights in pink, cyan and yellow creating an abstract bokeh pattern against a dark urban background. Vibrant and modern."),
        ("liquid marble",
         "Swirling liquid marble texture in white, grey and gold. Top-down view, smooth flowing patterns, studio photography."),
        ("holographic gradient",
         "Abstract holographic foil texture in iridescent pink, blue and gold. Macro view, smooth metallic surface, studio lighting."),
        ("crystal refraction",
         "Macro photograph of light refracting through a clear crystal prism, creating rainbow spectrum patterns on a white surface."),
        ("sand texture",
         "Macro photograph of fine white sand with delicate ripple patterns and tiny shadows. Overhead, meditative, minimal."),
    ],
    "food": [
        # ── Generated ──────────────────────────────────────
        ("avocado toast",
         "Overhead flat-lay of sourdough avocado toast with a perfectly poached egg, microgreens and chilli flakes on a white ceramic plate. Bright natural light."),
        ("latte art",
         "Close-up of a flat white coffee with a tulip latte art pattern in a wide ceramic cup on a wooden café table. Warm natural tones."),
        ("grain bowl",
         "Overhead flat-lay of a nourishing grain bowl with roasted sweet potato, chickpeas, avocado and tahini on a light grey linen surface."),
        ("farmers market",
         "Overhead flat-lay of fresh seasonal vegetables — heirloom tomatoes, rainbow carrots, courgettes and herbs — on a worn wooden market table."),
        ("sourdough loaf",
         "Close-up of a freshly baked artisan sourdough loaf with a beautifully scored crust on a dark wooden board. Warm kitchen light, slight steam."),
        # ── Pending ────────────────────────────────────────
        ("smoothie bowl",
         "Overhead flat-lay of a vibrant acai smoothie bowl topped with fresh berries, banana slices, granola and coconut flakes on a white surface. Bright and colourful."),
        ("matcha latte",
         "Close-up of a matcha latte in a wide ceramic cup with a simple swirled pattern on a light marble surface. Soft natural light."),
        ("vegan plate",
         "Overhead flat-lay of a beautifully arranged vegan dinner plate with roasted vegetables, hummus, olives and flatbread on a dark slate surface."),
        ("fresh herbs",
         "Flat lay of a selection of fresh herbs — basil, rosemary, thyme and mint — arranged on white marble. Clean, bright, minimal."),
        ("charcuterie board",
         "Overhead flat-lay of a rustic wooden board with artisan cheese, crackers, grapes, nuts and honey. Warm tones, appetising arrangement."),
    ],
    "travel": [
        # ── Generated ──────────────────────────────────────
        ("cobblestone village",
         "A charming narrow cobblestone street in a sun-drenched southern European village, flower pots and stone buildings in golden hour light. No people."),
        ("airport terminal",
         "Wide-angle interior of a grand modern airport terminal with soaring windows and natural light. No people, clean architecture."),
        ("desert highway",
         "A straight two-lane highway cutting through a vast red desert landscape toward distant mountains. Dramatic sunset sky."),
        ("tropical water",
         "Aerial view of an overwater bungalow in impossibly clear turquoise water, sandy floor visible below. No people."),
        ("city reflection",
         "City skyline perfectly reflected in a still river at blue hour. Long-exposure, building lights shimmering in the water. No people."),
        # ── Pending ────────────────────────────────────────
        ("mountain hiking trail",
         "A winding hiking trail ascending through alpine meadows toward snow-capped peaks under a clear blue sky. No people, wide angle."),
        ("old train station",
         "Interior of a grand historic train station with arched iron and glass roof, shafts of light falling through. No people, dramatic atmosphere."),
        ("canal boats",
         "Colourful narrow boats moored along a quiet English canal in summer, lined by weeping willows. No people, golden afternoon light."),
        ("night market",
         "A vibrant Asian night market street scene with glowing lanterns and illuminated food stalls. Warm and atmospheric. No faces visible."),
        ("lighthouse coast",
         "A white and red striped lighthouse on a dramatic rocky coastal headland at sunset. No people, wide angle, vivid sky."),
    ],
    # ── NEW CATEGORY: Sustainable Living ──────────────────────────────────────
    # Aligned with the upcycling blog audience — underserved niche in free
    # stock photo libraries; differentiates this site from generic galleries.
    "sustainable": [
        ("upcycled furniture",
         "A beautifully refinished vintage wooden dresser with new brass handles in a bright Scandinavian-style room. No people, warm natural light."),
        ("zero waste kitchen",
         "A clean, minimal kitchen counter with glass storage jars, a bamboo dish brush, cloth produce bags and fresh vegetables. No people, natural light."),
        ("compost garden",
         "Close-up of hands holding dark, rich compost soil with visible organic matter, above a wooden compost bin in a garden. Warm light."),
        ("sustainable products",
         "Flat lay of zero-waste lifestyle products on a natural linen surface: bamboo toothbrush, soap bar, reusable bag, glass bottle. Minimal and clean."),
        ("community garden",
         "Wide shot of a thriving community vegetable garden with raised beds, trellises and flowers in an urban setting. No people, golden afternoon light."),
    ],
}


_print_lock = threading.Lock()

def tprint(*args):
    with _print_lock:
        print(*args, flush=True)

def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")

def load_index() -> dict:
    if INDEX_PATH.exists():
        try:
            return json.loads(INDEX_PATH.read_text())
        except json.JSONDecodeError:
            pass
    return {"total_images": 0, "generated_at": None, "images": []}

def download_url(url: str, dest_path: Path) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": "stock-photo-bot/gpt-image-1"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    dest_path.write_bytes(data)
    return len(data) // 1024

def save_b64(b64_data: str, dest_path: Path) -> int:
    data = base64.b64decode(b64_data)
    dest_path.write_bytes(data)
    return len(data) // 1024

def generate_one(task: dict, client) -> dict:
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
            item = response.data[0]
            if getattr(item, "b64_json", None):
                size_kb = save_b64(item.b64_json, dest_path)
                revised = prompt
            elif getattr(item, "url", None):
                size_kb = download_url(item.url, dest_path)
                revised = getattr(item, "revised_prompt", None) or prompt
            else:
                tprint(f"  [err]   {filename}: no image data")
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
                    "prompt":          revised,
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
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    API_DIR.mkdir(parents=True, exist_ok=True)

    index    = load_index()
    existing = {img["filename"] for img in index["images"]}

    # Build pending task list preserving catalogue order
    tasks = []
    for category, items in CATALOGUE.items():
        for keyword, prompt in items:
            filename = f"{category}_{slugify(keyword)}_1.png"
            if filename not in existing:
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

    total_pending = len(tasks)
    if total_pending > MAX_NEW_PER_RUN:
        print(f"Limiting to {MAX_NEW_PER_RUN} images this run "
              f"({total_pending} pending — rest generate in future runs)")
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
    print(f"  Generated : {len(new_entries)}")
    print(f"  Failed    : {len(failed)}")
    print(f"  Total     : {index['total_images']}")
    print(f"  Pending   : {total_pending - len(new_entries)} (in future runs)")


if __name__ == "__main__":
    main()
