import json
import sqlite3
import urllib.request
import uuid

BASE_URL = "http://127.0.0.1:8100"

def get_db_stats():
    conn = sqlite3.connect('flow_agent.db')
    c = conn.cursor()
    count = c.execute('SELECT COUNT(*) FROM product').fetchone()[0]
    max_updated = c.execute('SELECT MAX(updated_at) FROM product').fetchone()[0]
    conn.close()
    return count, max_updated

def run_test_case(name, completion_payload):
    print(f"\n--- Case {name} ---")
    data = json.dumps(completion_payload).encode('utf-8')
    req = urllib.request.Request(f"{BASE_URL}/api/product-registration/review-draft", data=data, headers={'Content-Type': 'application/json'})
    
    try:
        with urllib.request.urlopen(req) as response:
            res = json.loads(response.read().decode())
            print(f"Status: {res['review_status']}")
            print(f"Write Back Allowed: {res['write_back_allowed']}")
            print(f"Candidates: {list(res['canonical_candidate_fields'].keys())[:5]}...")
            if res['warnings']:
                print(f"Warnings: {res['warnings']}")
            if res['claim_gate'] != 'CLAIM_SAFE':
                print(f"Claim Gate: {res['claim_gate']}")
    except Exception as e:
        print(f"Error: {e}")

print("--- Initial DB Stats ---")
initial_count, initial_updated = get_db_stats()
print(f"Count: {initial_count}, Max Updated: {initial_updated}")

# Case A: Clean owned product
case_a = {
    "completion_status": "COMPLETION_READY",
    "input_quality_status": "SUFFICIENT",
    "declared_evidence_summary": "Name: Good Soap",
    "extracted_product_facts": {"product_name": "Good Soap"},
    "suggested_normalized_name": "Good Soap",
    "suggested_category": "Personal Care",
    "claim_gate": "CLAIM_SAFE",
    "readiness_by_mode": {}
}
run_test_case("A (Clean)", case_a)

# Case B: Incomplete
case_b = {
    "completion_status": "NEEDS_REVIEW",
    "input_quality_status": "PARTIAL",
    "declared_evidence_summary": "Name: Unknown",
    "extracted_product_facts": {"product_name": "Unknown"},
    "missing_required_evidence": ["SIZE_OR_VOLUME_EVIDENCE"],
    "readiness_by_mode": {}
}
run_test_case("B (Incomplete)", case_b)

# Case C: Risky Claim
case_c = {
    "completion_status": "NEEDS_REVIEW",
    "input_quality_status": "PARTIAL",
    "declared_evidence_summary": "Name: Cure-All",
    "extracted_product_facts": {"product_name": "Cure-All"},
    "claim_gate": "CLAIM_BLOCKED",
    "claim_tokens": ["cure"],
    "blocked_fields": ["claims"],
    "readiness_by_mode": {}
}
run_test_case("C (Risky Claim)", case_c)

# Case D: Affiliate Lane
case_d = {
    "completion_status": "COMPLETION_READY",
    "input_quality_status": "SUFFICIENT",
    "declared_evidence_summary": "Name: Fast Product",
    "extracted_product_facts": {"product_name": "Fast Product"},
    "warnings": ["AFFILIATE_LANE_CONTAMINATION_RISK"],
    "readiness_by_mode": {}
}
run_test_case("D (Affiliate Lane)", case_d)

# Case E: Missing Scale
case_e = {
    "completion_status": "COMPLETION_READY",
    "input_quality_status": "SUFFICIENT",
    "declared_evidence_summary": "Name: Giant Box",
    "extracted_product_facts": {"product_name": "Giant Box"},
    "human_review_fields": ["physics_profile"],
    "readiness_by_mode": {"product_asset_generator": {"status": "NEEDS_PHYSICS", "detail": "..."}}
}
run_test_case("E (Missing Scale)", case_e)

print("\n--- Final DB Stats ---")
final_count, final_updated = get_db_stats()
print(f"Count: {final_count}, Max Updated: {final_updated}")

if initial_count == final_count and initial_updated == final_updated:
    print("\nNO DB MUTATION: PASS")
else:
    print("\nDB MUTATION DETECTED: FAIL")
