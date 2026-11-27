"""
微服务冒烟测试。

用法（先按 docs/runbooks/local-dev.md 启动对应服务）：
    python tests/test_microservices_smoke.py

只依赖标准库。每个服务单独判定：没启动就跳过该类用例，启动了就必须真实读写成功。
覆盖：auth（注册/登录/me）、notification（创建/列表/已读）、
llm（Provider/Model 创建、成本汇总）、document（文档登记/统计）、workflow（创建/校验），
以及 X-Tenant-Id 租户隔离、/ready 数据库探活、非法租户头 400。
"""

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid

GATEWAY_BASE = os.getenv("GATEWAY_BASE", "http://127.0.0.1:8000")

SERVICES = {
    "auth": os.getenv("AUTH_BASE", "http://127.0.0.1:8007"),
    "notification": os.getenv("NOTIFICATION_BASE", "http://127.0.0.1:8006"),
    "llm": os.getenv("LLM_BASE", "http://127.0.0.1:8003"),
    "document": os.getenv("DOCUMENT_BASE", "http://127.0.0.1:8004"),
    "workflow": os.getenv("WORKFLOW_BASE", "http://127.0.0.1:8005"),
    "rag": os.getenv("RAG_BASE", "http://127.0.0.1:8001"),
}

# 非法租户头用例：服务 -> 一个必然存在的路径
PATHS_FOR_HEADER_TEST = {
    "llm": "/api/v1/providers",
    "document": "/api/v1/documents",
    "workflow": "/api/v1/workflows",
    "rag": "/api/v1/knowledge-bases",
}

# 服务间签名用例：服务 -> 一个受签名保护的路径（六个服务都要覆盖）
PATHS_FOR_SIGNATURE_TEST = {
    "auth": "/api/v1/auth/me",
    "notification": "/api/v1/notifications",
    "llm": "/api/v1/providers",
    "document": "/api/v1/documents",
    "workflow": "/api/v1/workflows",
    "rag": "/api/v1/knowledge-bases",
}

_ROOT_ENV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")


