# 统一 JSON 响应：始终带 charset=utf-8，避免浏览器按系统默认编码（如 GBK）
# 解析 UTF-8 正文导致中文显示乱码（例如 "测试对话" 显示为 "??"）。
from fastapi.responses import JSONResponse


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"
