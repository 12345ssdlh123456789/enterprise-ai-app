import json, urllib.request

# 登录
body = json.dumps({"email":"admin@example.com","password":"admin123"}).encode()
req = urllib.request.Request("http://127.0.0.1:8000/api/v1/auth/login", data=body, headers={"Content-Type":"application/json"})
resp = urllib.request.urlopen(req, timeout=10)
data = json.loads(resp.read().decode())
token = data["data"]["access_token"]
print("token ok:", token[:20])

# 创建中文标题对话
body2 = json.dumps({"title":"测试对话","model":"gpt-4o-mini"}).encode()
req2 = urllib.request.Request("http://127.0.0.1:8000/api/v1/conversations/", data=body2, headers={"Content-Type":"application/json","Authorization":"Bearer "+token})
resp2 = urllib.request.urlopen(req2, timeout=10)
raw = resp2.read()
print("Content-Type:", resp2.headers.get("Content-Type"))
print("RAW bytes:", raw)
print("RAW decode utf-8:", raw.decode("utf-8"))
