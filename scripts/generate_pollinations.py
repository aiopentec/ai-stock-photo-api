#!/usr/bin/env python3
"""
generate_pollinations.py  (v2 — improved quality)

Key changes from v1:
  - MODEL switched from flux-realism -> flux
    flux-realism amplifies anatomy issues on people; flux handles mixed
    scenes more reliably and produces sharper overall results.
  - enhance=true  lets Pollinations' prompt-improvement layer run.
    Previous enhance=false gave us exactly what we wrote, which was not
    enough for consistent stock-photo quality.
  - nofeed=true  keeps generated images out of the public Pollinations feed.
  - QUALITY_SUFFIX appended to every prompt: sharp focus, high resolution,
    no blur, no distortion. Explicit beats implicit every time.
  - "shallow depth of field" removed from ALL prompts — it directly causes
    the blur complaints and is inappropriate for stock photo use anyway.
  - People category COMPLETELY rewritten to use close-ups of hands, feet,
    and silhouettes. Full-face/full-body prompts hit the worst failure modes
    of every diffusion model. Avoiding faces sidesteps this entirely while
    producing images that are actually more useful as stock photos.
  - Image size bumped to 1344x896 (still 3:2, slightly larger for quality).
"""

import json
import re
import time
import urllib.parse
import urllib.request
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

IMAGE_WIDTH  = 1344
IMAGE_HEIGHT = 896
MODEL        = "flux"
PAUSE_SECS   = 3.0

# Appended to every prompt. Spelling these out explicitly matters.
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
        # Rewritten entirely: close-ups of hands/feet/silhouettes only.
        # This sidesteps diffusion model anatomy failures completely
        # while producing more versatile, high-demand stock images.
        ("reading hands",
         "close-up of relaxed hands holding an open paperback book, sunlight falling across the pages, warm tones, wooden armchair arm visible"),
        ("creative hands",
         "close-up of hands sketching in a spiral notebook with a fine pen, wooden desk, natural window light, coffee cup in soft background blur"),
        ("connection hands",
         "overhead close-up of two pairs of hands gently clasped together on a light oak table, warm afternoon sunlight"),
        ("typing hands",
         "close-up of hands typing on a slim laptop keyboard, clean white desk, soft indoor light, minimal"),
        ("chef hands",
         "close-up of hands slicing a ripe red tomato on a wooden chopping board, professional kitchen counter, natural light"),
    ],
    "abstract": [
        ("colour smoke",
         "swirling purple, orange and teal coloured smoke against a pure black background, flowing, artistic, studio"),
        ("geometric minimal",
         "arrangement of clean pastel geometric shapes — circles, triangles, rectangles — on white background, studio lighting"),
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
         "overhead flat lay of a colourful grain bowl with roasted vegetables, chickpeas and tahini on a light grey surface, natural light"),
        ("farmers market",
         "overhead flat lay of fresh seasonal vegetables — carrots, tomatoes, courgettes — on a wooden market table, vibrant colours"),
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


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def build_url(prompt: str, seed: int) -> str:
    full_prompt = prompt + QUALITY_SUFFIX
    encoded = urllib.parse.quote(full_prompt, safe="")
    return POLLINATIONS_BASE.format(
        prompt=encoded,
        w=IMAGE_WIDTH,
        h=IMAGE_HEIGHT,
        seed=seed,
        model=MODEL,
    )


def fetch_image(url: str, dest_path: Path, retries: int = 3) -> int | None:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "stock-photo-bot/2.0"}
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = resp.read()

            if len(data) < 10_000:
                print(f"    [warn] attempt {attempt+1}: too small ({len(data)} bytes)")
                time.sleep(PAUSE_SECS * 2)
                continue

            dest_path.write_bytes(data)
            return len(data) // 1024

        except Exception as exc:
            print(f"    [warn] attempt {attempt+1}: {exc}")
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
    existing = {img["filename"] for img in index["images"]}
    new_entries = []
    seed = 2000  # new seed range so v2 prompts don't collide with v1 files

    for category, items in CATALOGUE.items():
        print(f"\n── {category.upper()} ──")

        for keyword, prompt in items:
            filename = f"{category}_{slugify(keyword)}_1.png"

            if filename in existing:
                print(f"  [skip] {filename}")
                seed += 1
                continue

            print(f"  [gen]  {keyword}  (seed={seed})")
            size_kb = fetch_image(build_url(prompt, seed), IMAGES_DIR / filename)

            if size_kb is None:
                print(f"  [fail] {filename}")
            else:
                new_entries.append({
                    "filename":        filename,
                    "source_keyword":  keyword,
                    "source_category": category,
                    "size_kb":         size_kb,
                    "width":           IMAGE_WIDTH,
                    "height":          IMAGE_HEIGHT,
                    "prompt":          prompt + QUALITY_SUFFIX,
                    "seed":            seed,
                })
                print(f"  [ok]   {size_kb} KB")

            seed += 1
            time.sleep(PAUSE_SECS)

    index["images"].extend(new_entries)
    index["total_images"] = len(index["images"])
    index["generated_at"] = datetime.now(timezone.utc).isoformat()
    INDEX_PATH.write_text(json.dumps(index, indent=2))

    print(f"\nDone: {len(new_entries)} new  |  {index['total_images']} total")


if __name__ == "__main__":
    main()
