#!/usr/bin/env python3
"""Fetch trending keywords with fallback support"""
import argparse
import json
import os
import sys
import random
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

# FALLBACK KEYWORDS (used when Google Trends fails)
FALLBACK_KEYWORDS = [
    {"keyword": "modern office workspace", "category": "business", "rank": 1},
    {"keyword": "professional business meeting", "category": "business", "rank": 2},
    {"keyword": "startup team collaboration", "category": "business", "rank": 3},
    {"keyword": "corporate executive portrait", "category": "business", "rank": 4},
    {"keyword": "mountain landscape sunset", "category": "nature", "rank": 5},
    {"keyword": "ocean beach waves", "category": "nature", "rank": 6},
    {"keyword": "forest trees sunlight", "category": "nature", "rank": 7},
    {"keyword": "flower garden spring", "category": "nature", "rank": 8},
    {"keyword": "artificial intelligence technology", "category": "technology", "rank": 9},
    {"keyword": "computer coding workspace", "category": "technology", "rank": 10},
    {"keyword": "smartphone mobile app", "category": "technology", "rank": 11},
    {"keyword": "data visualization charts", "category": "technology", "rank": 12},
    {"keyword": "healthy food salad bowl", "category": "food", "rank": 13},
    {"keyword": "coffee cup cafe", "category": "food", "rank": 14},
    {"keyword": "restaurant dining table", "category": "food", "rank": 15},
    {"keyword": "diverse people group", "category": "people", "rank": 16},
    {"keyword": "happy family moment", "category": "people", "rank": 17},
    {"keyword": "fitness yoga exercise", "category": "health", "rank": 18},
    {"keyword": "abstract geometric pattern", "category": "abstract", "rank": 19},
    {"keyword": "city skyline architecture", "category": "travel", "rank": 20}
]

def try_fetch_from_google_trends() -> List[Dict[str, Any]]:
    """Try to fetch keywords from Google Trends."""
    try:
        from pytrends.request import TrendReq
        
        print("📊 Attempting to fetch from Google Trends...")
        pytrends = TrendReq(hl='en-US', tz=360)
        
        df = pytrends.trending_searches(pn='united_states')
        
        results = []
        for idx, row in df.head(30).iterrows():
            kw = str(row[0]) if hasattr(row, 'iloc') else str(row[0])
            results.append({
                'keyword': kw,
                'category': categorize_keyword(kw),
                'rank': idx + 1,
                'source': 'google_trends'
            })
        
        print(f"✅ Successfully fetched {len(results)} keywords from Google Trends")
        return results
        
    except Exception as e:
        print(f"⚠️ Google Trends failed: {e}")
        print("🔄 Using fallback keywords instead...")
        return None

def categorize_keyword(keyword: str) -> str:
    """Categorize a keyword into stock photo category."""
    kw_lower = keyword.lower()
    
    categories = {
        'business': ['business', 'office', 'corporate', 'meeting', 'startup', 'company', 'work', 'professional'],
        'nature': ['nature', 'landscape', 'mountain', 'ocean', 'forest', 'tree', 'flower', 'garden', 'sunset', 'beach'],
        'technology': ['technology', 'computer', 'phone', 'ai', 'data', 'code', 'digital', 'tech', 'software'],
        'food': ['food', 'restaurant', 'coffee', 'cooking', 'recipe', 'meal', 'drink', 'salad'],
        'people': ['people', 'team', 'diverse', 'person', 'woman', 'man', 'family', 'group', 'human'],
        'abstract': ['abstract', 'background', 'texture', 'pattern', 'color', 'geometric', 'design', 'art'],
        'travel': ['travel', 'city', 'architecture', 'urban', 'building', 'adventure', 'skyline'],
        'education': ['education', 'school', 'learning', 'book', 'student', 'university', 'study'],
        'health': ['health', 'fitness', 'yoga', 'medical', 'wellness', 'sport', 'exercise']
    }
    
    for cat, keywords in categories.items():
        if any(k in kw_lower for k in keywords):
            return cat
    
    return 'general'

def main():
    parser = argparse.ArgumentParser(description='Fetch trending keywords')
    parser.add_argument('--output', '-o', default='data/trending_keywords.json')
    args = parser.parse_args()
    
    print("\n" + "="*50)
    print("🔍 KEYWORD FETCHER")
    print("="*50 + "\n")
    
    # Try Google Trends first
    keywords = try_fetch_from_google_trends()
    
    # Fall back to predefined list if needed
    if not keywords:
        print(f"\n📝 Using {len(FALLBACK_KEYWORDS)} fallback keywords")
        keywords = FALLBACK_KEYWORDS
    
    # Ensure we have enough keywords
    if len(keywords) < 20:
        # Add more fallback keywords if needed
        extra_fallbacks = [kw for kw in FALLBACK_KEYWORDS if kw not in keywords]
        keywords.extend(extra_fallbacks[:20 - len(keywords)])
    
    # Build output data
    output_data = {
        'metadata': {
            'fetched_at': datetime.now().isoformat(),
            'total_keywords': len(keywords),
            'source': 'google_trends' if keywords and keywords[0].get('source') == 'google_trends' else 'fallback',
            'note': 'Using fallback keywords due to Google Trends limitation'
        },
        'keywords': keywords[:50]  # Limit to 50
    }
    
    # Save to file
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Saved {len(keywords)} keywords to {output_path}")
    print("\n📋 Sample keywords:")
    for i, kw in enumerate(keywords[:5], 1):
        print(f"   {i}. [{kw['category']:10s}] {kw['keyword']}")
    if len(keywords) > 5:
        print(f"   ... and {len(keywords) - 5} more")
    
    print("\n" + "="*50)
    return 0

if __name__ == '__main__':
    sys.exit(main())
