#!/usr/bin/env python3
"""
Generate AI stock photos using Pollinations.ai (Free, No API Key Required!)
"""

import argparse
import json
import os
import sys
import time
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any
import urllib.parse

# Pollinations.ai - FREE AI Image Generation (No API key needed!)
POLLINATIONS_API = "https://image.pollinations.ai/prompt"

def generate_image_url(prompt: str, width: int = 1024, height: int = 1024) -> str:
    """
    Generate image using Pollinations.ai free API.
    Returns URL to the generated image.
    """
    # Encode prompt for URL
    encoded_prompt = urllib.parse.quote(prompt)
    
    # Build URL with parameters
    url = f"{POLLINATIONS_API}/{encoded_prompt}?width={width}&height={height}&nologo=true&seed={int(time.time()) % 10000}"
    
    return url

def download_image(url: str, output_path: Path) -> Dict[str, Any]:
    """
    Download image from URL to local file.
    """
    try:
        print(f"  ⬇️ Downloading from API...")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (AI Stock Photo Bot)'
        }
        
        response = requests.get(url, headers=headers, timeout=120)
        
        if response.status_code == 200:
            # Ensure directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Save image
            with open(output_path, 'wb') as f:
                f.write(response.content)
            
            file_size = len(response.content)
            
            return {
                'success': True,
                'filepath': str(output_path),
                'filename': output_path.name,
                'size_bytes': file_size,
                'size_kb': round(file_size / 1024, 2),
                'url': url
            }
        else:
            return {
                'success': False,
                'error': f"HTTP {response.status_code}",
                'url': url
            }
            
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'url': url
        }

def create_optimized_prompt(keyword: str, category: str = "general") -> str:
    """Create professional stock photo prompt."""
    
    category_enhancements = {
        'business': "professional corporate photography, modern office, business people, soft lighting",
        'nature': "stunning landscape photography, golden hour, National Geographic quality, vibrant colors",
        'technology': "futuristic technology, clean minimal design, product photography, blue lighting",
        'food': "appetizing food photography, restaurant quality, warm ambient light, gourmet presentation",
        'people': "diverse group of people, lifestyle photography, authentic moment, natural expression",
        'abstract': "abstract geometric art, gradient colors, contemporary design, minimalist composition",
        'travel': "iconic travel destination, wanderlust photography, blue hour, architectural beauty",
        'education': "bright learning environment, student studying, knowledge concept, academic setting",
        'health': "fitness and wellness, active lifestyle, yoga meditation, healthy living"
    }
    
    enhancement = category_enhancements.get(category, "high quality professional photography")
    
    prompt = f"Professional stock photo of {keyword}, {enhancement}, 8k resolution, sharp focus, commercially usable, Unsplash style, award-winning photography"
    
    return prompt

def batch_generate_images(
    keywords: List[Dict[str, Any]], 
    output_dir: Path, 
    count: int = 5
) -> Dict[str, Any]:
    """Generate multiple images."""
    
    print(f"\n{'='*60}")
    print(f"🎨 GENERATING {count} STOCK PHOTOS")
    print(f"   Using: Pollinations.ai (FREE, No API Key)")
    print(f"{'='*60}\n")
    
    results = []
    successful = 0
    
    for i, kw_data in enumerate(keywords[:count]):
        keyword = kw_data['keyword']
        category = kw_data.get('category', 'general')
        
        print(f"\n[{i+1}/{min(count, len(keywords))}] 📷 {keyword}")
        print(f"   Category: {category}")
        
        # Create optimized prompt
        prompt = create_optimized_prompt(keyword, category)
        print(f"   Prompt: {prompt[:80]}...")
        
        # Generate URL
        img_url = generate_image_url(prompt)
        
        # Create filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_keyword = "".join(c if c.isalnum() else "_" for c in keyword[:20])
        filename = f"{timestamp}_{safe_keyword}.png"
        filepath = output_dir / filename
        
        # Download image
        result = download_image(img_url, filepath)
        
        if result['success']:
            successful += 1
            result.update({
                'keyword': keyword,
                'category': category,
                'prompt': prompt,
                'source_url': result.get('url', ''),
                'relative_path': str(filepath.relative_to(Path.cwd())),
                'license': 'CC0 1.0 Universal',
                'tags': [category, keyword.lower()]
            })
            results.append(result)
            
            print(f"   ✅ Success! ({result['size_kb']} KB)")
        else:
            print(f"   ❌ Failed: {result.get('error', 'Unknown')}")
            results.append({
                'success': False,
                'keyword': keyword,
                'error': result.get('error'),
                'url': result.get('url', '')
            })
        
        # Small delay between downloads
        if i < count - 1:
            time.sleep(1)
    
    # Summary
    print(f"\n{'='*60}")
    print(f"✅ GENERATION COMPLETE")
    print(f"   Successful: {successful}/{count}")
    print(f"   Total size: {sum(r.get('size_bytes', 0) for r in results if r.get('success')) / 1024:.1f} KB")
    print('='*60)
    
    return {
        'generated_at': datetime.now().isoformat(),
        'total_requested': count,
        'successful': successful,
        'failed': count - successful,
        'service_used': 'pollinations.ai',
        'results': results
    }

def main():
    parser = argparse.ArgumentParser(description='Generate AI stock photos (FREE)')
    parser.add_argument('--keywords-file', '-k', default='data/trending_keywords.json')
    parser.add_argument('--count', '-c', type=int, default=5)
    parser.add_argument('--output-dir', '-o', default='images')
    args = parser.parse_args()
    
    # Load keywords
    try:
        with open(args.keywords_file, 'r') as f:
            data = json.load(f)
        keywords = data.get('keywords', [])
    except:
        # Fallback keywords if file missing
        keywords = [
            {'keyword': 'modern office workspace', 'category': 'business'},
            {'keyword': 'mountain landscape sunset', 'category': 'nature'},
            {'keyword': 'artificial intelligence technology', 'category': 'technology'},
            {'keyword': 'diverse team collaboration', 'category': 'people'},
            {'keyword': 'abstract geometric pattern', 'category': 'abstract'}
        ]
    
    if not keywords:
        print("❌ No keywords found!")
        return 1
    
    print(f"📂 Loaded {len(keywords)} keywords")
    
    # Generate images
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    results = batch_generate_images(keywords, output_dir, args.count)
    
    # Save metadata
    meta_dir = Path('data/generated')
    meta_dir.mkdir(parents=True, exist_ok=True)
    
    meta_file = meta_dir / f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(meta_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\n💾 Metadata saved: {meta_file}")
    
    return 0 if results['successful'] > 0 else 1

if __name__ == '__main__':
    sys.exit(main())
