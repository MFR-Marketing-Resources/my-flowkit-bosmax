import sqlite3

def check_recent():
    conn = sqlite3.connect('flow_agent.db')
    cursor = conn.cursor()
    cursor.execute('SELECT request_id, stage, status, timestamp FROM request_stage_event ORDER BY timestamp DESC LIMIT 30')
    rows = cursor.fetchall()
    for row in rows:
        print(f"[{row[3]}] {row[0]}: {row[1]} - {row[2]}")
    conn.close()

if __name__ == "__main__":
    check_recent()
