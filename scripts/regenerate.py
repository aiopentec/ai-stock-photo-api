#!/usr/bin/env python3
"""
regenerate.py — Remove specific images from the index and disk, then
re-generate them with new seeds using the current CATALOGUE prompts.

Usage:
  python scripts/regenerate.py <filename> [<filename> ...]

Examples:
  # Fix the malformed team collaboration image
  python scripts/regenerate.py business_team_collaboration_1.png

  # Fix all old people/hands images at once
  python scripts/regenerate.py \\
    people_reading_hands_1.png \\
    people_creative_hands_1.png \\
    people_connection_hands_1.png \\
    people_typing_hands_1.png

After running this script, re-run generate_pollinations.py to generate
fresh versions with the updated prompts and new seeds.
"""

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

# Import CATALOGUE and build_url from generate_pollinations
sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_pollinations import (
    CATALOGUE, QUALITY_SUFFIX, NEGATIVE_PROMPT,
    POLLINATIONS_BASE, IMAGE_WIDTH, IMAGE_HEIGHT, MODEL,
    slugify, tprint,
)

REPO_ROOT  = Path(__file__).resolve().parent.parent
IMAGES_DIR = REPO_ROOT / "images"
INDEX_PATH = REPO_ROOT / "api" / "images.json"

REGEN_SEED_OFFSET = 9000   # well away from v3 (2000s) and v4 (3000s) seeds


def load_index():
    if INDEX_PATH.exists():
        return json.loads(INDEX_PATH.read_text())
    return {"total_images": 0, "generated_at": None, "images": []}


def build_catalogue_map():
    """Filename → (category, keyword, prompt)"""
    mapping = {}
    for category, items in CATALOGUE.items():
        for keyword, prompt in items:
            filename = f"{category}_{slugify(keyword)}_1.png"
            mapping[filename] = (category, keyword, prompt)
    return mapping


def remove_from_index(index, filenames):
    original_count = len(index["images"])
    index["images"] = [
        img for img in index["images"]
        if img["filename"] not in filenames
    ]
    removed = original_count - len(index["images"])
    index["total_images"] = len(index["images"])
    return removed


def fetch_image(url, dest_path, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "stock-photo-bot/regen"}
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = resp.read()
            if len(data) < 10_000:
                tprint(f"  [small] attempt {attempt+1} ({len(data)} B)")
                time.sleep(8)
                continue
            dest_path.write_bytes(data)
            return len(data) // 1024
        except Exception as exc:
            tprint(f"  [err]   attempt {attempt+1}: {exc}")
            time.sleep(8)
    return None


def build_url(prompt, seed):
    full = prompt + QUALITY_SUFFIX
    encoded = urllib.parse.quote(full, safe="")
    return POLLINATIONS_BASE.format(
        prompt=encoded, w=IMAGE_WIDTH, h=IMAGE_HEIGHT,
        seed=seed, model=MODEL, negative=NEGATIVE_PROMPT,
    )


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    targets   = set(sys.argv[1:])
    catalogue = build_catalogue_map()
    index     = load_index()

    # Validate filenames
    unknown = targets - set(catalogue.keys())
    if unknown:
        for f in unknown:
            print(f"[warn] '{f}' not found in CATALOGUE — cannot regenerate")
        targets -= unknown

    if not targets:
        print("Nothing to regenerate.")
        sys.exit(0)

    print(f"Removing {len(targets)} image(s) from index and disk...\n")
    removed = remove_from_index(index, targets)
    print(f"  Removed {removed} index entries")

    for filename in targets:
        path = IMAGES_DIR / filename
        if path.exists():
            path.unlink()
            print(f"  Deleted {filename}")
        else:
            print(f"  [skip] {filename} not on disk")

    # Save updated index immediately so generate_pollinations.py sees the gaps
    INDEX_PATH.write_text(json.dumps(index, indent=2))
    print(f"\nIndex updated — {index['total_images']} images remaining")

    # Re-generate each removed image with a new seed
    print(f"\nRe-generating {len(targets)} image(s)...\n")
    new_entries = []
    seed = REGEN_SEED_OFFSET

    for filename in sorted(targets):
        category, keyword, prompt = catalogue[filename]
        seed += 1
        tprint(f"  [gen] {filename}  seed={seed}")
        url     = build_url(prompt, seed)
        dest    = IMAGES_DIR / filename
        size_kb = fetch_image(url, dest)

        if size_kb is None:
            tprint(f"  [fail] {filename} — try again or use a different seed")
        else:
            tprint(f"  [ok]  {filename}  {size_kb} KB")
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
        time.sleep(3)

    if new_entries:
        index["images"].extend(new_entries)
        index["total_images"] = len(index["images"])
        index["generated_at"] = datetime.now(timezone.utc).isoformat()
        INDEX_PATH.write_text(json.dumps(index, indent=2))
        print(f"\nDone — regenerated {len(new_entries)}/{len(targets)} images")
        print(f"Index total: {index['total_images']}")
    else:
        print("\nNo images successfully regenerated.")


if __name__ == "__main__":
    main()
