#!/usr/bin/env python3
"""Update API JSON indexes"""
import argparse, json, os, sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict

def scan_images(images_dir: Path) -> list:
    images = []
    for ext in ['.png', '.jpg', '.jpeg']:
        for img_path in images_dir.rglob(f'*{ext}'):
            stat = img_path.stat()
            images.append({
                'id': f"img_{img_path.stem}",
                'filename': img_path.name,
                'url': f"/{img_path.relative_to(img_path.parent.parent)}",
                'size_kb': round(stat.st_size/1024, 2),
                'created_at': datetime.fromtimestamp(stat.st_ctime).isoformat()
            })
    return images

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--images-dir', '-i', default='images')
    parser.add_argument('--api-dir', '-a', default='api')
    args = parser.parse_args()
    
    images = scan_images(Path(args.images_dir))
    api_dir = Path(args.api_dir)
    api_dir.mkdir(parents=True, exist_ok=True)
    
    # Create main API file
    api_data = {
        'api_version': '1.0.0',
        'total_images': len(images),
        'last_updated': datetime.now().isoformat(),
        'images': images
    }
    
    with open(api_dir / 'images.json', 'w') as f:
        json.dump(api_data, f, indent=2)
    
    # Create info endpoint
    info = {
        'name': 'AI Stock Photo API',
        'version': '1.0.0',
        'total_images': len(images),
        'license': 'CC0 1.0 Universal',
        'last_updated': datetime.now().isoformat()
    }
    with open(api_dir / 'info.json', 'w') as f:
        json.dump(info, f, indent=2)
    
    print(f"✅ Updated API: {len(images)} images indexed")

if __name__ == '__main__': main()
