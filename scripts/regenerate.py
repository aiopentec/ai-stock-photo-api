#!/usr/bin/env python3
"""
regenerate.py — Replace any gallery image with a fresh gpt-image-1 version.

Usage (GitHub Actions -> Run workflow -> regenerate field):
  business_entrepreneur_desk_1.webp technology_smartphone_flat_lay_1.webp

Looks up stored prompt from api/images.json. No catalogue matching needed.
Saves result as WebP and creates a thumbnail automatically.
"""

import base64, json, os, sys, time, urllib.parse, urllib.request
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT  = Path(__file__).resolve().parent.parent
IMAGES_DIR = REPO_ROOT / "images"
THUMBS_DIR = IMAGES_DIR / "thumbs"
INDEX_PATH = REPO_ROOT / "api" / "images.json"
THUMB_W, THUMB_H = 480, 320

def load_index():
    if INDEX_PATH.exists():
        try: return json.loads(INDEX_PATH.read_text())
        except: pass
    return {"total_images": 0, "generated_at": None, "images": []}

def save_index(index):
    index["total_images"] = len(index["images"])
    index["generated_at"] = datetime.now(timezone.utc).isoformat()
    INDEX_PATH.write_text(json.dumps(index, indent=2))

def _save_webp(data, dest_path):
    try:
        from PIL import Image; import io
        Image.open(io.BytesIO(data)).convert("RGB").save(
            dest_path, "WEBP", quality=85, method=4)
    except ImportError:
        dest_path.write_bytes(data)

def _make_thumb(source_path, stem):
    try:
        from PIL import Image, ImageOps
        THUMBS_DIR.mkdir(parents=True, exist_ok=True)
        tp = THUMBS_DIR / (stem + ".webp")
        with Image.open(source_path) as img:
            ImageOps.fit(img.convert("RGB"),
                         (THUMB_W, THUMB_H), Image.LANCZOS).save(tp, "WEBP", quality=80, method=4)
        return "thumbs/" + tp.name
    except Exception as exc:
        print(f"  [thumb err] {exc}"); return None

def generate_openai(prompt, dest_path):
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        resp = client.images.generate(
            model="gpt-image-1", prompt=prompt,
            size="1536x1024", quality="high", n=1)
        item = resp.data[0]
        if getattr(item, "b64_json", None):
            data = base64.b64decode(item.b64_json)
        elif getattr(item, "url", None):
            req = urllib.request.Request(item.url, headers={"User-Agent": "stock-photo-bot"})
            with urllib.request.urlopen(req, timeout=60) as r: data = r.read()
        else: return None
        _save_webp(data, dest_path)
        return dest_path.stat().st_size // 1024, 1536, 1024
    except Exception as exc:
        print(f"  [err] {exc}"); return None

def generate_pollinations(prompt, dest_path, seed=9999):
    neg = urllib.parse.quote("deformed fingers,bad anatomy,blurry,watermark", safe="")
    url = (f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt,safe='')}"
           f"?width=1344&height=896&seed={seed}&model=flux&nologo=true&enhance=true"
           f"&nofeed=true&negative={neg}")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "stock-photo-bot"})
            with urllib.request.urlopen(req, timeout=90) as r: data = r.read()
            if len(data) < 10_000: time.sleep(8); continue
            _save_webp(data, dest_path)
            return dest_path.stat().st_size // 1024, 1344, 896
        except Exception as exc:
            print(f"  [err] attempt {attempt+1}: {exc}"); time.sleep(8)
    return None

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/regenerate.py <filename> [...]"); sys.exit(1)

    targets    = list(dict.fromkeys(sys.argv[1:]))
    use_openai = bool(os.environ.get("OPENAI_API_KEY"))
    provider   = "gpt-image-1" if use_openai else "Pollinations"

    index    = load_index()
    idx_map  = {img["filename"]: img for img in index["images"]}

    not_found = [f for f in targets if f not in idx_map]
    for f in not_found: print(f"[warn] '{f}' not in index — skipping")
    targets = [f for f in targets if f in idx_map]
    if not targets: print("Nothing to regenerate."); sys.exit(0)

    print(f"Provider : {provider}\nTargets  : {len(targets)}\n")

    # Remove from index and disk
    index["images"] = [img for img in index["images"] if img["filename"] not in targets]
    for fn in targets:
        for path in [IMAGES_DIR/fn, THUMBS_DIR/(fn[:-5]+".webp" if fn.endswith(".webp") else fn[:-4]+".webp")]:
            if path.exists(): path.unlink(); print(f"  Deleted {path.name}")
    save_index(index)
    print(f"  Index now: {index['total_images']} images\n")

    new_entries = []
    for i, filename in enumerate(targets):
        original = idx_map[filename]
        prompt   = original.get("prompt", "")
        dest_fn  = filename if filename.endswith(".webp") else filename[:-4]+".webp"
        dest     = IMAGES_DIR / dest_fn
        stem     = dest_fn[:-5]

        print(f"[{i+1}/{len(targets)}] {filename}")
        print(f"  Prompt : {prompt[:80]}{'...' if len(prompt)>80 else ''}")

        result = generate_openai(prompt, dest) if use_openai else \
                 generate_pollinations(prompt, dest, seed=9000+i)
        if result is None: print(f"  [fail] {filename}"); continue

        size_kb, w, h = result
        thumb = _make_thumb(dest, stem)
        print(f"  [ok]  {dest_fn}  {size_kb}KB")

        new_entries.append({
            "filename": dest_fn, "source_keyword": original.get("source_keyword",""),
            "source_category": original.get("source_category",""),
            "size_kb": size_kb, "width": w, "height": h,
            "prompt": prompt, "model": "gpt-image-1" if use_openai else "flux",
            "thumbnail": thumb,
        })
        if i < len(targets)-1: time.sleep(3)

    index["images"].extend(new_entries)
    save_index(index)
    print(f"\nDone — {len(new_entries)}/{len(targets)} regenerated | Total: {index['total_images']}")

if __name__ == "__main__":
    main()
