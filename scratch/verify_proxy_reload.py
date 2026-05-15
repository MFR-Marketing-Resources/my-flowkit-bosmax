import json
import secrets
import urllib.request
import os
import base64
import time

# Base URL for the agent
BASE_URL = "http://127.0.0.1:8100"
IMAGE_PATH = r"C:\Users\USER\Downloads\Bosmax image.jpg"

def post_json(url, payload):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as f:
        return json.load(f)

def get_json(url):
    with urllib.request.urlopen(url) as f:
        return json.load(f)

# 1. Create a manual product with the image
print(f"Reading image: {IMAGE_PATH}")
with open(IMAGE_PATH, 'rb') as f:
    img_data = f.read()
    img_b64 = base64.b64encode(img_data).decode('utf-8')

product_payload = {
    "raw_product_title": f"Bosmax Verification {secrets.token_hex(4)}",
    "product_name": "Bosmax Verification",
    "image_base64": img_b64,
    "image_filename": "bosmax_verification.jpg"
}

print("Creating manual product...")
product_resp = post_json(f"{BASE_URL}/api/products/manual", product_payload)
product_id = product_resp.get("id")
print(f"Created product: {product_id}")

# 2. Trigger the F2V job
request_id = f"proof_f2v_{secrets.token_hex(4)}"
flow_payload = {
    "request_id": request_id,
    "mode": "F2V",
    "productId": product_id,
    "prompt": "Cinematic shot of the product on a luxury marble table, soft morning light, 8k resolution.",
    "stop_after_stage": "PROMPT_EDITABLE_AFTER_INSERT",
    "project_id": "bosmax_verify_project"
}

print(f"Triggering F2V job: {request_id}")
flow_resp = post_json(f"{BASE_URL}/api/flow/execute-flow-job", flow_payload)
print(f"Job trigger response: {json.dumps(flow_resp, indent=2)}")

# 3. Monitor telemetry
print("Monitoring telemetry (30s)...")
start_time = time.time()
stages_seen = set()
while time.time() - start_time < 60:
    try:
        telemetry = get_json(f"{BASE_URL}/api/telemetry/requests/{request_id}")
        stages = telemetry.get("stages", [])
        for s in stages:
            stage_name = s.get("stage")
            if stage_name not in stages_seen:
                print(f"[{s.get('timestamp')}] {stage_name}: {s.get('status')} - {s.get('message')}")
                stages_seen.add(stage_name)
        
        if any(s.get("stage") == "PROMPT_EDITABLE_AFTER_INSERT" for s in stages):
            print("\nSUCCESS: Target stage reached!")
            break
        if any(s.get("status") == "FAIL" for s in stages):
            print("\nFAILURE: Stop immediately.")
            break
    except Exception as e:
        pass
    time.sleep(2)

print("\nFinal Telemetry Stages:")
for s in stages_seen:
    print(f"- {s}")