def load_service_key() -> str:
    """服务间签名密钥：优先环境变量，其次仓库根 .env。都没有 = 服务处于本地开发模式。"""
    key = os.getenv("SERVICE_API_KEY", "").strip()
    if key:
        return key
    try:
        with open(_ROOT_ENV, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("SERVICE_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


SERVICE_KEY = load_service_key()


def signature_headers(method: str, path: str, headers: dict | None = None, key: str | None = None, timestamp=None) -> dict:
    """按服务端的 canonical 规则生成签名头（与服务内 app/core/service_auth.py 保持一致）。"""
    key = SERVICE_KEY if key is None else key
    if not key:
        return {}
    ts = str(int(time.time() if timestamp is None else timestamp))
    tenant = (headers or {}).get("X-Tenant-Id", "")
    user = (headers or {}).get("X-User-Id", "")
    canon = "\n".join([method.upper(), path.split("?")[0], tenant, user, ts])
    mac = hmac.new(key.encode("utf-8"), canon.encode("utf-8"), hashlib.sha256).hexdigest()
    return {"X-Service-Timestamp": ts, "X-Service-Signature": mac}


def call(
    base: str,
    path: str,
    method: str = "GET",
    token: str | None = None,
    body: dict | None = None,
    headers: dict | None = None,
    sign: bool = True,
    sign_key: str | None = None,
    sign_ts=None,
):
    """返回 (status, payload)。参数说明见 call_full()。"""
    status, payload, _ = call_full(
        base, path, method, token, body, headers, sign, sign_key, sign_ts
    )
    return status, payload


def call_full(
    base: str,
    path: str,
    method: str = "GET",
    token: str | None = None,
    body: dict | None = None,
    headers: dict | None = None,
    sign: bool = True,
    sign_key: str | None = None,
    sign_ts=None,
):
    """返回 (status, payload, headers)。headers 已小写化（检测转发开关 / X-Total-Count 用）。

    headers 参数用于模拟网关注入的 X-Tenant-Id / X-User-Id；配置了 SERVICE_API_KEY 时
    默认自动附带合法签名（sign=False 可构造未签名请求，sign_key/sign_ts 用于构造坏签名）。
    """
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data:
        req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    if sign:
        for key, value in signature_headers(method, path, headers, sign_key, sign_ts).items():
            req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return (
                resp.status,
                _parse(resp.read().decode("utf-8", "replace")),
                {key.lower(): value for key, value in resp.headers.items()},
            )
    except urllib.error.HTTPError as exc:
        return (
            exc.code,
            _parse(exc.read().decode("utf-8", "replace")),
            {key.lower(): value for key, value in exc.headers.items()},
        )


def call_multipart(
    base: str,
    path: str,
    fields: dict | None = None,
    filename: str = "upload.txt",
    content: bytes = b"",
    headers: dict | None = None,
    content_type: str = "text/plain",
    token: str | None = None,
):
    """multipart/form-data 上传（文档服务的 /upload/multipart 用），签名规则同 call()。"""
    boundary = "----smoke" + uuid.uuid4().hex
    crlf = bytes([13, 10])
    marker = b"--" + boundary.encode("ascii")
    body = b""
    for name, value in (fields or {}).items():
        body += marker + crlf
        body += b'Content-Disposition: form-data; name="' + name.encode("utf-8") + b'"' + crlf + crlf
        body += str(value).encode("utf-8") + crlf
    body += marker + crlf
    body += b'Content-Disposition: form-data; name="file"; filename="' + filename.encode("utf-8") + b'"' + crlf
    body += b"Content-Type: " + content_type.encode("utf-8") + crlf + crlf
    body += content + crlf
    body += marker + b"--" + crlf

    req = urllib.request.Request(base + path, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    for key, value in signature_headers("POST", path, headers).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, _parse(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return exc.code, _parse(exc.read().decode("utf-8", "replace"))


def _parse(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def gateway_login() -> str | None:
    """网关是否在跑 + 登录拿 JWT（转发类用例的前置）。"""
    try:
        urllib.request.urlopen(GATEWAY_BASE + "/health", timeout=5)
    except Exception:
        return None
    status, payload = call(
        GATEWAY_BASE,
        "/api/v1/auth/login",
        "POST",
        body={"email": "admin@example.com", "password": "admin123"},
        sign=False,
    )
    if status != 200 or not isinstance(payload, dict):
        return None
    data = payload.get("data", payload)
    return data.get("access_token")


def probe() -> dict[str, bool]:
    """探测哪些服务在运行。"""
    up = {}
    for name, base in SERVICES.items():
        try:
            urllib.request.urlopen(base + "/health", timeout=5)
            up[name] = True
        except Exception:
            up[name] = False
    return up


class MicroservicesSmokeTest(unittest.TestCase):
    running: dict[str, bool] = {}

    @classmethod
    def setUpClass(cls):
        if not cls.running:
            cls.running = probe()

    def base(self, name: str) -> str:
        if not self.running.get(name):
            self.skipTest(f"{name}-service 未启动（{SERVICES[name]}）")
        return SERVICES[name]

    # ------------------------------------------------------------ 通用
    def test_ready_checks_database(self):
        for name in ("llm", "document", "workflow", "notification", "auth", "rag"):
            if not self.running.get(name):
                continue
            with self.subTest(service=name):
                status, payload = call(SERVICES[name], "/ready")
                self.assertEqual(status, 200, payload)
                self.assertEqual(payload["status"], "ready")

    def test_invalid_tenant_header_is_400(self):
        for name, path in PATHS_FOR_HEADER_TEST.items():
            if not self.running.get(name):
                continue
            with self.subTest(service=name):
                status, payload = call(SERVICES[name], path, headers={"X-Tenant-Id": "not-a-uuid"})
                self.assertEqual(status, 400, payload)

    # ------------------------------------------------------------ 服务间签名
    def _require_key(self):
        if not SERVICE_KEY:
            self.skipTest("未配置 SERVICE_API_KEY：服务处于本地开发模式，不校验签名")

    def test_missing_signature_is_401(self):
        """服务间签名一旦配置，未签名的请求必须被拒（否则伪造 X-Tenant-Id 就能冒充租户）。"""
        self._require_key()
        for name, path in PATHS_FOR_SIGNATURE_TEST.items():
            if not self.running.get(name):
                continue
            with self.subTest(service=name):
                status, payload = call(SERVICES[name], path, sign=False)
                self.assertEqual(status, 401, payload)
                self.assertIn("签名", payload.get("detail", "") if isinstance(payload, dict) else str(payload))

    def test_forged_signature_is_401(self):
        """用错误的密钥签名等同于伪造租户头，必须 401。"""
        self._require_key()
        for name, path in PATHS_FOR_SIGNATURE_TEST.items():
            if not self.running.get(name):
                continue
            with self.subTest(service=name):
                status, payload = call(SERVICES[name], path, sign_key="not-the-service-key")
                self.assertEqual(status, 401, payload)

    def test_stale_signature_is_401(self):
        """过期签名（超出 300 秒时差窗口）必须 401，防止旧请求被重放。"""
        self._require_key()
        for name, path in PATHS_FOR_SIGNATURE_TEST.items():
            if not self.running.get(name):
                continue
            with self.subTest(service=name):
                status, payload = call(SERVICES[name], path, sign_ts=int(time.time()) - 3600)
                self.assertEqual(status, 401, payload)
                detail = payload.get("detail", "") if isinstance(payload, dict) else str(payload)
                self.assertIn("过期", detail)

    # ------------------------------------------------------------ auth
    def test_auth_register_login_me(self):
        base = self.base("auth")
        suffix = uuid.uuid4().hex[:8]
        username = f"smoke_{suffix}"
        status, created = call(
            base,
            "/api/v1/auth/register",
            "POST",
            body={"username": username, "email": f"{username}@example.com", "password": "smoke-pass-123"},
        )
        self.assertEqual(status, 201, created)
        self.assertEqual(created["username"], username)

        status, token = call(base, "/api/v1/auth/login", "POST", body={"username": username, "password": "smoke-pass-123"})
        self.assertEqual(status, 200, token)
        access = token["access_token"]

        status, me = call(base, "/api/v1/auth/me", token=access)
        self.assertEqual(status, 200, me)
        self.assertEqual(me["username"], username)

        status, _ = call(base, "/api/v1/auth/login", "POST", body={"username": username, "password": "wrong"})
        self.assertEqual(status, 401)

    # ------------------------------------------------------------ notification
    def test_notification_create_list_read(self):
        base = self.base("notification")
        recipient = f"smoke-{uuid.uuid4().hex[:8]}"
        status, created = call(
            base,
            "/api/v1/notifications",
            "POST",
            body={"recipient_id": recipient, "channel": "in_app", "subject": "冒烟测试", "content": "微服务写入验证"},
        )
        self.assertEqual(status, 201, created)

        status, listed = call(base, f"/api/v1/notifications?recipient_id={recipient}")
        self.assertEqual(status, 200, listed)
        self.assertEqual(listed["total"], 1)
        self.assertEqual(listed["items"][0]["content"], "微服务写入验证")

        status, read = call(base, f"/api/v1/notifications/{created['id']}/read", "POST")
        self.assertEqual(status, 200, read)

    # ------------------------------------------------------------ llm
    def test_llm_provider_and_model_crud(self):
        base = self.base("llm")
        tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
        provider_name = f"smoke-provider-{uuid.uuid4().hex[:6]}"
        status, provider = call(
            base,
            "/api/v1/providers",
            "POST",
            body={"name": provider_name, "provider_type": "openai", "api_key": "sk-smoke", "metadata": {"source": "smoke"}},
            headers={"X-Tenant-Id": tenant_a},
        )
        self.assertEqual(status, 201, provider)
        self.assertEqual(provider["name"], provider_name)
        self.assertEqual(provider["metadata"], {"source": "smoke"})
        self.assertEqual(provider["tenant_id"], tenant_a)

        status, providers = call(base, "/api/v1/providers", headers={"X-Tenant-Id": tenant_a})
        self.assertEqual(status, 200, providers)
        self.assertIn(provider["id"], [p["id"] for p in providers])

        # 另一个租户看不到
        status, other = call(base, "/api/v1/providers", headers={"X-Tenant-Id": tenant_b})
        self.assertEqual(status, 200, other)
        self.assertNotIn(provider["id"], [p["id"] for p in other])

        status, model = call(
            base,
            "/api/v1/models",
            "POST",
            body={
                "provider_id": provider["id"],
                "name": f"smoke-model-{uuid.uuid4().hex[:6]}",
                "display_name": "Smoke Model",
                "model_type": "chat",
            },
            headers={"X-Tenant-Id": tenant_a},
        )
        self.assertEqual(status, 201, model)

        status, summary = call(base, "/api/v1/usage/cost-summary", headers={"X-Tenant-Id": tenant_a})
        self.assertEqual(status, 200, summary)

    # ------------------------------------------------------------ document
    def test_document_register_and_stats(self):
        base = self.base("document")
        tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
        digest = uuid.uuid4().hex
        status, doc = call(
            base,
            "/api/v1/documents",
            "POST",
            body={
                "filename": "smoke.txt",
                "original_filename": "smoke.txt",
                "content_type": "text/plain",
                "file_size": 12,
                "file_hash": digest,
                "metadata": {"source": "smoke"},
            },
            headers={"X-Tenant-Id": tenant_a},
        )
        self.assertEqual(status, 201, doc)
        self.assertEqual(doc["metadata"], {"source": "smoke"})
        self.assertEqual(doc["tenant_id"], tenant_a)
        self.assertEqual(doc["document_type"], "txt")
        self.assertEqual(doc["storage_path"], f"documents/{tenant_a}/{digest}")

        status, docs = call(base, "/api/v1/documents", headers={"X-Tenant-Id": tenant_a})
        self.assertEqual(status, 200, docs)
        self.assertIn(doc["id"], [d["id"] for d in docs])

        status, other = call(base, "/api/v1/documents", headers={"X-Tenant-Id": tenant_b})
        self.assertEqual(status, 200, other)
        self.assertNotIn(doc["id"], [d["id"] for d in other])

        # 知道 UUID 也不能跨租户读：按 id 取文档必须校验租户
        status, foreign = call(
            base, f"/api/v1/documents/{doc['id']}", headers={"X-Tenant-Id": tenant_b}
        )
        self.assertEqual(status, 404, foreign)

        status, stats = call(base, "/api/v1/documents/stats/summary", headers={"X-Tenant-Id": tenant_a})
        self.assertEqual(status, 200, stats)

    # ------------------------------------------------------------ workflow
    def test_workflow_create_and_validate(self):
        base = self.base("workflow")
        tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
        definition = {
            "nodes": [
                {"id": "start", "type": "start"},
                {"id": "end", "type": "end"},
            ],
            "edges": [{"from": "start", "to": "end"}],
        }
        status, wf = call(
            base,
            "/api/v1/workflows",
            "POST",
            body={"name": f"smoke-workflow-{uuid.uuid4().hex[:6]}", "description": "冒烟测试", "definition": definition},
            headers={"X-Tenant-Id": tenant_a},
        )
        self.assertEqual(status, 201, wf)
        self.assertEqual(wf["definition"], definition)
        self.assertEqual(wf["tenant_id"], tenant_a)

        status, workflows = call(base, "/api/v1/workflows", headers={"X-Tenant-Id": tenant_a})
        self.assertEqual(status, 200, workflows)
        self.assertIn(wf["id"], [w["id"] for w in workflows])

        status, other = call(base, "/api/v1/workflows", headers={"X-Tenant-Id": tenant_b})
        self.assertEqual(status, 200, other)
        self.assertNotIn(wf["id"], [w["id"] for w in other])

        status, validated = call(
            base, "/api/v1/workflows/validate", "POST", body={"definition": definition}, headers={"X-Tenant-Id": tenant_a}
        )
        self.assertEqual(status, 200, validated)

        # 知道 UUID 也不能跨租户读：按 id 取工作流必须校验租户
        status, foreign = call(
            base, f"/api/v1/workflows/{wf['id']}", headers={"X-Tenant-Id": tenant_b}
        )
        self.assertEqual(status, 404, foreign)

    # ------------------------------------------------------------ rag（需 PostgreSQL + pgvector）
    def test_rag_knowledge_base_and_document(self):
        base = self.base("rag")
        tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())

        status, kb = call(
            base,
            "/api/v1/knowledge-bases",
            "POST",
            body={"name": f"smoke-kb-{uuid.uuid4().hex[:6]}", "description": "冒烟测试知识库"},
            headers={"X-Tenant-Id": tenant_a},
        )
        self.assertEqual(status, 201, kb)
        self.assertEqual(kb["tenant_id"], tenant_a)

        status, kbs = call(base, "/api/v1/knowledge-bases", headers={"X-Tenant-Id": tenant_a})
        self.assertEqual(status, 200, kbs)
        self.assertIn(kb["id"], [item["id"] for item in kbs])

        status, other = call(base, "/api/v1/knowledge-bases", headers={"X-Tenant-Id": tenant_b})
        self.assertEqual(status, 200, other)
        self.assertNotIn(kb["id"], [item["id"] for item in other])

        status, fetched = call(base, f"/api/v1/knowledge-bases/{kb['id']}", headers={"X-Tenant-Id": tenant_a})
        self.assertEqual(status, 200, fetched)

        status, patched = call(
            base,
            f"/api/v1/knowledge-bases/{kb['id']}",
            "PATCH",
            body={"description": "冒烟测试已更新"},
            headers={"X-Tenant-Id": tenant_a},
        )
        self.assertEqual(status, 200, patched)
        self.assertEqual(patched["description"], "冒烟测试已更新")

        status, doc = call(
            base,
            "/api/v1/documents",
            "POST",
            body={
                "filename": "smoke.txt",
                "original_filename": "smoke.txt",
                "content_type": "text/plain",
                "file_size": 12,
                "file_hash": uuid.uuid4().hex,
                "knowledge_base_id": kb["id"],
            },
            headers={"X-Tenant-Id": tenant_a},
        )
        self.assertEqual(status, 201, doc)
        self.assertEqual(doc["knowledge_base_id"], kb["id"])

        status, docs = call(base, f"/api/v1/documents?kb_id={kb['id']}", headers={"X-Tenant-Id": tenant_a})
        self.assertEqual(status, 200, docs)
        self.assertIn(doc["id"], [item["id"] for item in docs])

    def test_rag_process_and_retrieval(self):
        """分块 → 嵌入 → 写入 document_chunks → 向量检索，全链路。"""
        base = self.base("rag")
        tenant = str(uuid.uuid4())
        headers = {"X-Tenant-Id": tenant}
        text = (
            "差旅报销制度：员工出差需提前提交申请，经济舱机票与高铁二等座可全额报销。"
            "住宿标准：一线城市每晚不超过600元，其他城市不超过400元。\n"
            "年假政策：入职满一年享有5天带薪年假，满三年10天，满五年15天。\n"
        )

        status, kb = call(
            base,
            "/api/v1/knowledge-bases",
            "POST",
            body={
                "name": f"smoke-rag-{uuid.uuid4().hex[:6]}",
                "embedding_model": os.getenv("RAG_EMBEDDING_MODEL", "embeddinggemma:300m"),
                "embedding_dim": int(os.getenv("RAG_EMBEDDING_DIM", "768")),
                "chunk_size": 120,
                "chunk_overlap": 20,
            },
            headers=headers,
        )
        self.assertEqual(status, 201, kb)

        status, doc = call(
            base,
            "/api/v1/documents",
            "POST",
            body={
                "filename": "handbook.txt",
                "original_filename": "员工手册.txt",
                "content_type": "text/plain",
                "file_size": len(text.encode()),
                "file_hash": uuid.uuid4().hex,
                "knowledge_base_id": kb["id"],
                "metadata": {"text": text},
            },
            headers=headers,
        )
        self.assertEqual(status, 201, doc)

        status, proc = call(base, f"/api/v1/documents/{doc['id']}/process", "POST", headers=headers)
        if status >= 500:
            self.skipTest(f"embedding 不可用，跳过检索链路：{proc}")
        self.assertEqual(status, 200, proc)
        self.assertEqual(proc["status"], "completed")
        self.assertGreater(proc["chunks_created"], 0)

        status, chunks = call(base, f"/api/v1/documents/{doc['id']}/chunks", headers=headers)
        self.assertEqual(status, 200, chunks)
        self.assertGreater(len(chunks), 0)

        status, res = call(
            base,
            "/api/v1/retrieval/search",
            "POST",
            body={"query": "出差住宿能报销多少", "knowledge_base_id": kb["id"], "use_rerank": False},
            headers=headers,
        )
        self.assertEqual(status, 200, res)
        self.assertGreater(res["total_found"], 0)
        self.assertIn("住宿", res["chunks"][0]["content"])

    def test_document_upload_download_process(self):
        """presigned 上传 → 完成入库 → 下载校验字节 → 解析。"""
        base = self.base("document")
        tenant = str(uuid.uuid4())
        headers = {"X-Tenant-Id": tenant}
        payload = (
            "上传链路冒烟测试。\n第一段：远程办公每周三可申请。\n"
            f"第二段：住宿一线城市600元。运行标记 {uuid.uuid4().hex[:8]}\n"
        ).encode()
        digest = hashlib.sha256(payload).hexdigest()

        status, presign = call(
            base,
            "/api/v1/upload/presigned-url",
            "POST",
            body={
                "filename": "smoke-upload.txt",
                "content_type": "text/plain",
                "file_size": len(payload),
                "file_hash": digest,
            },
            headers=headers,
        )
        self.assertEqual(status, 200, presign)

        put = urllib.request.Request(presign["upload_url"], data=payload, method="PUT")
        put.add_header("Content-Type", "text/plain")
        try:
            with urllib.request.urlopen(put, timeout=20) as resp:
                self.assertIn(resp.status, (200, 204))
        except urllib.error.URLError as exc:
            self.skipTest(f"对象存储不可达（可能用的是 MinIO 且未启动）：{exc}")

        form = urllib.parse.urlencode(
            {
                "object_key": presign["object_key"],
                "filename": "smoke-upload.txt",
                "content_type": "text/plain",
                "file_size": len(payload),
                "file_hash": digest,
            }
        ).encode()
        req = urllib.request.Request(base + "/api/v1/upload/complete", data=form, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        req.add_header("X-Tenant-Id", tenant)
        # 配置 SERVICE_API_KEY 后 /api/v1/* 必须带服务间签名（网关就是这么转发的）
        for key, value in signature_headers("POST", "/api/v1/upload/complete", {"X-Tenant-Id": tenant}).items():
            req.add_header(key, value)
        with urllib.request.urlopen(req, timeout=20) as resp:
            completed = json.loads(resp.read().decode())
        doc_id = completed.get("document_id") or completed.get("id")
        self.assertIsNotNone(doc_id, completed)

        dl_path = f"/api/v1/download/{doc_id}"
        dl = urllib.request.Request(base + dl_path)
        dl.add_header("X-Tenant-Id", tenant)
        for key, value in signature_headers("GET", dl_path, headers).items():
            dl.add_header(key, value)
        with urllib.request.urlopen(dl, timeout=20) as resp:
            self.assertEqual(resp.read(), payload)

        status, proc = call(base, f"/api/v1/documents/{doc_id}/process", "POST", headers=headers)
        self.assertEqual(status, 200, proc)
        self.assertEqual(proc["page_count"], 1)

        status, detail = call(base, f"/api/v1/documents/{doc_id}", headers=headers)
        self.assertEqual(status, 200, detail)
        self.assertEqual(detail["status"], "processed")
        self.assertIn("远程办公", detail["metadata"].get("text", ""))


    # ------------------------------------------------------------ 上传即入库 / 错误映射
    def _new_kb(self, base: str, headers: dict, prefix: str) -> dict:
        status, kb = call(
            base,
            "/api/v1/knowledge-bases",
            "POST",
            body={
                "name": f"{prefix}-{uuid.uuid4().hex[:6]}",
                "embedding_model": os.getenv("RAG_EMBEDDING_MODEL", "embeddinggemma:300m"),
                "embedding_dim": int(os.getenv("RAG_EMBEDDING_DIM", "768")),
                "chunk_size": 120,
                "chunk_overlap": 20,
            },
            headers=headers,
        )
        self.assertEqual(status, 201, kb)
        return kb

    def test_rag_ingest_is_one_step_and_idempotent(self):
        """POST /documents/ingest：登记 + 分块 + 嵌入 + BM25 刷新一步完成；同一 file_hash 复用文档。"""
        base = self.base("rag")
        tenant = str(uuid.uuid4())
        headers = {"X-Tenant-Id": tenant}
        kb = self._new_kb(base, headers, "smoke-ingest")
        nl = chr(10)
        text = (
            "差旅报销制度：一线城市住宿每晚 600 元，其他城市每晚 400 元，凭发票据实报销。"
            + nl
            + "年假制度：入职满一年 5 天带薪年假，满三年 10 天，满五年 15 天。"
            + nl
        )
        body = {"knowledge_base_id": kb["id"], "title": "policy.txt", "text": text}

        status, ing = call(base, "/api/v1/documents/ingest", "POST", body=body, headers=headers)
        if status == 503:
            self.skipTest(f"embedding 不可用，跳过入库链路：{ing}")
        self.assertEqual(status, 201, ing)
        self.assertGreater(ing["chunks_created"], 0)
        self.assertFalse(ing["reused_existing"])

        status, again = call(base, "/api/v1/documents/ingest", "POST", body=body, headers=headers)
        self.assertEqual(status, 201, again)
        self.assertEqual(again["document_id"], ing["document_id"])
        self.assertTrue(again["reused_existing"])

        status, res = call(
            base,
            "/api/v1/retrieval/search",
            "POST",
            body={"query": "住宿报销标准", "knowledge_base_id": kb["id"], "use_rerank": False},
            headers=headers,
        )
        self.assertEqual(status, 200, res)
        self.assertGreater(res["total_found"], 0)
        self.assertFalse(res["degraded"])

    def test_rag_embedding_failure_is_503_with_readable_reason(self):
        """embedding 依赖不可用时必须是 503 + 可读文案，而不是 200 空结果或 500。"""
        base = self.base("rag")
        headers = {"X-Tenant-Id": str(uuid.uuid4())}

        status, payload = call(
            base,
            "/api/v1/embeddings",
            "POST",
            body={"texts": ["hello"], "model": "no-such-embedding-model:0b"},
            headers=headers,
        )
        self.assertEqual(status, 503, payload)
        self.assertIn("Embedding 服务不可用", payload["detail"])
        self.assertIn("EMBEDDING_API", payload["detail"])

        status, kb = call(
            base,
            "/api/v1/knowledge-bases",
            "POST",
            body={
                "name": f"smoke-bad-{uuid.uuid4().hex[:6]}",
                "embedding_model": "no-such-embedding-model:0b",
                "embedding_dim": 768,
            },
            headers=headers,
        )
        self.assertEqual(status, 201, kb)
        status, payload = call(
            base,
            "/api/v1/documents/ingest",
            "POST",
            body={"knowledge_base_id": kb["id"], "title": "bad.txt", "text": "触发 embedding 失败"},
            headers=headers,
        )
        self.assertEqual(status, 503, payload)
        self.assertIn("Embedding 服务不可用", payload["detail"])

    def test_document_parse_auto_ingests_to_rag(self):
        """P1：document-service 解析完自动送 rag，上传后无需手工调 rag 就能检索命中。"""
        doc_base = self.base("document")
        rag_base = self.base("rag")
        headers = {"X-Tenant-Id": str(uuid.uuid4())}
        kb = self._new_kb(rag_base, headers, "smoke-auto")

        marker = uuid.uuid4().hex[:8]
        content = (
            f"远程办公制度：每周三可申请远程办公，需提前一天在系统报备。标记 {marker}"
        ).encode("utf-8")
        status, doc = call_multipart(
            doc_base,
            "/api/v1/upload/multipart",
            fields={"knowledge_base_id": kb["id"]},
            filename="telework.txt",
            content=content,
            headers=headers,
        )
        if status >= 500:
            self.skipTest(f"文档存储不可用，跳过自动入库链路：{doc}")
        self.assertIn(status, (200, 201), doc)

        status, proc = call(doc_base, f"/api/v1/documents/{doc['id']}/process", "POST", headers=headers)
        self.assertEqual(status, 200, proc)
        self.assertTrue(proc.get("rag_ingested"), proc)

        status, res = call(
            rag_base,
            "/api/v1/retrieval/search",
            "POST",
            body={"query": "远程办公 每周三", "knowledge_base_id": kb["id"], "use_rerank": False},
            headers=headers,
        )
        self.assertEqual(status, 200, res)
        self.assertGreater(res["total_found"], 0)
        self.assertIn("远程办公", res["chunks"][0]["content"])

    def test_kb_stats_follow_proxied_documents(self):
        """转发模式下知识库的 document_count 必须是微服务里的真实数字，不是网关旧库的 0。"""
        if not self.running.get("document"):
            self.skipTest("document-service 未启动")
        token = gateway_login()
        if not token:
            self.skipTest(f"网关未启动或登录失败（{GATEWAY_BASE}）")
        status, _, headers = call_full(
            GATEWAY_BASE, "/api/v1/documents", token=token, sign=False
        )
        if headers.get("x-gateway-proxy") != "document-service":
            self.skipTest("网关未开启 GATEWAY_PROXY_DOCUMENTS")

        status, created_kb = call(
            GATEWAY_BASE,
            "/api/v1/knowledge-bases",
            "POST",
            token=token,
            sign=False,
            body={
                "name": f"kb-stats-{uuid.uuid4().hex[:6]}",
                "description": "转发统计验证",
                "visibility": "TENANT",
            },
        )
        self.assertEqual(status, 201, created_kb)
        kb_id = created_kb["data"]["id"]
        doc_id = None

        try:
            status, stats = call(
                GATEWAY_BASE,
                f"/api/v1/knowledge-bases/{kb_id}/stats",
                token=token,
                sign=False,
            )
            self.assertEqual(status, 200, stats)
            self.assertEqual(stats["data"]["document_count"], 0, stats)

            file_hash = uuid.uuid4().hex
            # 通过网关建一篇文档到该知识库（写进 document-service 的库）
            status, created = call(
                GATEWAY_BASE,
                "/api/v1/documents",
                "POST",
                token=token,
                sign=False,
                body={
                    "knowledge_base_id": kb_id,
                    "title": "kb-stats.txt",
                    "type": "TXT",
                    "file_name": "kb-stats.txt",
                    "file_size": 16,
                    "mime_type": "text/plain",
                    "metadata": {"file_hash": file_hash},
                },
            )
            self.assertEqual(status, 201, created)
            doc_id = created["data"]["id"]

            status, stats = call(
                GATEWAY_BASE,
                f"/api/v1/knowledge-bases/{kb_id}/stats",
                token=token,
                sign=False,
            )
            self.assertEqual(status, 200, stats)
            self.assertEqual(stats["data"]["document_count"], 1, stats)
            self.assertIn(
                doc_id, [item["id"] for item in stats["data"]["recent_documents"]], stats
            )

            # 列表项与详情同样要反映真实计数（网关本地表仍是 0）
            status, listed = call(
                GATEWAY_BASE, "/api/v1/knowledge-bases?page_size=50", token=token, sign=False
            )
            self.assertEqual(status, 200, listed)
            item = next(
                (i for i in listed["data"]["items"] if i["id"] == kb_id), None
            )
            self.assertIsNotNone(item, listed)
            self.assertEqual(item["document_count"], 1, item)

            status, detail = call(
                GATEWAY_BASE, f"/api/v1/knowledge-bases/{kb_id}", token=token, sign=False
            )
            self.assertEqual(status, 200, detail)
            self.assertEqual(detail["data"]["document_count"], 1, detail)

            # 删除后再登记同内容文件：唯一约束含软删除记录，必须复活而不是 500
            status, deleted = call(
                GATEWAY_BASE,
                f"/api/v1/documents/{doc_id}",
                "DELETE",
                token=token,
                sign=False,
            )
            self.assertEqual(status, 200, deleted)
            status, revived = call(
                GATEWAY_BASE,
                "/api/v1/documents",
                "POST",
                token=token,
                sign=False,
                body={
                    "knowledge_base_id": kb_id,
                    "title": "kb-stats.txt",
                    "type": "TXT",
                    "file_name": "kb-stats.txt",
                    "file_size": 16,
                    "mime_type": "text/plain",
                    "metadata": {"file_hash": file_hash},
                },
            )
            self.assertEqual(status, 201, revived)
            # 同一条记录被复活（不能插入：唯一约束包含软删除行），ID 不变
            self.assertEqual(revived["data"]["id"], doc_id, revived)
            doc_id = revived["data"]["id"]
        finally:
            if doc_id:
                call(
                    GATEWAY_BASE,
                    f"/api/v1/documents/{doc_id}",
                    "DELETE",
                    token=token,
                    sign=False,
                )
            call(
                GATEWAY_BASE,
                f"/api/v1/knowledge-bases/{kb_id}",
                "DELETE",
                token=token,
                sign=False,
            )

    def test_proxy_enforces_gateway_rbac(self):
        """转发不能绕开网关 RBAC：VIEWER 能读文档，但不能创建/删除文档或创建工作流。"""
        if not self.running.get("document"):
            self.skipTest("document-service 未启动")
        admin = gateway_login()
        if not admin:
            self.skipTest(f"网关未启动或登录失败（{GATEWAY_BASE}）")
        status, _, headers = call_full(
            GATEWAY_BASE, "/api/v1/documents", token=admin, sign=False
        )
        if headers.get("x-gateway-proxy") != "document-service":
            self.skipTest("网关未开启 GATEWAY_PROXY_DOCUMENTS")

        suffix = uuid.uuid4().hex[:8]
        username = f"viewer_{suffix}"
        email = f"{username}@example.com"
        password = "viewer-pass-123"
        status, created = call(
            GATEWAY_BASE,
            "/api/v1/users",
            "POST",
            token=admin,
            sign=False,
            body={
                "email": email,
                "username": username,
                "password": password,
                "display_name": "Proxy RBAC",
                "role": "VIEWER",
            },
        )
        self.assertEqual(status, 201, created)
        user_id = created["data"]["id"]

        try:
            status, login = call(
                GATEWAY_BASE,
                "/api/v1/auth/login",
                "POST",
                body={"email": email, "password": password},
                sign=False,
            )
            self.assertEqual(status, 200, login)
            viewer = login["data"]["access_token"]

            # 读：VIEWER 有 document:read
            status, listed = call(
                GATEWAY_BASE, "/api/v1/documents", token=viewer, sign=False
            )
            self.assertEqual(status, 200, listed)

            # 写：必须被网关拦下，而不是直接转发给微服务
            status, denied = call(
                GATEWAY_BASE,
                "/api/v1/documents",
                "POST",
                token=viewer,
                sign=False,
                body={
                    "knowledge_base_id": str(uuid.uuid4()),
                    "title": "rbac-should-fail.txt",
                    "type": "TXT",
                    "file_name": "rbac-should-fail.txt",
                    "file_size": 1,
                    "mime_type": "text/plain",
                },
            )
            self.assertEqual(status, 403, denied)
            self.assertIn("document:create", denied["detail"])

            status, denied = call(
                GATEWAY_BASE,
                f"/api/v1/documents/{uuid.uuid4()}",
                "DELETE",
                token=viewer,
                sign=False,
            )
            self.assertEqual(status, 403, denied)
            self.assertIn("document:delete", denied["detail"])

            # 工作流转发开着时同样受 RBAC 约束
            status, _, wf_headers = call_full(
                GATEWAY_BASE, "/api/v1/workflows", token=admin, sign=False
            )
            if wf_headers.get("x-gateway-proxy") == "workflow-service":
                status, denied = call(
                    GATEWAY_BASE,
                    "/api/v1/workflows",
                    "POST",
                    token=viewer,
                    sign=False,
                    body={"name": "rbac-should-fail", "definition": {"nodes": [], "edges": []}},
                )
                self.assertEqual(status, 403, denied)
                self.assertIn("workflow:create", denied["detail"])
        finally:
            call(
                GATEWAY_BASE,
                f"/api/v1/users/{user_id}",
                "DELETE",
                token=admin,
                sign=False,
            )

    def test_gateway_forwards_notifications(self):
        """网关 → notification-service：UUID 契约、信封分页、已读/未读数、删除。

        需要网关以 GATEWAY_PROXY_NOTIFICATIONS=true + SERVICE_API_KEY 启动，且 notification-service 在跑。
        第 16 轮把通知列为「不可拆」（int 主键 vs UUID），第 26 轮对齐契约后才打通；
        这条用例同时盯住那个回归：返回的 id 必须是 UUID。
        """
        if not self.running.get("notification"):
            self.skipTest("notification-service 未启动")
        token = gateway_login()
        if not token:
            self.skipTest(f"网关未启动或登录失败（{GATEWAY_BASE}）")

        status, listed, headers = call_full(
            GATEWAY_BASE, "/api/v1/notifications", token=token, sign=False
        )
        self.assertEqual(status, 200, listed)
        if headers.get("x-gateway-proxy") != "notification-service":
            self.skipTest("网关未开启 GATEWAY_PROXY_NOTIFICATIONS")
        self.assertTrue(listed["success"], listed)
        for key in ("items", "total", "page", "page_size", "total_pages"):
            self.assertIn(key, listed["data"], listed)
        before = listed["data"]["total"]

        title = f"网关转发通知-{uuid.uuid4().hex[:8]}"
        status, created = call(
            GATEWAY_BASE,
            "/api/v1/notifications",
            "POST",
            token=token,
            sign=False,
            body={"title": title, "content": "通过网关创建", "type": "INFO", "channel": "IN_APP"},
        )
        self.assertEqual(status, 201, created)
        notif = created["data"]
        self.assertEqual(notif["title"], title)
        self.assertFalse(notif["read"])
        # 契约：id 必须是 UUID，不能是自增整数
        self.assertEqual(str(uuid.UUID(notif["id"])), notif["id"])

        status, unread = call(
            GATEWAY_BASE, "/api/v1/notifications/unread-count", token=token, sign=False
        )
        self.assertEqual(status, 200, unread)
        self.assertGreaterEqual(unread["data"]["unread_count"], 1)

        status, read = call(
            GATEWAY_BASE,
            f"/api/v1/notifications/{notif['id']}/read",
            "PATCH",
            token=token,
            sign=False,
        )
        self.assertEqual(status, 200, read)
        self.assertTrue(read["data"]["read"])
        self.assertEqual(read["data"]["id"], notif["id"])

        status, listed2 = call(GATEWAY_BASE, "/api/v1/notifications", token=token, sign=False)
        self.assertEqual(listed2["data"]["total"], before + 1)

        status, deleted = call(
            GATEWAY_BASE,
            f"/api/v1/notifications/{notif['id']}",
            "DELETE",
            token=token,
            sign=False,
        )
        self.assertEqual(status, 200, deleted)
        status, listed3 = call(GATEWAY_BASE, "/api/v1/notifications", token=token, sign=False)
        self.assertEqual(listed3["data"]["total"], before)

    def test_gateway_forwards_workflows(self):
        """网关 → workflow-service：图结构双向转换、信封分页、发布状态。

        需要网关以 GATEWAY_PROXY_WORKFLOWS=true + SERVICE_API_KEY 启动，且 workflow-service 在跑。
        发布后的工作流在微服务侧不能删/不能改（状态机如此），因此用例会保留一条随机名字的数据。
        """
        if not self.running.get("workflow"):
            self.skipTest("workflow-service 未启动")
        token = gateway_login()
        if not token:
            self.skipTest(f"网关未启动或登录失败（{GATEWAY_BASE}）")

        status, listed, headers = call_full(
            GATEWAY_BASE, "/api/v1/workflows", token=token, sign=False
        )
        self.assertEqual(status, 200, listed)
        if headers.get("x-gateway-proxy") != "workflow-service":
            self.skipTest("网关未开启 GATEWAY_PROXY_WORKFLOWS")
        self.assertTrue(listed["success"], listed)
        for key in ("items", "total", "page", "page_size", "total_pages"):
            self.assertIn(key, listed["data"], listed)

        definition = {
            "nodes": [
                {
                    "id": "start",
                    "type": "START",
                    "name": "开始",
                    "position": {"x": 0, "y": 0},
                    "config": {},
                    "inputs": [],
                    "outputs": [
                        {"id": "out", "name": "out", "type": "string", "required": False}
                    ],
                },
                {
                    "id": "end",
                    "type": "END",
                    "name": "结束",
                    "position": {"x": 220, "y": 0},
                    "config": {},
                    "inputs": [
                        {"id": "in", "name": "in", "type": "string", "required": False}
                    ],
                    "outputs": [],
                },
            ],
            "edges": [
                {
                    "id": "e1",
                    "source_node_id": "start",
                    "source_port_id": "out",
                    "target_node_id": "end",
                    "target_port_id": "in",
                }
            ],
            "variables": [],
        }

        status, created = call(
            GATEWAY_BASE,
            "/api/v1/workflows",
            "POST",
            token=token,
            sign=False,
            body={
                "name": f"proxy-wf-{uuid.uuid4().hex[:6]}",
                "description": "转发冒烟",
                "definition": definition,
            },
        )
        self.assertEqual(status, 201, created)
        self.assertTrue(created["success"], created)
        wf = created["data"]
        self.assertEqual(wf["status"], "DRAFT")
        # 微服务的 source/target 要能还原成网关的 source_node_id/target_node_id
        self.assertEqual(wf["definition"]["edges"][0]["source_node_id"], "start")
        self.assertEqual(wf["definition"]["nodes"][0]["type"], "START")
        self.assertEqual(wf["definition"]["nodes"][0]["name"], "开始")

        status, validated = call(
            GATEWAY_BASE,
            "/api/v1/workflows/validate",
            "POST",
            token=token,
            sign=False,
            body={"definition": definition},
        )
        self.assertEqual(status, 200, validated)
        self.assertTrue(validated["data"]["valid"], validated)

        status, fetched = call(
            GATEWAY_BASE, f"/api/v1/workflows/{wf['id']}", token=token, sign=False
        )
        self.assertEqual(status, 200, fetched)
        self.assertEqual(fetched["data"]["id"], wf["id"])

        status, published = call(
            GATEWAY_BASE,
            f"/api/v1/workflows/{wf['id']}/publish",
            "POST",
            token=token,
            sign=False,
            body={},
        )
        self.assertEqual(status, 200, published)
        self.assertEqual(published["data"]["status"], "PUBLISHED")

        # 微服务没有 unpublish：转发模式必须明确 501，而不是假装成功
        status, unsupported = call(
            GATEWAY_BASE,
            f"/api/v1/workflows/{wf['id']}/unpublish",
            "POST",
            token=token,
            sign=False,
            body={},
        )
        self.assertEqual(status, 501, unsupported)

        # 执行真的跑完（微服务侧同步执行）→ 网关自动写一条「工作流执行完成」通知（第 28 轮）
        status, executed = call(
            GATEWAY_BASE,
            f"/api/v1/workflows/{wf['id']}/execute",
            "POST",
            token=token,
            sign=False,
            body={"input_data": {}},
        )
        self.assertEqual(status, 200, executed)
        self.assertIn(executed["data"]["status"].lower(), {"completed", "failed", "pending", "running"})

        status, notifs = call(
            GATEWAY_BASE, "/api/v1/notifications?page=1&page_size=20", token=token, sign=False
        )
        if status == 200:
            body = notifs.get("data") or {}
            items = body.get("items", []) if isinstance(body, dict) else body
            matched = [n for n in items if (n.get("data") or {}).get("workflow_id") == wf["id"]]
            self.assertTrue(matched, f"执行后没有生成通知：{[n.get('title') for n in items[:5]]}")
            self.assertEqual(matched[0]["type"], "SUCCESS")

    def test_gateway_forwards_documents_with_jwt_identity(self):
        """网关 → document-service：JWT 身份被换成签名头，文档真的落在微服务那一侧。

        需要网关以 GATEWAY_PROXY_DOCUMENTS=true + SERVICE_API_KEY 启动；
        没开转发时没有 X-Gateway-Proxy 响应头，本用例自动跳过。
        同时验证契约对齐：转发回来仍是 {success, data} 信封 + 网关字段名。
        """
        if not self.running.get("document"):
            self.skipTest("document-service 未启动")
        try:
            urllib.request.urlopen(GATEWAY_BASE + "/health", timeout=5)
        except Exception:
            self.skipTest(f"网关未启动（{GATEWAY_BASE}）")

        status, login = call(
            GATEWAY_BASE,
            "/api/v1/auth/login",
            "POST",
            body={"email": "admin@example.com", "password": "admin123"},
            sign=False,
        )
        if status != 200:
            self.skipTest(f"网关登录失败，无法验证转发：{login}")
        # 网关登录是 {success, data} 信封；微服务则是裸对象
        login_data = login.get("data", login) if isinstance(login, dict) else login
        token = login_data["access_token"]

        status, listed, headers = call_full(
            GATEWAY_BASE, "/api/v1/documents", token=token, sign=False
        )
        self.assertEqual(status, 200, listed)
        if headers.get("x-gateway-proxy") != "document-service":
            self.skipTest("网关未开启 GATEWAY_PROXY_DOCUMENTS")

        # 契约：仍是网关信封 + 分页对象
        self.assertTrue(listed["success"], listed)
        page = listed["data"]
        for key in ("items", "total", "page", "page_size", "total_pages"):
            self.assertIn(key, page, listed)

        # 从 JWT 里取租户，断言微服务收到的确实是登录用户的租户
        payload_b64 = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)))
        digest = uuid.uuid4().hex
        status, created = call(
            GATEWAY_BASE,
            "/api/v1/documents",
            "POST",
            token=token,
            sign=False,
            body={
                "knowledge_base_id": str(uuid.uuid4()),
                "title": "gateway-proxy.txt",
                "type": "TXT",
                "file_name": "gateway-proxy.txt",
                "file_size": 12,
                "mime_type": "text/plain",
                "metadata": {"file_hash": digest},
            },
        )
        self.assertEqual(status, 201, created)
        self.assertTrue(created["success"], created)
        doc = created["data"]
        self.assertEqual(doc["tenant_id"], claims["tenant_id"])
        # 字段映射：微服务 filename / document_type / content_type → 网关 file_name / type / mime_type
        self.assertEqual(doc["file_name"], "gateway-proxy.txt")
        self.assertEqual(doc["type"], "TXT")
        self.assertEqual(doc["mime_type"], "text/plain")

        # 同一个租户直连微服务能查到 → 文档确实写进了 document-service
        status, direct, direct_headers = call_full(
            SERVICES["document"],
            "/api/v1/documents",
            headers={"X-Tenant-Id": claims["tenant_id"]},
        )
        self.assertEqual(status, 200, direct)
        self.assertIn(doc["id"], [item["id"] for item in direct])
        self.assertGreaterEqual(int(direct_headers.get("x-total-count", "0")), 1)

        # 详情 / 删除也走网关契约
        status, fetched = call(
            GATEWAY_BASE, f"/api/v1/documents/{doc['id']}", token=token, sign=False
        )
        self.assertEqual(status, 200, fetched)
        self.assertEqual(fetched["data"]["id"], doc["id"])

        status, deleted = call(
            GATEWAY_BASE,
            f"/api/v1/documents/{doc['id']}",
            "DELETE",
            token=token,
            sign=False,
        )
        self.assertEqual(status, 200, deleted)
        self.assertTrue(deleted["success"], deleted)

        status, after = call(
            GATEWAY_BASE,
            "/api/v1/documents",
            token=token,
            sign=False,
        )
        self.assertEqual(status, 200, after)
        self.assertNotIn(doc["id"], [item["id"] for item in after["data"]["items"]])

        # 网关的上传路径 /documents/upload 也要能落到微服务的 /upload/multipart
        # 用 ~700KB 正文走一遍，确认请求体是流式转发而不是在网关里整块缓冲
        upload_content = (
            "网关上传适配验证：" + "远程办公每周三可申请。" * 20000 + uuid.uuid4().hex
        ).encode("utf-8")
        status, uploaded = call_multipart(
            GATEWAY_BASE,
            "/api/v1/documents/upload",
            fields={"knowledge_base_id": str(uuid.uuid4()), "title": "via-gateway.txt"},
            filename="via-gateway.txt",
            content=upload_content,
            token=token,
        )
        self.assertEqual(status, 201, uploaded)
        self.assertTrue(uploaded["success"], uploaded)
        self.assertEqual(uploaded["data"]["file_name"], "via-gateway.txt")
        file_id = uploaded["data"]["file_id"]
        self.assertTrue(file_id)

        # 下载走 /documents/{id}/download → 微服务 /download/{id}，字节要完全一致
        download_req = urllib.request.Request(
            GATEWAY_BASE + f"/api/v1/documents/{file_id}/download"
        )
        download_req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(download_req, timeout=30) as resp:
            self.assertEqual(resp.read(), upload_content)

        call(
            GATEWAY_BASE,
            f"/api/v1/documents/{file_id}",
            "DELETE",
            token=token,
            sign=False,
        )

    def test_presigned_complete_auto_processes_and_ingests(self):
        """预签名链路：/upload/complete 之后不再需要手动 /process，解析与入库一次完成。"""
        doc_base = self.base("document")
        rag_base = self.base("rag")
        headers = {"X-Tenant-Id": str(uuid.uuid4())}
        kb = self._new_kb(rag_base, headers, "smoke-presigned")

        marker = uuid.uuid4().hex[:8]
        payload = (
            f"远程办公制度：每周五下午可以申请远程办公，需提前报备。预签名标记 {marker}"
        ).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()

        status, presign = call(
            doc_base,
            "/api/v1/upload/presigned-url",
            "POST",
            body={
                "filename": "presigned.txt",
                "content_type": "text/plain",
                "file_size": len(payload),
                "file_hash": digest,
            },
            headers=headers,
        )
        self.assertEqual(status, 200, presign)

        put = urllib.request.Request(presign["upload_url"], data=payload, method="PUT")
        put.add_header("Content-Type", "text/plain")
        try:
            with urllib.request.urlopen(put, timeout=20) as resp:
                self.assertIn(resp.status, (200, 204))
        except urllib.error.URLError as exc:
            self.skipTest(f"对象存储不可达：{exc}")

        form = urllib.parse.urlencode(
            {
                "object_key": presign["object_key"],
                "filename": "presigned.txt",
                "content_type": "text/plain",
                "file_size": len(payload),
                "file_hash": digest,
                "knowledge_base_id": kb["id"],
            }
        ).encode()
        req = urllib.request.Request(doc_base + "/api/v1/upload/complete", data=form, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        for key, value in headers.items():
            req.add_header(key, value)
        for key, value in signature_headers("POST", "/api/v1/upload/complete", headers).items():
            req.add_header(key, value)
        with urllib.request.urlopen(req, timeout=30) as resp:
            completed = json.loads(resp.read().decode())

        self.assertTrue(completed.get("processed"), completed)
        self.assertEqual(completed.get("document_status"), "processed", completed)
        self.assertTrue(completed.get("rag_ingested"), completed)

        status, res = call(
            rag_base,
            "/api/v1/retrieval/search",
            "POST",
            body={"query": "远程办公 周五", "knowledge_base_id": kb["id"], "use_rerank": False},
            headers=headers,
        )
        self.assertEqual(status, 200, res)
        self.assertGreater(res["total_found"], 0)
        self.assertIn("远程办公", res["chunks"][0]["content"])


if __name__ == "__main__":
    status = probe()
    for name, up in status.items():
        print(f"  {name:<13} {'UP' if up else 'down':<5} {SERVICES[name]}")
    if not any(status.values()):
        print("没有微服务在运行，跳过。启动方式见 docs/runbooks/local-dev.md")
        sys.exit(2)
    unittest.main(verbosity=2)
