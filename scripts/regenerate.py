#!/usr/bin/env python3
"""
regenerate.py — Replace any gallery image with a fresh gpt-image-1 version.

HOW TO USE:
  In GitHub Actions → AI Stock Photo Generator → Run workflow,
  paste one or more filenames (space-separated) into the
  "Filenames to regenerate" field and click Run.

  Example:
    business_entrepreneur_desk_1.png technology_smartphone_flat_lay_1.png

  That's it. Any image visible in the gallery can be replaced this way.

HOW IT WORKS (no more catalogue matching):
  1. Looks up each filename in api/images.json to get its stored prompt.
  2. Removes the entry from the index and deletes the file from disk.
  3. Re-generates using the stored prompt via gpt-image-1 (if
     OPENAI_API_KEY is set) or Pollinations (free fallback).
  4. Saves the new image and updates the index.

  Because this uses the index — not the catalogue — it works for
  ANY image in the gallery regardless of how it was originally named
  or which script generated it. No more "not in catalogue" errors.

  The stored prompt is reused by default. To use a completely
  different prompt, edit the relevant entry in generate_dalle.py's
  CATALOGUE and run the weekly workflow instead (which will pick up
  the new keyword as a missing image and generate it fresh).
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


def load_index() -> dict:
    if INDEX_PATH.exists():
        try:
            return json.loads(INDEX_PATH.read_text())
        except json.JSONDecodeError:
            pass
    return {"total_images": 0, "generated_at": None, "images": []}


def save_index(index: dict) -> None:
    index["total_images"] = len(index["images"])
    index["generated_at"] = datetime.now(timezone.utc).isoformat()
    INDEX_PATH.write_text(json.dumps(index, indent=2))


# ── gpt-image-1 generation ────────────────────────────────────────────────────
def generate_with_openai(prompt: str, dest_path: Path) -> tuple[int, int, int] | None:
    """Generate via gpt-image-1. Returns (size_kb, width, height) or None."""
    try:
        import base64
        from openai import OpenAI

        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        response = client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size="1536x1024",
            quality="high",
            n=1,
        )
        item = response.data[0]
        if getattr(item, "b64_json", None):
            data = base64.b64decode(item.b64_json)
        elif getattr(item, "url", None):
            req = urllib.request.Request(
                item.url, headers={"User-Agent": "stock-photo-bot/regen"}
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
        else:
            print("  [err] no image data in response")
            return None

        dest_path.write_bytes(data)
        return len(data) // 1024, 1536, 1024

    except Exception as exc:
        print(f"  [err] gpt-image-1: {exc}")
        return None


# ── Pollinations fallback ─────────────────────────────────────────────────────
def generate_with_pollinations(prompt: str, dest_path: Path, seed: int = 9999) -> tuple[int, int, int] | None:
    """Free fallback via Pollinations FLUX. Returns (size_kb, width, height) or None."""
    negative = urllib.parse.quote(
        "deformed fingers, extra fingers, bad anatomy, blurry, watermark", safe=""
    )
    base = (
        "https://image.pollinations.ai/prompt/{p}"
        "?width=1344&height=896&seed={s}&model=flux"
        "&nologo=true&enhance=true&nofeed=true&negative={n}"
    )
    url = base.format(p=urllib.parse.quote(prompt, safe=""), s=seed, n=negative)

    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "stock-photo-bot/regen"})
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = resp.read()
            if len(data) < 10_000:
                print(f"  [small] attempt {attempt+1} ({len(data)} B)")
                time.sleep(8)
                continue
            dest_path.write_bytes(data)
            return len(data) // 1024, 1344, 896
        except Exception as exc:
            print(f"  [err] pollinations attempt {attempt+1}: {exc}")
            time.sleep(8)

    return None


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    targets    = list(dict.fromkeys(sys.argv[1:]))  # deduplicate, preserve order
    use_openai = bool(os.environ.get("OPENAI_API_KEY"))
    provider   = "gpt-image-1" if use_openai else "Pollinations"

    index    = load_index()
    index_by_filename = {img["filename"]: img for img in index["images"]}

    # Validate — everything must exist in the index
    not_found = [f for f in targets if f not in index_by_filename]
    for f in not_found:
        print(f"[warn] '{f}' not found in api/images.json — skipping")
    targets = [f for f in targets if f in index_by_filename]

    if not targets:
        print("Nothing to regenerate.")
        sys.exit(0)

    print(f"Provider  : {provider}")
    print(f"Targets   : {len(targets)} image(s)\n")

    # Step 1: remove from index and disk
    print(f"Removing {len(targets)} image(s) from index and disk...")
    index["images"] = [
        img for img in index["images"]
        if img["filename"] not in targets
    ]
    for filename in targets:
        path = IMAGES_DIR / filename
        if path.exists():
            path.unlink()
            print(f"  Deleted  {filename}")
        else:
            print(f"  [skip]   {filename} not on disk")

    save_index(index)
    print(f"  Index now: {index['total_images']} images\n")

    # Step 2: regenerate each
    new_entries = []
    for i, filename in enumerate(targets):
        original = index_by_filename[filename]
        prompt   = original.get("prompt", "")
        category = original.get("source_category", "")
        keyword  = original.get("source_keyword", "")
        dest     = IMAGES_DIR / filename

        print(f"[{i+1}/{len(targets)}] {filename}")
        print(f"  Prompt   : {prompt[:80]}{'...' if len(prompt) > 80 else ''}")

        if use_openai:
            result = generate_with_openai(prompt, dest)
        else:
            result = generate_with_pollinations(prompt, dest, seed=9000 + i)

        if result is None:
            print(f"  [fail]   {filename} — skipped")
            continue

        size_kb, w, h = result
        print(f"  [ok]     {filename}  {size_kb} KB  ({w}×{h})")

        new_entries.append({
            "filename":        filename,
            "source_keyword":  keyword,
            "source_category": category,
            "size_kb":         size_kb,
            "width":           w,
            "height":          h,
            "prompt":          prompt,
            "model":           "gpt-image-1" if use_openai else "flux",
        })

        if i < len(targets) - 1:
            time.sleep(3)

    # Step 3: write updated index
    index["images"].extend(new_entries)
    save_index(index)

    print(f"\nDone — {len(new_entries)}/{len(targets)} regenerated")
    print(f"Index total: {index['total_images']}")


if __name__ == "__main__":
    main()
