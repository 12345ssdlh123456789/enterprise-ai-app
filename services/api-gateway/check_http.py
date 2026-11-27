import urllib.request
import json

# First login
login_data = json.dumps({"email": "admin@example.com", "password": "admin123"}).encode("utf-8")
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/v1/auth/login",
    data=login_data,
    headers={"Content-Type": "application/json"},
    method="POST",
)
resp = urllib.request.urlopen(req)
token_data = json.loads(resp.read().decode("utf-8"))
token = token_data["data"]["access_token"]
print(f"Token: {token[:20]}...")

# Create conversation with Chinese title
conv_data = json.dumps({"title": "测试对话", "model": "gpt-4o-mini", "temperature": 0.7, "max_tokens": 2048}).encode("utf-8")
req2 = urllib.request.Request(
    "http://127.0.0.1:8000/api/v1/conversations",
    data=conv_data,
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    },
    method="POST",
)
resp2 = urllib.request.urlopen(req2)
raw = resp2.read()
print(f"Raw bytes: {raw}")
print(f"Raw decoded UTF-8: {raw.decode('utf-8')}")
print(f"Content-Type header: {resp2.headers.get('Content-Type')}")
