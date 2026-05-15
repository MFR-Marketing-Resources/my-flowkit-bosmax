import urllib.request
import json
import sys

req_id = sys.argv[1]
url = f"http://127.0.0.1:8100/api/telemetry/requests/{req_id}"

with urllib.request.urlopen(url) as r:
    data = json.loads(r.read().decode("utf-8"))
    for s in data.get("stages", []):
        print(f"{s.get('stage')} - {s.get('status')}")
