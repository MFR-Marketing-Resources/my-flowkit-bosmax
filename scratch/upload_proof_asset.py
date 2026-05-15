import urllib.request
import json

url = "http://127.0.0.1:8100/api/flow/upload-image"
payload = {"file_path": "C:/Users/USER/Downloads/Bosmax image.jpg"}
data = json.dumps(payload).encode('utf-8')
headers = {"Content-Type": "application/json"}

try:
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req) as response:
        print(response.read().decode('utf-8'))
except Exception as e:
    print(f"Error: {e}")
