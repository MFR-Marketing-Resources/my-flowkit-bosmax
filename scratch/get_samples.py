import asyncio
import sqlite3
from agent.config import DB_PATH

async def get_samples():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, raw_product_title, source, category FROM product LIMIT 100")
    rows = cursor.fetchall()
    
    samples = {
        "baby_wipes": [],
        "lipmatte": [],
        "smartwatch": [],
        "fashion": [],
        "male_health": [],
        "fastmoss_clean": [],
        "manual": []
    }
    
    for row in rows:
        title = row["raw_product_title"].lower()
        source = row["source"]
        category = (row["category"] or "").lower()
        
        if "wipes" in title or "tisu" in title:
            samples["baby_wipes"].append(dict(row))
        elif "lipmatte" in title or "lipstick" in title or "powder" in title:
            samples["lipmatte"].append(dict(row))
        elif "smartwatch" in title or "watch" in title:
            samples["smartwatch"].append(dict(row))
        elif "pants" in title or "shirt" in title or "fashion" in title:
            samples["fashion"].append(dict(row))
        elif source == "FASTMOSS" and category:
            samples["fastmoss_clean"].append(dict(row))
        elif source == "MANUAL":
            samples["manual"].append(dict(row))
            
    # Look for male health specifically
    cursor.execute("SELECT id, raw_product_title, source, category FROM product WHERE category LIKE '%health%' OR raw_product_title LIKE '%men%' LIMIT 10")
    rows = cursor.fetchall()
    for row in rows:
        samples["male_health"].append(dict(row))

    print("--- SAMPLES FOUND ---")
    for k, v in samples.items():
        if v:
            print(f"{k}: {v[0]['id']} | {v[0]['raw_product_title']}")
        else:
            print(f"{k}: NOT FOUND")

if __name__ == "__main__":
    asyncio.run(get_samples())
