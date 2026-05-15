import sqlite3
import json

def query_db():
    conn = sqlite3.connect('flow_agent.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("--- Projects ---")
    cursor.execute("SELECT * FROM project WHERE name LIKE '%Bosmax%'")
    projects = [dict(row) for row in cursor.fetchall()]
    for p in projects:
        print(f"Project ID: {p['id']}, Name: {p['name']}")
        
        print(f"  --- Videos for Project {p['id']} ---")
        cursor.execute("SELECT * FROM video WHERE project_id = ?", (p['id'],))
        videos = [dict(row) for row in cursor.fetchall()]
        for v in videos:
            print(f"  Video ID: {v['id']}, Name: {v['name']}")
            
            print(f"    --- Scenes for Video {v['id']} ---")
            cursor.execute("SELECT * FROM scene WHERE video_id = ?", (v['id'],))
            scenes = [dict(row) for row in cursor.fetchall()]
            for s in scenes:
                print(f"    Scene ID: {s['id']}, Display Order: {s['display_order']}")

    conn.close()

if __name__ == "__main__":
    query_db()
