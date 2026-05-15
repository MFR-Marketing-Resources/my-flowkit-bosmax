import sqlite3
import json

def get_latest_stages(request_id):
    conn = sqlite3.connect('flow_agent.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT stage, status, message, timestamp FROM request_stage_event WHERE request_id = ? ORDER BY timestamp DESC LIMIT 20", (request_id,))
    rows = cursor.fetchall()
    for row in rows:
        print(f"[{row['timestamp']}] {row['stage']}: {row['status']} - {row['message']}")
    
    conn.close()

if __name__ == "__main__":
    get_latest_stages("bosmax_clean_proof")
