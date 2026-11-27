import json, urllib.request
b = json.dumps({
    "title": "智汇 AI 工作台 - 智能客服助手 和另外 1 个页面",
    "name_contains": "输入问题",
    "type_contains": "Edit",
    "depth": 10
}, ensure_ascii=False).encode("utf-8")
req = urllib.request.Request("http://127.0.0.1:18765/uia_find", data=b, headers={"Content-Type": "application/json"})
print(urllib.request.urlopen(req, timeout=10).read().decode("utf-8"))
