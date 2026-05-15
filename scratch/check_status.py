import sqlite3
import json

def check_status(request_id):
    conn = sqlite3.connect('flow_agent.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT status, error_message, updated_at FROM request WHERE id = ?", (request_id,))
    row = cursor.fetchone()
    if row:
        print(f"Request Status: {row['status']}")
        print(f"Error Message: {row['error_message']}")
        print(f"Updated At: {row['updated_at']}")
        
    cursor.execute("SELECT status, google_flow_stage, extension_stage, worker_stage, error_message FROM request_telemetry WHERE request_id = ?", (request_id,))
    row = cursor.fetchone()
    if row:
        print(f"Telemetry Status: {row['status']}")
        print(f"Flow Stage: {row['google_flow_stage']}")
        print(f"Ext Stage: {row['extension_stage']}")
        print(f"Worker Stage: {row['worker_stage']}")
        print(f"Tel Error: {row['error_message']}")

    conn.close()

if __name__ == "__main__":
    check_status("4e578b1b-a80c-4d32-81b3-8bd3b004da38")
