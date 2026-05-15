import sqlite3

def find_bosmax():
    conn = sqlite3.connect('flow_agent.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, product_short_name FROM product WHERE product_short_name LIKE ?', ('%Bosmax%',))
    rows = cursor.fetchall()
    for row in rows:
        print(f"ID: {row[0]}, Name: {row[1]}")
    conn.close()

if __name__ == "__main__":
    find_bosmax()
