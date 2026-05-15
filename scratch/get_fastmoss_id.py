import sqlite3
import os
from pathlib import Path

db_path = Path('flow_agent.db')
if not db_path.exists():
    print(f"ERROR: {db_path} not found")
    exit(1)

conn = sqlite3.connect(str(db_path))
c = conn.cursor()
try:
    c.execute("SELECT id FROM product WHERE source='FASTMOSS' LIMIT 1;")
    row = c.fetchone()
    print(row[0] if row else 'NONE')
except Exception as e:
    print(f"ERROR: {e}")
conn.close()
