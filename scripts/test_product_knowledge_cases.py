import json
import urllib.request

BASE_URL = "http://127.0.0.1:8100"

CASES = [
    {
        "name": "Case A: Messy usable owned product",
        "payload": {
            "product_name": "Bosmax Ultra Soap",
            "product_knowledge_text": "Sabun dobi paling wangi di Malaysia. Botol biru 500ml. Pek refill 1.2kg pun ada. RM25.90 sahaja.",
            "source_lane": "MANUAL"
        }
    },
    {
        "name": "Case B: Incomplete vague product",
        "payload": {
            "product_name": "Something New",
            "product_knowledge_text": "Benda baru ni best gila.",
            "source_lane": "MANUAL"
        }
    },
    {
        "name": "Case C: Risky claim product",
        "payload": {
            "product_name": "Bosmax Miracle Cure",
            "product_knowledge_text": "Dapat menyembuhkan kanser dalam sekelip mata. Ingredients: air zam-zam.",
            "source_lane": "MANUAL"
        }
    },
    {
        "name": "Case D: Affiliate lane attempt",
        "payload": {
            "product_name": "Atlas Liquid",
            "product_knowledge_text": "Affiliate product description here.",
            "source_lane": "FASTMOSS"
        }
    }
]

def run_tests():
    for case in CASES:
        print(f"\n--- {case['name']} ---")
        try:
            req = urllib.request.Request(
                f"{BASE_URL}/api/product-knowledge/complete",
                data=json.dumps(case['payload']).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            with urllib.request.urlopen(req) as f:
                data = json.loads(f.read().decode('utf-8'))
                print(f"Status: {data['completion_status']}")
                print(f"Quality: {data['input_quality_status']}")
                print(f"Family: {data['suggested_bosmax_product_family']}")
                print(f"Claim Gate: {data['claim_gate']}")
                print(f"Tokens: {data['claim_tokens']}")
                print(f"Missing: {data['missing_required_evidence']}")
                print(f"Review Fields: {data['human_review_fields']}")
                print("Readiness:")
                for mode, r in data['readiness_by_mode'].items():
                    print(f"  {mode}: {r['status']} ({r['detail']})")
                print(f"Warnings: {data['warnings']}")
        except Exception as e:
            print(f"Exception: {e}")

if __name__ == "__main__":
    run_tests()
