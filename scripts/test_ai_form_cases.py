import json
import sqlite3
import urllib.request
import urllib.parse
import uuid

BASE_URL = "http://127.0.0.1:8100"

def get_db_stats():
    conn = sqlite3.connect('flow_agent.db')
    c = conn.cursor()
    count = c.execute('SELECT COUNT(*) FROM product').fetchone()[0]
    max_updated = c.execute('SELECT MAX(updated_at) FROM product').fetchone()[0]
    conn.close()
    return count, max_updated

print("--- Initial DB Stats ---")
initial_count, initial_updated = get_db_stats()
print(f"Count: {initial_count}")
print(f"Max Updated: {initial_updated}")

def test_case(name, content, file_name="form.md"):
    print(f"\n--- Case {name} ---")
    
    boundary = "----WebKitFormBoundary" + str(uuid.uuid4()).replace("-", "")
    parts = []
    parts.append('--' + boundary)
    parts.append('Content-Disposition: form-data; name="file"; filename="%s"' % file_name)
    parts.append('Content-Type: text/markdown')
    parts.append('')
    parts.append(content)
    parts.append('--' + boundary + '--')
    parts.append('')
    body = "\r\n".join(parts).encode('utf-8')
    
    req = urllib.request.Request(f"{BASE_URL}/api/product-knowledge/import-ai-form", data=body)
    req.add_header('Content-Type', 'multipart/form-data; boundary=%s' % boundary)
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            print(f"Status: {data['parse_status']}")
            if data['completion_response']:
                print(f"Completion: {data['completion_response']['completion_status']}")
                print(f"Claim Gate: {data['completion_response']['claim_gate']}")
            print(f"Warnings: {data['parse_warnings']}")
            print(f"Errors: {data['parse_errors']}")
    except Exception as e:
        print(f"Error: {e}")

# A. Valid completed Markdown form for owned product
case_a = """
```json
{
  "bosmax_product_knowledge_form_version": "1.0",
  "product_name": "Smart Laundry Pods",
  "source_lane": "OWNED",
  "product_knowledge_text": "3-in-1 pods for easy laundry",
  "size_or_volume": "20 pods",
  "user_review_status": "USER_APPROVED"
}
```
"""
test_case("A (Valid Markdown)", case_a)

# B. Valid raw JSON form
case_b = """{
  "bosmax_product_knowledge_form_version": "1.0",
  "product_name": "JSON Product",
  "source_lane": "OWNED",
  "product_knowledge_text": "Raw JSON intake"
}"""
test_case("B (Raw JSON)", case_b, "form.json")

# C. Malformed markdown/json
case_c = "```json { this is not json } ```"
test_case("C (Malformed)", case_c)

# D. Risky claim form
case_d = """
```json
{
  "bosmax_product_knowledge_form_version": "1.0",
  "product_name": "Slimming Tea",
  "product_knowledge_text": "Lose 10kg in 1 day! Whitening and slimming miracle.",
  "user_review_status": "USER_APPROVED"
}
```
"""
test_case("D (Risky Claim)", case_d)

# E. Affiliate lane form
case_e = """
```json
{
  "bosmax_product_knowledge_form_version": "1.0",
  "product_name": "Affiliate Item",
  "source_lane": "FASTMOSS"
}
```
"""
test_case("E (Affiliate Lane)", case_e)

print("\n--- Final DB Stats ---")
final_count, final_updated = get_db_stats()
print(f"Count: {final_count}")
print(f"Max Updated: {final_updated}")

if initial_count == final_count and initial_updated == final_updated:
    print("\nNO DB MUTATION: PASS")
else:
    print("\nDB MUTATION DETECTED: FAIL")
