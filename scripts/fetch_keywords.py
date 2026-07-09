#!/usr/bin/env python3
"""Fetch trending keywords from Google Trends"""
import argparse, json, os, sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

try:
    from pytrends.request import TrendReq
except ImportError:
    print("Error: Install pytrends first: pip install pytrends")
    sys.exit(1)

CATEGORIES = ['business', 'nature', 'technology', 'food', 'people', 'abstract', 'travel', 'education', 'health']
BLOCKED = ['news', 'video', 'song', 'movie', 'game', 'weather', 'crypto price', 'celebrity gossip']

def is_suitable(keyword):
    kw = keyword.lower()
    return not any(b in kw for b in BLOCKED) and (any(c in kw for c in CATEGORIES) or len(kw.split()) >= 2)

def categorize(keyword):
    kw = keyword.lower()
    mapping = {
        'business': ['business', 'office', 'corporate', 'meeting', 'startup'],
        'nature': ['nature', 'landscape', 'mountain', 'ocean', 'forest'],
        'technology': ['technology', 'computer', 'phone', 'ai', 'data', 'code'],
        'food': ['food', 'restaurant', 'coffee', 'cooking'],
        'people': ['people', 'team', 'diverse', 'person', 'family'],
        'abstract': ['abstract', 'background', 'texture', 'pattern'],
        'travel': ['travel', 'city', 'architecture', 'adventure'],
        'education': ['education', 'school', 'learning', 'student'],
        'health': ['health', 'fitness', 'yoga', 'medical', 'wellness']
    }
    for cat, keywords in mapping.items():
        if any(k in kw for k in keywords): return cat
    return 'general'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', '-o', default='data/trending_keywords.json')
    args = parser.parse_args()
    
    print("Fetching trending keywords...")
    try:
        pytrends = TrendReq(hl='en-US', tz=360)
        df = pytrends.trending_searches(pn='united_states')
        
        results = []
        for idx, row in df.head(50).iterrows():
            kw = str(row[0])
            if isinstance(kw, str) and is_suitable(kw):
                results.append({'keyword': kw, 'category': categorize(kw), 'rank': idx+1})
        
        output = {
            'metadata': {'fetched_at': datetime.now().isoformat(), 'total': len(results)},
            'keywords': results[:100]
        }
        
        Path(args.output).parent.mkdir(exist_ok=True)
        with open(args.output, 'w') as f:
            json.dump(output, f, indent=2)
        
        print(f"✅ Saved {len(results)} keywords to {args.output}")
        return 0
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1

if __name__ == '__main__': sys.exit(main())
