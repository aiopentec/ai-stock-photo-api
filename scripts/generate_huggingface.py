#!/usr/bin/env python3
"""
generate_huggingface.py — Free image generation via HuggingFace Inference API

The best zero-cost upgrade available over Pollinations. Uses Stable Diffusion
3.5 Medium by default — meaningfully better than FLUX.1-schnell for hands,
people, and prompt adherence, at zero cost with a free HF account.

Quality comparison (hands/people):
  FLUX.1-schnell (Pollinations)  : ~30-40% acceptable
  SDXL (HF free, fallback)       : ~45-55% acceptable
  SD 3.5 Medium (HF free)        : ~55-65% acceptable
  DALL-E 3                       : ~90% acceptable

Requires:
  pip install requests
  export HF_API_TOKEN=hf_...   (free at huggingface.co/settings/tokens)

Model options (set MODEL constant below):
  stabilityai/stable-diffusion-3-5-medium   ← default, best free quality
  stabilityai/stable-diffusion-xl-base-1.0  ← fallback, always available
  black-forest-labs/FLUX.1-schnell          ← same as Pollinations

Notes:
  - Free HF accounts get limited serverless inference per month (~1000 units).
    35 images uses roughly 35-70 units depending on steps. Well within limits.
  - Large models (SD 3.5 Large, FLUX.1-dev) may require HF Pro ($9/month)
    or gated model access. Stick with Medium for reliable free access.
  - Models cold-start on first request (30-120s wait). The script handles this.
  - HF Inference API supports negative prompts natively — a key advantage
    over Pollinations which implements them inconsistently.
"""

import json
import os
import re
import sys
import time
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT  = Path(__file__).resolve().parent.parent
IMAGES_DIR = REPO_ROOT / "images"
API_DIR    = REPO_ROOT / "api"
INDEX_PATH = API_DIR / "images.json"

# ── Model selection ──────────────────────────────────────────────────────────
# SD 3.5 Medium: best free quality, ~2.5B params, works on free HF tier
# SDXL: reliable fallback if 3.5 Medium quota is exhausted
MODEL = "stabilityai/stable-diffusion-3-5-medium"
# MODEL = "stabilityai/stable-diffusion-xl-base-1.0"  # reliable fallback

HF_API_BASE = "https://api-inference.huggingface.co/models"
IMAGE_WIDTH  = 1024
IMAGE_HEIGHT = 680
MAX_WORKERS  = 3      # conservative — HF free tier rate-limits aggressively
RETRY_PAUSE  = 12.0

# SD 3.5 Medium generation parameters
# (ignored by SDXL — it uses its own defaults)
GENERATION_PARAMS = {
    "num_inference_steps": 28,
    "guidance_scale": 4.5,        # SD3 works best at 4-5, not 7-9
    "width": IMAGE_WIDTH,
    "height": IMAGE_HEIGHT,
}

NEGATIVE_PROMPT = (
    "deformed fingers, extra fingers, fused fingers, missing fingers, "
    "malformed hands, bad anatomy, disfigured, poorly drawn, "
    "blurry, out of focus, low quality, grainy, noisy, "
    "watermark, text, logo, signature, border, frame, "
    "cartoon, illustration, painting, drawing, sketch"
)

QUALITY_SUFFIX = (
    ", professional stock photograph, sharp focus, "
    "high resolution, natural lighting, no text, no watermark"
)

