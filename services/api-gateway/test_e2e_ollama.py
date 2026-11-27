"""阶段1端到端自测：登录 -> 创建对话 -> send_message -> 验证真实 ollama 回复"""
import asyncio
import httpx

BASE = "http://127.0.0.1:8200"
API = f"{BASE}/api/v1"


async def main():
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        # 1. 健康检查
        r = await client.get(f"{BASE}/health")
        print(f"[健康检查] {r.status_code} {r.text[:200]}")
        assert r.status_code == 200, "健康检查失败"
        data = r.json()
        assert data.get("status") == "healthy", f"状态不健康: {data}"
        print("[健康检查] database + redis healthy")

        # 2. 登录
        r = await client.post(
            f"{API}/auth/login",
            json={"email": "admin@example.com", "password": "admin123"},
        )
        print(f"[登录] {r.status_code}")
        assert r.status_code == 200, f"登录失败: {r.text}"
        token = r.json()["data"]["access_token"]
        print(f"[登录] token: {token[:20]}...")

        headers = {"Authorization": f"Bearer {token}"}

        # 3. 获取或创建对话
        r = await client.get(f"{API}/conversations", headers=headers)
        assert r.status_code == 200
        convs = r.json().get("data", {}).get("items", [])
        if convs:
            conv_id = convs[0]["id"]
            print(f"[对话] 使用现有对话: {conv_id}")
        else:
            r = await client.post(
                f"{API}/conversations",
                headers=headers,
                json={"title": "E2E 测试对话", "model": "qwen2.5-coder:1.5b"},
            )
            assert r.status_code in (200, 201), f"创建对话失败: {r.text}"
            conv_id = r.json()["data"]["id"]
            print(f"[对话] 新对话 ID: {conv_id}")

        # 4. 发送消息（非流式 send_message，使用真实 ollama）
        r = await client.post(
            f"{API}/conversations/{conv_id}/messages",
            headers=headers,
            json={"content": "你好，请用一句话介绍你自己。", "role": "user"},
        )
        print(f"[发消息] {r.status_code}")
        assert r.status_code == 200, f"发消息失败: {r.text}"
        msg = r.json()["data"]
        content = msg.get("content", "")
        print(f"[回复内容] {content[:500]}")

        # 验证不是模拟占位
        assert "模拟" not in content, f"仍是模拟回复: {content}"
        assert len(content) > 10, f"回复太短: {content}"
        print("[验证] 通过：收到真实 ollama 生成的中文回复，非模拟占位")

        # 5. 再次健康检查
        r2 = await client.get(f"{BASE}/health")
        print(f"[健康检查复查] {r2.status_code} {r2.text[:200]}")
        assert r2.status_code == 200
        assert r2.json().get("status") == "healthy"

        print("\n=== 阶段1端到端自测全部通过 ===")


if __name__ == "__main__":
    asyncio.run(main())
