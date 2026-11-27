"""
API 网关冒烟测试。

用法（网关需先启动）：
    python tests/test_gateway_smoke.py
    BASE=http://127.0.0.1:8000/api/v1 python tests/test_gateway_smoke.py

只依赖标准库，覆盖：健康检查、认证、用户/租户/模型/审计/成本读接口，
以及"无 token 401""非管理员改模型 403"两条权限边界。
"""

import json
import os
import sys
import unittest
import urllib.error
import urllib.request
import uuid

BASE = os.getenv("BASE", "http://127.0.0.1:8000/api/v1")
ROOT = BASE.rsplit("/api/v1", 1)[0]
ADMIN = {"email": os.getenv("ADMIN_EMAIL", "admin@example.com"),
         "password": os.getenv("ADMIN_PASSWORD", "admin123")}


def call(path: str, method: str = "GET", token: str | None = None, body: dict | None = None):
    """返回 (status, payload)。payload 解析失败时返回原始文本。"""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, _parse(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        return exc.code, _parse(raw)


CR = chr(13)
LF = chr(10)
CRLF = CR + LF


def upload(path: str, token: str, fields: dict, filename: str, content: str):
    """手搓 multipart/form-data（只依赖标准库），返回 (status, payload)。"""
    boundary = "----smoke" + uuid.uuid4().hex
    chunks = []
    for name, value in fields.items():
        head = f'--{boundary}{CRLF}Content-Disposition: form-data; name="{name}"{CRLF}{CRLF}'
        chunks.append((head + str(value) + CRLF).encode("utf-8"))
    file_head = (
        f'--{boundary}{CRLF}Content-Disposition: form-data; name="file"; '
        f'filename="{filename}"{CRLF}Content-Type: text/plain{CRLF}{CRLF}'
    )
    chunks.append(file_head.encode("utf-8") + content.encode("utf-8") + CRLF.encode("utf-8"))
    chunks.append(f"--{boundary}--{CRLF}".encode("utf-8"))

    req = urllib.request.Request(BASE + path, data=b"".join(chunks), method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
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


class GatewaySmokeTest(unittest.TestCase):
    token: str | None = None

    @classmethod
    def setUpClass(cls):
        status, payload = call("/auth/login", "POST", body=ADMIN)
        if status != 200:
            raise unittest.SkipTest(f"网关未就绪或演示账号不可用：{status} {payload}")
        cls.token = payload["data"]["access_token"]

    # ------------------------------------------------------------ 基础
    def test_health(self):
        with urllib.request.urlopen(ROOT + "/health", timeout=10) as resp:
            self.assertEqual(resp.status, 200)

    def test_openapi_parses(self):
        with urllib.request.urlopen(BASE + "/openapi.json", timeout=10) as resp:
            schema = json.loads(resp.read().decode("utf-8"))
        self.assertIn("/api/v1/auth/login", schema["paths"])

    def test_requires_token(self):
        status, _ = call("/users")
        self.assertEqual(status, 401)

    def test_bad_password_rejected(self):
        status, _ = call("/auth/login", "POST", body={"email": ADMIN["email"], "password": "wrong-pass"})
        self.assertEqual(status, 401)

    # ------------------------------------------------------------ 读接口
    def test_me(self):
        status, payload = call("/auth/me", token=self.token)
        self.assertEqual(status, 200)
        me = payload["data"].get("user", payload["data"])
        self.assertEqual(me["email"], ADMIN["email"])

    def test_users_list(self):
        status, payload = call("/users?page=1&page_size=100", token=self.token)
        self.assertEqual(status, 200)
        self.assertGreaterEqual(payload["data"]["total"], 1)

    def test_tenants_list(self):
        status, payload = call("/tenants", token=self.token)
        self.assertEqual(status, 200)
        self.assertIsInstance(payload["data"], (list, dict))

    def test_models_list(self):
        status, payload = call("/models?enabled_only=false", token=self.token)
        self.assertEqual(status, 200)
        self.assertIsInstance(payload["data"], list)

    def test_models_update_requires_admin_role(self):
        # 用一个不存在的模型 ID：管理员会拿到 404，说明角色检查已通过
        status, _ = call("/models/does-not-exist", "PATCH", token=self.token, body={"enabled": True})
        self.assertEqual(status, 404)

    def test_audit_logs(self):
        status, payload = call("/audit-logs?page=1&page_size=20", token=self.token)
        self.assertEqual(status, 200)
        self.assertIn("items", payload["data"])

    def test_cost_summary(self):
        status, payload = call("/costs/summary", token=self.token)
        self.assertEqual(status, 200)
        self.assertIn("total_cost", payload["data"])

    def test_token_budget(self):
        status, payload = call("/costs/budget", token=self.token)
        self.assertEqual(status, 200)
        self.assertIn("limit", payload["data"])

    def test_validation_error_is_422(self):
        status, _ = call("/users", "POST", token=self.token, body={"email": "not-an-email"})
        self.assertEqual(status, 422)

    def test_upload_creates_notification(self):
        """上传 .txt → 解析完成 → 自动写一条站内通知（第 28 轮）。"""
        status, payload = call("/knowledge-bases?page=1&page_size=1", token=self.token)
        self.assertEqual(status, 200, payload)
        items = payload["data"]["items"]
        if not items:
            self.skipTest("没有知识库可用于上传")

        filename = f"smoke-notify-{uuid.uuid4().hex[:8]}.txt"
        status, payload = upload(
            "/documents/upload",
            self.token,
            {"knowledge_base_id": items[0]["id"]},
            filename,
            "冒烟测试：这条通知应该由「解析完成」事件自动写入。" * 10,
        )
        self.assertEqual(status, 201, payload)
        doc_id = payload["data"]["file_id"]

        status, payload = call("/notifications?page=1&page_size=20", token=self.token)
        self.assertEqual(status, 200, payload)
        matched = [n for n in payload["data"]["items"] if filename in n["title"]]
        self.assertTrue(matched, f"没有找到解析完成通知：{payload['data']['items']}")
        self.assertIn("解析完成", matched[0]["title"])
        self.assertFalse(matched[0]["read"])
        self.assertEqual(matched[0]["data"]["document_id"], doc_id)

        # 清理：反复本地跑不要污染演示数据
        call(f"/notifications/{matched[0]['id']}", "DELETE", token=self.token)
        call(f"/documents/{doc_id}", "DELETE", token=self.token)


    def test_failed_parse_creates_warning_notification(self):
        """空文件解析失败 → 也写一条「解析失败」通知，而不是静默失败（第 28 轮）。"""
        status, payload = call("/knowledge-bases?page=1&page_size=1", token=self.token)
        self.assertEqual(status, 200, payload)
        items = payload["data"]["items"]
        if not items:
            self.skipTest("没有知识库可用于上传")

        filename = f"smoke-empty-{uuid.uuid4().hex[:8]}.txt"
        status, payload = upload(
            "/documents/upload",
            self.token,
            {"knowledge_base_id": items[0]["id"]},
            filename,
            "",
        )
        self.assertEqual(status, 201, payload)
        doc_id = payload["data"]["file_id"]

        status, payload = call("/notifications?page=1&page_size=20", token=self.token)
        self.assertEqual(status, 200, payload)
        matched = [n for n in payload["data"]["items"] if filename in n["title"]]
        self.assertTrue(matched, f"没有找到解析失败通知：{payload['data']['items']}")
        self.assertIn("解析失败", matched[0]["title"])
        self.assertEqual(matched[0]["type"], "WARNING")

        call(f"/notifications/{matched[0]['id']}", "DELETE", token=self.token)
        call(f"/documents/{doc_id}", "DELETE", token=self.token)


    # ------------------------------------------------------------ 工作流执行器（第 29 轮）
    def _create_published_workflow(self, name: str, definition: dict) -> str:
        status, created = call(
            "/workflows", "POST", token=self.token, body={"name": name, "definition": definition}
        )
        self.assertEqual(status, 201, created)
        wf_id = created["data"]["id"]
        status, published = call(f"/workflows/{wf_id}/publish", "POST", token=self.token, body={})
        self.assertEqual(status, 200, published)
        return wf_id

    def test_workflow_execute_runs_nodes_and_notifies(self):
        """START → END 真的执行完：状态、节点明细、输出、通知都要对（第 29 轮）。"""
        name = f"smoke-exec-{uuid.uuid4().hex[:6]}"
        definition = {
            "nodes": [
                {"id": "start", "type": "START", "name": "开始", "position": {"x": 0, "y": 0}, "config": {}},
                {"id": "end", "type": "END", "name": "结束", "position": {"x": 200, "y": 0}, "config": {}},
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
        wf_id = self._create_published_workflow(name, definition)

        status, executed = call(
            f"/workflows/{wf_id}/execute",
            "POST",
            token=self.token,
            body={"input_data": {"message": "hello"}},
        )
        self.assertEqual(status, 200, executed)
        data = executed["data"]
        self.assertEqual(data["status"], "COMPLETED")
        self.assertIsNotNone(data["completed_at"])
        self.assertEqual([n["node_id"] for n in data["node_executions"]], ["start", "end"])
        self.assertTrue(all(n["status"] == "completed" for n in data["node_executions"]))
        self.assertEqual(data["output"]["output"]["message"], "hello")

        # 执行历史里也能读到节点明细（以前固定是空列表）
        status, history = call(f"/workflows/{wf_id}/executions", token=self.token)
        self.assertEqual(status, 200, history)
        self.assertEqual(len(history["data"]["items"][0]["node_executions"]), 2)

        status, notifs = call("/notifications?page=1&page_size=20", token=self.token)
        matched = [
            n for n in notifs["data"]["items"]
            if (n.get("data") or {}).get("execution_id") == data["id"]
        ]
        self.assertTrue(matched, "执行完成后没有生成通知")
        self.assertEqual(matched[0]["type"], "SUCCESS")
        self.assertIn(name, matched[0]["title"])

        call(f"/notifications/{matched[0]['id']}", "DELETE", token=self.token)
        call(f"/workflows/{wf_id}", "DELETE", token=self.token)

    def test_workflow_execute_rejects_unsupported_nodes(self):
        """条件分支默认模式不支持 → 明确 FAILED + ERROR 通知，而不是假装跑完（第 29–30 轮）。"""
        name = f"smoke-unsupported-{uuid.uuid4().hex[:6]}"
        definition = {
            "nodes": [
                {"id": "start", "type": "START", "name": "开始", "position": {"x": 0, "y": 0}, "config": {}},
                {
                    "id": "branch",
                    "type": "CONDITION",
                    "name": "判断",
                    "position": {"x": 200, "y": 0},
                    "config": {"condition": "{{score}} > 0.5"},
                },
                {"id": "end", "type": "END", "name": "结束", "position": {"x": 400, "y": 0}, "config": {}},
            ],
            "edges": [
                {
                    "id": "e1",
                    "source_node_id": "start",
                    "source_port_id": "out",
                    "target_node_id": "branch",
                    "target_port_id": "in",
                },
                {
                    "id": "e2",
                    "source_node_id": "branch",
                    "source_port_id": "out",
                    "target_node_id": "end",
                    "target_port_id": "in",
                },
            ],
            "variables": [],
        }
        wf_id = self._create_published_workflow(name, definition)

        status, executed = call(
            f"/workflows/{wf_id}/execute", "POST", token=self.token, body={"input_data": {}}
        )
        self.assertEqual(status, 200, executed)
        data = executed["data"]
        self.assertEqual(data["status"], "FAILED")
        self.assertIn("不支持", data["error"])
        self.assertIn("CONDITION", data["error"])
        self.assertEqual(data["node_executions"], [])

        status, notifs = call("/notifications?page=1&page_size=20", token=self.token)
        matched = [
            n for n in notifs["data"]["items"]
            if (n.get("data") or {}).get("execution_id") == data["id"]
        ]
        self.assertTrue(matched, "执行失败后没有生成通知")
        self.assertEqual(matched[0]["type"], "ERROR")

        call(f"/notifications/{matched[0]['id']}", "DELETE", token=self.token)
        call(f"/workflows/{wf_id}", "DELETE", token=self.token)


    def test_workflow_http_node_really_requests(self):
        """HTTP 节点真的发请求：把网关自己的 /health 当目标，结果并进变量（第 29 轮）。"""
        name = f"smoke-http-{uuid.uuid4().hex[:6]}"
        definition = {
            "nodes": [
                {"id": "start", "type": "START", "name": "开始", "position": {"x": 0, "y": 0}, "config": {}},
                {
                    "id": "health",
                    "type": "HTTP",
                    "name": "探活",
                    "position": {"x": 200, "y": 0},
                    "config": {"method": "GET", "url": ROOT + "/health", "headers": {}, "body": {}},
                },
                {"id": "end", "type": "END", "name": "结束", "position": {"x": 400, "y": 0}, "config": {}},
            ],
            "edges": [
                {"id": "e1", "source_node_id": "start", "source_port_id": "out", "target_node_id": "health", "target_port_id": "in"},
                {"id": "e2", "source_node_id": "health", "source_port_id": "out", "target_node_id": "end", "target_port_id": "in"},
            ],
            "variables": [],
        }
        wf_id = self._create_published_workflow(name, definition)

        status, executed = call(
            f"/workflows/{wf_id}/execute", "POST", token=self.token, body={"input_data": {}}
        )
        self.assertEqual(status, 200, executed)
        data = executed["data"]
        self.assertEqual(data["status"], "COMPLETED", data.get("error"))
        http_node = [n for n in data["node_executions"] if n["node_id"] == "health"][0]
        self.assertEqual(http_node["output"]["status_code"], 200)
        # 响应里的 status 字段被并进变量，END 节点的输出能直接引用
        self.assertEqual(data["output"]["output"]["status"], "healthy")

        status, notifs = call("/notifications?page=1&page_size=20", token=self.token)
        for n in notifs["data"]["items"]:
            if (n.get("data") or {}).get("execution_id") == data["id"]:
                call(f"/notifications/{n['id']}", "DELETE", token=self.token)
        call(f"/workflows/{wf_id}", "DELETE", token=self.token)


    # ------------------------------------------------------------ 工作流 AI 节点（第 30 轮）
    def test_workflow_llm_node_calls_model_and_records_cost(self):
        """LLM 节点真的调模型、返回内容并记 tokens；本机没有 Ollama 时跳过（第 30 轮）。"""
        name = f"smoke-llm-{uuid.uuid4().hex[:6]}"
        definition = {
            "nodes": [
                {"id": "start", "type": "START", "name": "开始", "position": {"x": 0, "y": 0}, "config": {}},
                {
                    "id": "llm",
                    "type": "LLM",
                    "name": "生成",
                    "position": {"x": 200, "y": 0},
                    "config": {"prompt_template": "只回答两个字：你好", "temperature": 0.1, "max_tokens": 32},
                },
                {"id": "end", "type": "END", "name": "结束", "position": {"x": 400, "y": 0}, "config": {}},
            ],
            "edges": [
                {"id": "e1", "source_node_id": "start", "source_port_id": "out", "target_node_id": "llm", "target_port_id": "in"},
                {"id": "e2", "source_node_id": "llm", "source_port_id": "out", "target_node_id": "end", "target_port_id": "in"},
            ],
            "variables": [],
        }
        wf_id = self._create_published_workflow(name, definition)
        try:
            status, executed = call(
                f"/workflows/{wf_id}/execute", "POST", token=self.token, body={"input_data": {}}
            )
            self.assertEqual(status, 200, executed)
            data = executed["data"]
            if data["status"] != "COMPLETED":
                self.skipTest(f"本机没有可用的 Ollama 模型（11434），跳过真实调用：{data['error']}")

            llm_node = [n for n in data["node_executions"] if n["node_id"] == "llm"][0]
            self.assertTrue(llm_node["output"]["content"].strip(), llm_node)
            self.assertGreater(llm_node["output"]["prompt_tokens"], 0, llm_node)
            # 结果并进变量，END 节点能引用
            self.assertEqual(data["output"]["output"]["llm_model"], llm_node["output"]["model"])

            # 成本记录 + 汇总接口（以前一有记录就 500：SQLite 的 func.date() 返回字符串）
            status, summary = call("/costs/summary", token=self.token)
            self.assertEqual(status, 200, summary)
            ops = summary["data"].get("by_operation") or []
            self.assertTrue(
                any(o.get("operation_type") == "workflow_llm" for o in ops),
                f"没有 workflow_llm 的成本记录：{ops}",
            )
        finally:
            status, notifs = call("/notifications?page=1&page_size=20", token=self.token)
            if status == 200:
                for n in notifs["data"]["items"]:
                    if (n.get("data") or {}).get("workflow_id") == wf_id:
                        call(f"/notifications/{n['id']}", "DELETE", token=self.token)
            call(f"/workflows/{wf_id}", "DELETE", token=self.token)

    def test_workflow_rag_node_retrieves_chunks(self):
        """RAG 节点用本地检索真的命中分块，并把上下文并进变量（第 30 轮）。"""
        status, kb = call(
            "/knowledge-bases",
            "POST",
            token=self.token,
            body={"name": f"smoke-rag-{uuid.uuid4().hex[:6]}", "description": "RAG 节点冒烟"},
        )
        self.assertEqual(status, 201, kb)
        kb_id = kb["data"]["id"]

        keyword = f"火星{uuid.uuid4().hex[:4]}"
        filename = f"smoke-rag-{uuid.uuid4().hex[:6]}.txt"
        status, uploaded = upload(
            "/documents/upload",
            self.token,
            {"knowledge_base_id": kb_id},
            filename,
            f"{keyword} 探测计划说明：这是用来验证 RAG 节点的文档，含有关键词。" * 5,
        )
        self.assertEqual(status, 201, uploaded)
        doc_id = uploaded["data"]["file_id"]

        name = f"smoke-rag-wf-{uuid.uuid4().hex[:6]}"
        definition = {
            "nodes": [
                {"id": "start", "type": "START", "name": "开始", "position": {"x": 0, "y": 0}, "config": {}},
                {
                    "id": "rag",
                    "type": "RAG",
                    "name": "检索",
                    "position": {"x": 200, "y": 0},
                    "config": {"knowledge_base_id": kb_id, "query_template": "{{message}}", "top_k": 3},
                },
                {"id": "end", "type": "END", "name": "结束", "position": {"x": 400, "y": 0}, "config": {}},
            ],
            "edges": [
                {"id": "e1", "source_node_id": "start", "source_port_id": "out", "target_node_id": "rag", "target_port_id": "in"},
                {"id": "e2", "source_node_id": "rag", "source_port_id": "out", "target_node_id": "end", "target_port_id": "in"},
            ],
            "variables": [],
        }
        wf_id = self._create_published_workflow(name, definition)
        try:
            status, executed = call(
                f"/workflows/{wf_id}/execute",
                "POST",
                token=self.token,
                body={"input_data": {"message": keyword}},
            )
            self.assertEqual(status, 200, executed)
            data = executed["data"]
            self.assertEqual(data["status"], "COMPLETED", data.get("error"))
            rag_node = [n for n in data["node_executions"] if n["node_id"] == "rag"][0]
            self.assertGreaterEqual(rag_node["output"]["count"], 1, rag_node["output"])
            self.assertIn(keyword, rag_node["output"]["chunks"][0]["content"])
            # 检索到的上下文并进变量，后面的 LLM 节点可以直接用 {{rag_context}}
            self.assertIn(keyword, data["output"]["output"]["rag_context"])
        finally:
            status, notifs = call("/notifications?page=1&page_size=20", token=self.token)
            if status == 200:
                for n in notifs["data"]["items"]:
                    data = n.get("data") or {}
                    # 执行完成通知 + 上传文档解析完成的通知，都清掉
                    if data.get("workflow_id") == wf_id or data.get("document_id") == doc_id:
                        call(f"/notifications/{n['id']}", "DELETE", token=self.token)
            call(f"/workflows/{wf_id}", "DELETE", token=self.token)
            call(f"/documents/{doc_id}", "DELETE", token=self.token)
            call(f"/knowledge-bases/{kb_id}", "DELETE", token=self.token)



if __name__ == "__main__":
    try:
        urllib.request.urlopen(ROOT + "/health", timeout=5)
    except Exception:
        print("网关未启动，请先运行：cd services/api-gateway && python -m uvicorn app.main:app --port 8000")
        sys.exit(2)
    unittest.main(verbosity=2)
