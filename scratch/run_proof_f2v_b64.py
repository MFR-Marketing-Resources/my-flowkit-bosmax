import json
import secrets
import urllib.request
import os

# Base URL for the agent
BASE_URL = "http://127.0.0.1:8100"

# Read the b64 image
b64_path = os.path.join(os.path.dirname(__file__), '..', 'test_image_b64.txt')
with open(b64_path, 'r', encoding='utf-8') as f:
    start_asset_b64 = f.read()

request_id = f"proof_f2v_{secrets.token_hex(4)}"

payload = {
    "request_id": request_id,
    "mode": "F2V",
    "startAsset": {
        "previewUrl": start_asset_b64,
        "fileName": "proof_start.jpg"
    },
    "prompt": "Cinematic shot of the product on a luxury marble table, soft morning light, 8k resolution.",
    "stop_after_stage": "PROMPT_EDITABLE_AFTER_INSERT",
    "project_id": "test_proof_project"
}

print(f"Triggering proof job with B64: {request_id}")
try:
    url = f"{BASE_URL}/api/flow/execute-flow-job"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as f:
        print(f.read().decode())
except Exception as e:
    print(f"Failed to trigger: {e}")
