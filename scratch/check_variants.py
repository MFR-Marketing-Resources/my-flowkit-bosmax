import sqlite3

def check_db():
    conn = sqlite3.connect('flow_agent.db')
    conn.row_factory = sqlite3.Row
    
    print("--- Products ---")
    products = conn.execute("SELECT id, product_short_name FROM product WHERE product_short_name LIKE '%Sumikko%'").fetchall()
    for p in products:
        print(dict(p))
        
    print("\n--- Specific Variant ---")
    v_id = 'ac56b95e-942e-4d4e-bdc6-82f643f61b5b'
    res = conn.execute("SELECT variant_id, queue_status, blocked_reason FROM batch_variant WHERE variant_id = ?", (v_id,)).fetchone()
    if res:
        print(dict(res))
    else:
        print("Variant not found")

    
    conn.close()

if __name__ == "__main__":
    check_db()
