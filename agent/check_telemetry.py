import sqlite3
import json
import os

db_path = "c:\\Users\\USER\\Desktop\\_ref_flowkit\\agent\\flowkit.db"

def query_latest_requests():
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("--- Latest Requests ---")
    cursor.execute("SELECT id, status, created_at FROM request ORDER BY created_at DESC LIMIT 5")
    for row in cursor.fetchall():
        print(dict(row))
        
    print("\n--- Latest Telemetry ---")
    cursor.execute("SELECT request_id, status, extension_stage, last_heartbeat_at FROM request_telemetry ORDER BY last_heartbeat_at DESC LIMIT 5")
    for row in cursor.fetchall():
        print(dict(row))
        
    conn.close()

if __name__ == "__main__":
    query_latest_requests()
