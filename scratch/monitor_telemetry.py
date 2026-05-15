import urllib.request
import json
import time
import sys

req_id = sys.argv[1]
url = f"http://127.0.0.1:8100/api/telemetry/requests/{req_id}"

print(f"Monitoring Request: {req_id}")
print("-" * 40)

seen_stages = set()

while True:
    try:
        with urllib.request.urlopen(url) as r:
            data = json.loads(r.read().decode("utf-8"))
            telemetry = data.get("telemetry", {})
            status = telemetry.get("status", "UNKNOWN")
            stages = data.get("stages", [])
            
            for s in stages:
                stage_name = s.get("stage")
                if stage_name not in seen_stages:
                    print(f"[{s.get('timestamp')}] {s.get('status')}: {stage_name} - {s.get('message', '')}")
                    seen_stages.add(stage_name)
            
            if status in ["COMPLETED", "FAILED", "SUCCESS", "STOP_AFTER_STAGE_REACHED"]:
                print("-" * 40)
                print(f"FINAL STATUS: {status}")
                if status == "FAILED":
                    print(f"ERROR: {telemetry.get('error_message')}")
                break
    except Exception as e:
        # print(f"Error: {e}") # Suppress temporary errors
        pass
    
    time.sleep(2)