# ── Catalogue ────────────────────────────────────────────────────────────────
# Natural language sentences — SD 3.5 follows prose better than pure tags.
CATALOGUE = {
    "business": [
        ("remote work",
         "Overhead flat lay of a modern home office desk with a slim laptop, ceramic coffee mug, open notebook and pen, bright natural window light. Minimal and professional."),
        ("team collaboration",
         "Top-down flat lay of architectural blueprints spread across a dark oak conference table with technical pens, a brass compass and coffee cups. No people. Professional planning atmosphere."),
        ("startup office",
         "Wide-angle view of a bright modern open-plan startup office with standing desks, hanging plants and floor-to-ceiling windows. Empty of people, golden late afternoon light."),
        ("business growth",
         "Close-up of a hand drawing a clean upward-trending arrow on a glass whiteboard with a blue marker. One hand only, minimal, white background, soft natural light."),
        ("entrepreneur desk",
         "Overhead flat-lay of a minimal workspace: a thin silver laptop, reading glasses, small succulent plant, leather notebook on a pale oak desk. Warm morning light from left."),
    ],
    "nature": [
        ("forest path",
         "A sunlit forest path winding through tall trees with golden light filtering through the canopy and dappled shadows on the ground. Peaceful, no people, soft morning mist."),
        ("mountain lake",
         "A wide-angle view of a perfectly still alpine lake mirroring snow-capped mountains and blue sky at golden hour. No people, breathtaking natural reflection."),
        ("wildflower meadow",
         "A vast wildflower meadow in full summer bloom with red poppies, yellow buttercups and white daisies under a clear blue sky. No people, warm and vibrant."),
        ("ocean sunrise",
         "Gentle waves washing over smooth dark sand on an empty beach at sunrise, soft pastel pink and orange sky reflected in the wet sand. No people, peaceful."),
        ("urban garden",
         "A thriving urban rooftop garden with raised wooden beds growing tomatoes, herbs and flowers, city skyline in the warm background light. No people."),
    ],
    "technology": [
        ("circuit board macro",
         "Extreme close-up macro of a vivid green circuit board with gold through-hole components, copper traces and surface-mount chips against a dark background. Sharp, detailed, technical."),
        ("server room",
         "A corridor of a modern data center with rows of blue LED-lit server racks receding into the distance. No people, dramatic atmospheric lighting."),
        ("code on screen",
         "A large monitor displaying colourful syntax-highlighted code in a dark theme editor. Soft blue glow on the desk surface. No people."),
        ("smartphone flatlay",
         "Overhead flat-lay of a modern smartphone placed face-down beside a ceramic espresso cup and small succulent on clean white marble. Minimal, modern."),
        ("smart home devices",
         "Overhead flat-lay of smart home devices neatly arranged on a white surface: cylindrical speaker, smart display, smart bulb, and braided cables. Soft even shadows."),
    ],
    "people": [
        # SD 3.5 handles people better than FLUX but still benefits from
        # controlled compositions. These prompts keep the subject clear
        # and lighting simple to maximise quality.
        ("window silhouette",
         "Silhouette of a person standing at a large rain-streaked window looking at a misty city below. Person faces away from camera, warm room light creates a glow around their outline. Moody and atmospheric."),
        ("forest walker",
         "A person walking away from the camera along a misty autumn forest trail. Seen from behind, wearing a cosy knit jacket with a backpack. Golden fallen leaves, soft natural light."),
        ("park friends",
         "Two friends sitting on a wooden park bench seen from behind, looking out at a golden autumn park scene. Relaxed posture, warm late afternoon sunlight through trees."),
        ("cafe worker",
         "Over-the-shoulder view of a person working on a laptop in a warm independent cafe. A latte beside them on the table, warm bokeh background. Seen from behind, face not visible."),
        ("chef hands",
         "Close-up of a professional chef's hands carefully slicing a ripe red tomato on a wooden chopping board. Fresh basil leaves nearby. Sharp focus on hands and knife, warm natural kitchen light."),
    ],
    "abstract": [
        ("colour smoke",
         "Swirling purple, burnt orange and teal coloured smoke against a pure black background. Elegant flowing curves and translucent layers. Fine-art photography."),
        ("geometric minimal",
         "Clean studio arrangement of matte pastel geometric shapes — circles, triangles and rectangles in blush pink, sage green and warm beige — on a white surface with soft precise shadows."),
        ("water macro",
         "Extreme macro of water droplets on a glass surface, each droplet refracting coloured light into jewel tones of teal, amber and magenta against a deep black background."),
        ("bokeh golden",
         "Soft golden bokeh circles of varying sizes against a deep dark background. Shot on a fast prime lens for perfectly smooth circular bokeh. Warm and festive."),
        ("paper layers",
         "Neatly layered and torn sheets of white, cream and pale grey paper textures arranged in an overhead flat-lay with subtle precise soft shadows. Minimal and clean."),
    ],
    "food": [
        ("avocado toast",
         "Overhead flat-lay food photograph of sourdough avocado toast with a perfectly poached egg, microgreens, chilli flakes and sea salt on a white ceramic plate. Bright natural side light."),
        ("latte art",
         "Close-up of a flat white coffee with a tulip latte art pattern in a wide ceramic cup on a wooden cafe table. Warm natural ambient light."),
        ("grain bowl",
         "Overhead flat-lay of a nourishing grain bowl with roasted sweet potato, chickpeas, avocado, microgreens and tahini on a light grey linen surface. Natural side light."),
        ("farmers market",
         "Overhead flat-lay of fresh seasonal vegetables — heirloom tomatoes, rainbow carrots, courgettes and fresh herbs — arranged on a worn wooden market table. Vibrant natural colours."),
        ("sourdough loaf",
         "Close-up of a freshly baked artisan sourdough loaf with a beautifully scored crust on a dark wooden board in a warm kitchen. Slight steam rising from the crust."),
    ],
    "travel": [
        ("cobblestone village",
         "A charming narrow cobblestone street in a sun-drenched southern European village, lined with terracotta flower pots and old stone buildings. Glowing golden hour light. No people."),
        ("airport terminal",
         "Wide-angle interior of a grand modern airport terminal with soaring floor-to-ceiling windows flooding the space with natural light. Clean architecture, no people."),
        ("desert highway",
         "A straight two-lane highway cutting through a vast red desert landscape toward distant purple mountains. Dramatic sunset sky with streaked clouds."),
        ("tropical water",
         "Aerial view of an overwater bungalow in impossibly clear turquoise water with the sandy ocean floor visible below the surface. No people, tropical paradise."),
        ("city reflection",
         "Long-exposure view of a vibrant city skyline perfectly reflected in a still river at blue hour. Building lights creating shimmering trails in the water. No people."),
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

def call_hf_api(token, prompt, retries=3):
    """
    POST to HF Inference API. Returns raw image bytes or None.
    Handles cold-start 503s (model loading) and rate-limit 429s automatically.
    """
    url     = f"{HF_API_BASE}/{MODEL}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "image/png",
    }
    payload = {
        "inputs": prompt + QUALITY_SUFFIX,
        "parameters": {
            **GENERATION_PARAMS,
            "negative_prompt": NEGATIVE_PROMPT,
        },
    }

    for attempt in range(retries):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=120)

            if resp.status_code == 200:
                data = resp.content
                if len(data) < 5_000:
                    tprint(f"    [warn] response too small ({len(data)} B)")
                    time.sleep(RETRY_PAUSE)
                    continue
                return data

            if resp.status_code == 503:
                # Model is cold-loading on shared HF infra
                try:
                    wait = resp.json().get("estimated_time", 30)
                except Exception:
                    wait = 30
                wait = min(float(wait), 60)
                tprint(f"    [cold] model loading, waiting {wait:.0f}s...")
                time.sleep(wait)
                continue

            if resp.status_code == 429:
                tprint(f"    [rate] rate limited, waiting 60s...")
                time.sleep(60)
                continue

            tprint(f"    [http] {resp.status_code}: {resp.text[:120]}")
            time.sleep(RETRY_PAUSE)

        except requests.Timeout:
            tprint(f"    [timeout] attempt {attempt+1}")
            time.sleep(RETRY_PAUSE)
        except Exception as exc:
            tprint(f"    [err] attempt {attempt+1}: {exc}")
            time.sleep(RETRY_PAUSE)

    return None

