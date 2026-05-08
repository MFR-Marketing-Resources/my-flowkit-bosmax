import os
import json
import csv
import re
import uuid
import glob
from pathlib import Path

# Config
BASE_DIR = Path(__file__).parent.parent
RAW_DIR = BASE_DIR / "data" / "products" / "raw"
OUTPUT_FILE = BASE_DIR / "data" / "products" / "product_catalog.json"
NORMALIZED_FILE = BASE_DIR / "data" / "products" / "fastmoss_products.normalized.json"
MAPPING_FILE = BASE_DIR / "data" / "products" / "category_mapping.json"

def clean_title(title):
    if not title: return ""
    return title.strip()

def generate_short_name(title):
    if not title: return ""
    # Clean up common fluff
    title = re.sub(r'(\d+PCS|Premium|All size|S/M/L/XL/XXL/XXXL|Ultra-thin|breathable|disposable|tape|pull-ups|disposable diaper tape diaper pants pull-ups)', '', title, flags=re.IGNORECASE)
    words = title.split()
    return " ".join(words[:4]).strip()

def generate_display_name(title):
    if not title: return ""
    words = title.split()
    return " ".join(words[:9]).strip()

def resolve_category_info(title, raw_category, mappings):
    # Try to match keywords in title if category is generic
    title_lower = title.lower()
    for kw, info in mappings.items():
        if kw in title_lower:
            return info
    
    # Fallback to provided category
    return {
        "category": raw_category or "Other",
        "subcategory": "General",
        "type": "Product"
    }

def process_csv(file_path, mappings):
    products = []
    try:
        with open(file_path, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            # Normalize headers
            headers = {h.lower(): h for h in reader.fieldnames}
            
            name_key = headers.get('product name') or headers.get('product title') or headers.get('title') or headers.get('name')
            img_key = headers.get('image url') or headers.get('product image') or headers.get('cover image') or headers.get('image')
            cat_key = headers.get('category') or headers.get('product category')
            shop_key = headers.get('shop name') or headers.get('shop')
            price_key = headers.get('price') or headers.get('price_min') or headers.get('min price')
            url_key = headers.get('tiktok link') or headers.get('product url') or headers.get('tiktok_product_url')

            if not name_key:
                print(f"Skipping {file_path}: No name column found.")
                return []

            for row in reader:
                raw_title = row.get(name_key, "")
                if not raw_title: continue
                
                cat_info = resolve_category_info(raw_title, row.get(cat_key, ""), mappings)
                
                product = {
                    "product_id": str(uuid.uuid4()),
                    "source": "FASTMOSS",
                    "raw_product_title": raw_title,
                    "product_display_name": generate_display_name(raw_title),
                    "product_short_name": generate_short_name(raw_title),
                    "category": cat_info["category"],
                    "subcategory": cat_info["subcategory"],
                    "type": cat_info["type"],
                    "shop_name": row.get(shop_key, ""),
                    "price_min": float(row.get(price_key, 0)) if row.get(price_key) else None,
                    "price_max": None,
                    "commission": row.get("Commission", ""),
                    "image_url": row.get(img_key, ""),
                    "tiktok_product_url": row.get(url_key, ""),
                    "fastmoss_source_file": file_path.name,
                    "asset_status": "UNRESOLVED",
                    "manual_entry_allowed": True
                }
                products.append(product)
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
    return products

def main():
    print(f"Building product catalog from {RAW_DIR}...")
    
    if not RAW_DIR.exists():
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Created {RAW_DIR}. Please place FastMoss files there.")
        return

    # Load mappings
    mappings = {}
    if MAPPING_FILE.exists():
        with open(MAPPING_FILE, 'r') as f:
            mappings = json.load(f)

    all_products = []
    
    # Process CSV files
    csv_files = RAW_DIR.glob("*.csv")
    for csv_file in csv_files:
        print(f"Processing {csv_file.name}...")
        all_products.extend(process_csv(csv_file, mappings))

    # Deduplicate by TikTok URL or Title
    seen = set()
    deduped = []
    for p in all_products:
        key = p["tiktok_product_url"] or p["raw_product_title"]
        if key not in seen:
            seen.add(key)
            deduped.append(p)

    # Save results
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(deduped, f, indent=2, ensure_ascii=False)
    
    with open(NORMALIZED_FILE, 'w', encoding='utf-8') as f:
        json.dump(deduped, f, indent=2, ensure_ascii=False)

    print(f"Finished. Total products: {len(deduped)}")
    print(f"Catalog saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
