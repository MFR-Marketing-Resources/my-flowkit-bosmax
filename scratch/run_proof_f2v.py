import urllib.request
import json
import uuid

url = "http://127.0.0.1:8100/api/flow/execute-flow-job"
request_id = f"proof_f2v_{uuid.uuid4().hex[:8]}"

payload = {
    "request_id": request_id,
    "mode": "F2V",
    "productId": "dcf0b2a3-b714-4305-a0de-37033f9762a1",
    "prompt": "Cinematic shot of the product on a luxury marble table, soft morning light, 8k resolution.",
    "stop_after_stage": "PROMPT_EDITABLE_AFTER_INSERT",
    "project_id": "test_proof_project"
}

data = json.dumps(payload).encode('utf-8')
headers = {"Content-Type": "application/json"}

print(f"Triggering proof job: {request_id}")
try:
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req) as response:
        print(response.read().decode('utf-8'))
except Exception as e:
    print(f"Error: {e}")