def generate_one(task, token):
    category  = task["category"]
    keyword   = task["keyword"]
    filename  = task["filename"]
    dest_path = task["dest_path"]

    tprint(f"  [start] {category}/{keyword}")

    data = call_hf_api(token, task["prompt"])

    if data is None:
        tprint(f"  [fail]  {filename}")
        return {"passed": False, "filename": filename}

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
            "model":           MODEL,
        },
    }

def main():
    token = os.environ.get("HF_API_TOKEN")
    if not token:
        print("ERROR: HF_API_TOKEN not set.")
        print("Get a free token at https://huggingface.co/settings/tokens")
        sys.exit(1)

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

    print(f"Model     : {MODEL}")
    print(f"Images    : {len(tasks)} to generate")
    print(f"Workers   : {MAX_WORKERS}")
    print(f"Est. time : ~{len(tasks) * 45 // 60 // MAX_WORKERS + 1}–"
          f"{len(tasks) * 70 // 60 // MAX_WORKERS + 2} min\n")

    t0          = time.time()
    new_entries = []
    failed      = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(generate_one, task, token): task for task in tasks}
        for future in as_completed(futures):
            result = future.result()
            if result["passed"]:
                new_entries.append(result["entry"])
            else:
                failed.append(result["filename"])

    new_entries.sort(key=lambda e: (e["source_category"], e["source_keyword"]))
    index["images"].extend(new_entries)
    index["total_images"] = len(index["images"])
    index["generated_at"] = datetime.now(timezone.utc).isoformat()
    INDEX_PATH.write_text(json.dumps(index, indent=2))

    elapsed = int((time.time() - t0) / 60)
    print(f"\nFinished in {elapsed}m")
    print(f"  Generated : {len(new_entries)}")
    print(f"  Failed    : {len(failed)}")
    print(f"  Total     : {index['total_images']}")
    if failed:
        print("  Failed files:")
        for f in failed:
            print(f"    python scripts/regenerate.py {f}")

if __name__ == "__main__":
    main()
