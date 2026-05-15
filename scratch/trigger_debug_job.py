import urllib.request
import json
import uuid

request_id = f"manual_debug_{uuid.uuid4().hex[:8]}"
url = "http://127.0.0.1:8100/api/flow/execute-flow-job"
data = {
    "request_id": request_id,
    "mode": "F2V",
    "asset_source": "877821e9-2613-43c4-aac9-dc2df3173ee2",
    "prompt": "UAT PROOF: Cinematic video of a Bosmax product.",
    "stop_after_stage": "PROMPT_EDITABLE_AFTER_INSERT",
    "orientation": "VERTICAL",
    "count": 1,
    "modelLabel": "Veo 3.1 - Lite"
}

print(f"Submitting job {request_id}...")
req = urllib.request.Request(url, data=json.dumps(data).encode(), headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(req) as f:
    print(f.read().decode())
