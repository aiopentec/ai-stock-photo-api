#!/usr/bin/env python3
"""Generate AI images using Hugging Face"""
import argparse, json, os, random, sys, time, requests
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

CONFIG = {
    'api_url': 'https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0',
    'max_retries': 3,
    'retry_delay': 5,
    'default_size': (1024, 1024),
    'steps': 30,
    'guidance': 7.5
}

def generate_image(prompt: str, token: str, seed: int = None) -> Dict:
    seed = seed or random.randint(0, 2147483647)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "inputs": prompt,
        "parameters": {
            "negative_prompt": "blurry, low quality, distorted",
            "num_inference_steps": CONFIG['steps'],
            "guidance_scale": CONFIG['guidance'],
            "seed": seed,
            "width": CONFIG['default_size'][0],
            "height": CONFIG['default_size'][1]
        }
    }
    
    for attempt in range(CONFIG['max_retries']):
        try:
            print(f"  Generating (attempt {attempt+1}/{CONFIG['max_retries']})...")
            resp = requests.post(CONFIG['api_url'], headers=headers, json=payload, timeout=180)
            
            if resp.status_code == 200:
                return {'success': True, 'image_data': resp.content, 'prompt': prompt, 
                        'seed': seed, 'size': len(resp.content), 'time': time.time()}
            elif resp.status_code == 503:
                wait = resp.json().get('estimated_time', CONFIG['retry_delay'])
                print(f"  Model loading, waiting {wait}s...")
                time.sleep(wait)
            elif resp.status_code == 429:
                print(f"  Rate limited, waiting...")
                time.sleep(CONFIG['retry_delay'] * 2)
            else:
                print(f"  Error {resp.status_code}")
                if attempt < CONFIG['max_retries'] - 1:
                    time.sleep(CONFIG['retry_delay'])
        except Exception as e:
            print(f"  Exception: {e}")
            time.sleep(CONFIG['retry_delay'])
    
    return {'success': False, 'error': 'Failed after retries'}

def save_image(result: Dict, output_dir: Path) -> Dict:
    if not result.get('success'): return result
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{ts}_{result['seed']}.png"
    filepath = output_dir / filename
    with open(filepath, 'wb') as f:
        f.write(result['image_data'])
    result['filename'] = filename
    result['filepath'] = str(filepath)
    print(f"  Saved: {filename} ({result['size']/1024:.1f}KB)")
    return result

def create_prompt(keyword: str, category: str) -> str:
    return f"Professional stock photo of {keyword}, high quality, 8k resolution, commercial photography, sharp focus, Unsplash-style aesthetic"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--keywords-file', '-k', default='data/trending_keywords.json')
    parser.add_argument('--count', '-c', type=int, default=20)
    parser.add_argument('--output-dir', '-o', default='images')
    parser.add_argument('--token', '-t', default=None)
    args = parser.parse_args()
    
    token = args.token or os.environ.get('HF_TOKEN')
    if not token:
        print("❌ HF_TOKEN required!")
        return 1
    
    with open(args.keywords_file) as f:
        data = json.load(f)
    keywords = data.get('keywords', [])
    
    print(f"\nGenerating {args.count} images from {len(keywords)} keywords...\n")
    
    results = []
    for i, kw in enumerate(keywords[:args.count]):
        print(f"[{i+1}/{args.count}] {kw['keyword']} ({kw['category']})")
        prompt = create_prompt(kw['keyword'], kw['category'])
        result = generate_image(prompt, token)
        result = save_image(result, Path(args.output_dir))
        result.update({'keyword': kw['keyword'], 'category': kw['category']})
        results.append(result)
        time.sleep(2)
    
    # Save metadata
    meta = {'generated_at': datetime.now().isoformat(), 'results': results}
    Path('data/generated').mkdir(exist_ok=True)
    with open(f'data/generated/batch_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json', 'w') as f:
        json.dump(meta, f, indent=2, default=str)
    
    success = sum(1 for r in results if r.get('success'))
    print(f"\n✅ Done! Generated {success}/{args.count} images")
    return 0

if __name__ == '__main__': sys.exit(main())
