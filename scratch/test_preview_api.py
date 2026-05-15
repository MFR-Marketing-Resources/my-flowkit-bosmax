import requests
import json

def test_preview():
    url = "http://127.0.0.1:8100/product-asset-generator/preview"
    payload = {
        "product_id": "50aae071-b519-47ae-925a-67dea1c122da",
        "product_payload": {
            "raw_product_title": "3 IN 1 SABUN DOBI (DETERGENT) VIRAL ANTIBAKTERIA",
            "target_asset_intent": "CHARACTER_HOLDING_PRODUCT_IMAGE_PROMPT",
            "camera_capture_mode": "CINEMATIC_PRO"
        },
        "target_asset_intent": "CHARACTER_HOLDING_PRODUCT_IMAGE_PROMPT",
        "dry_run_only": True
    }
    
    response = requests.post(url, json=payload)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        print(json.dumps(response.json(), indent=2))
    else:
        print(response.text)

if __name__ == "__main__":
    test_preview()
