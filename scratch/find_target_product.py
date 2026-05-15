import sqlite3
import json

def find_product():
    conn = sqlite3.connect('agent_db.sqlite')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    query = "SELECT * FROM products WHERE product_display_name LIKE '%SABUN DOBI%' OR raw_product_title LIKE '%SABUN DOBI%' LIMIT 1"
    cursor.execute(query)
    row = cursor.fetchone()
    
    if row:
        print(json.dumps(dict(row), indent=2))
    else:
        print("Product not found")
    
    conn.close()

if __name__ == "__main__":
    find_product()
