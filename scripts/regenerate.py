#!/usr/bin/env python3
"""
regenerate.py — Remove specific images from index + disk, then re-generate.

Usage:
  python scripts/regenerate.py <filename> [<filename> ...]

Example — fix the old hands images:
  python scripts/regenerate.py \\
    people_reading_hands_1.png \\
    people_creative_hands_1.png \\
    people_connection_hands_1.png \\
    people_typing_hands_1.png \\
    business_team_collaboration_1.png

If OPENAI_API_KEY is set, uses DALL-E 3. Otherwise uses Pollinations.
"""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT  = Path(__file__).resolve().parent.parent
IMAGES_DIR = REPO_ROOT / "images"
INDEX_PATH = REPO_ROOT / "api" / "images.json"

REGEN_SEED = 9000

def slugify(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")

def load_index():
    if INDEX_PATH.exists():
        try: return json.loads(INDEX_PATH.read_text())
        except: pass
    return {"total_images": 0, "generated_at": None, "images": []}

def build_catalogue_map():
    """Import whichever catalogue is available."""
    scripts = Path(__file__).resolve().parent
    sys.path.insert(0, str(scripts))
    try:
        from generate_dalle import CATALOGUE
        print("Using DALL-E 3 catalogue for regeneration")
    except ImportError:
        from generate_pollinations import CATALOGUE
        print("Using Pollinations catalogue for regeneration")
    mapping = {}
    for category, items in CATALOGUE.items():
        for keyword, prompt in items:
            filename = f"{category}_{slugify(keyword)}_1.png"
            mapping[filename] = (category, keyword, prompt)
    return mapping

def fetch_pollinations(prompt, seed, dest_path):
    import urllib.parse as up
    NEGATIVE = up.quote("deformed fingers,extra fingers,bad anatomy,blurry,watermark", safe="")
    BASE = ("https://image.pollinations.ai/prompt/{p}"
            "?width=1344&height=896&seed={s}&model=flux"
            "&nologo=true&enhance=true&nofeed=true&negative={n}")
    url = BASE.format(p=up.quote(prompt, safe=""), s=seed, n=NEGATIVE)
    req = urllib.request.Request(url, headers={"User-Agent": "stock-photo-bot/regen"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = resp.read()
    if len(data) < 10_000:
        return None
    dest_path.write_bytes(data)
    return len(data) // 1024, 1344, 896

def fetch_dalle(prompt, dest_path):
    try:
        from openai import OpenAI
        import urllib.request as ur
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        response = client.images.generate(
            model="dall-e-3", prompt=prompt,
            size="1792x1024", quality="hd", n=1,
        )
        url = response.data[0].url
        req = ur.Request(url, headers={"User-Agent": "stock-photo-bot/regen"})
        with ur.urlopen(req, timeout=60) as resp:
            data = resp.read()
        dest_path.write_bytes(data)
        return len(data) // 1024, 1792, 1024
    except Exception as exc:
        print(f"  DALL-E 3 error: {exc}")
        return None

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    targets   = set(sys.argv[1:])
    catalogue = build_catalogue_map()
    index     = load_index()
    use_dalle = bool(os.environ.get("OPENAI_API_KEY"))

    unknown = targets - set(catalogue.keys())
    for f in unknown:
        print(f"[warn] '{f}' not in catalogue — skipping")
    targets -= unknown
    if not targets:
        print("Nothing to regenerate."); sys.exit(0)

    print(f"\nRemoving {len(targets)} images from index and disk...")
    before = len(index["images"])
    index["images"] = [img for img in index["images"] if img["filename"] not in targets]
    print(f"  Removed {before - len(index['images'])} index entries")

    for filename in targets:
        path = IMAGES_DIR / filename
        if path.exists():
            path.unlink()
            print(f"  Deleted {filename}")

    index["total_images"] = len(index["images"])
    INDEX_PATH.write_text(json.dumps(index, indent=2))

    print(f"\nRe-generating {len(targets)} images "
          f"({'DALL-E 3' if use_dalle else 'Pollinations'})...\n")

    new_entries = []
    seed = REGEN_SEED

    for filename in sorted(targets):
        category, keyword, prompt = catalogue[filename]
        seed += 1
        print(f"  [gen] {filename}")

        if use_dalle:
            result = fetch_dalle(prompt, IMAGES_DIR / filename)
        else:
            result = fetch_pollinations(prompt, seed, IMAGES_DIR / filename)

        if result is None:
            print(f"  [fail] {filename}")
            continue

        size_kb, w, h = result
        print(f"  [ok]  {filename}  {size_kb} KB")
        new_entries.append({
            "filename": filename, "source_keyword": keyword,
            "source_category": category, "size_kb": size_kb,
            "width": w, "height": h, "prompt": prompt,
            "seed": seed if not use_dalle else None,
        })
        time.sleep(3)

    index["images"].extend(new_entries)
    index["total_images"] = len(index["images"])
    index["generated_at"] = datetime.now(timezone.utc).isoformat()
    INDEX_PATH.write_text(json.dumps(index, indent=2))

    print(f"\nDone — {len(new_entries)}/{len(targets)} regenerated")
    print(f"Index total: {index['total_images']}")

if __name__ == "__main__":
    main()
