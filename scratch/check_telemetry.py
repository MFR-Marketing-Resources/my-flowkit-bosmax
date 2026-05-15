import sqlite3
import sys

def check_manual(target_id=None):
    conn = sqlite3.connect('flow_agent.db')
    cursor = conn.cursor()
    if target_id:
        print(f"--- Request Table: {target_id} ---")
        cursor.execute("SELECT * FROM request WHERE id = ?", (target_id,))
        for row in cursor.fetchall():
            print(row)
        print(f"--- Stage Events: {target_id} ---")
        cursor.execute("SELECT * FROM request_stage_event WHERE request_id = ? ORDER BY timestamp ASC", (target_id,))
        for row in cursor.fetchall():
            print(row)
    else:
        print("--- Recent Manual Requests ---")
        cursor.execute("SELECT * FROM request_stage_event WHERE request_id LIKE 'manual_%' ORDER BY timestamp DESC LIMIT 20")
        for row in cursor.fetchall():
            print(row)
    conn.close()

if __name__ == "__main__":
    tid = sys.argv[1] if len(sys.argv) > 1 else None
    check_manual(tid)
