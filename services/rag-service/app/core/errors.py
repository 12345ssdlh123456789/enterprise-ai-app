"""RAG 服务的领域异常。

单独定义而不是直接抛 RuntimeError，是为了让 API 层把「embedding 不可用」
映射成 503（依赖不可用）而不是 500（服务端 bug）——前者调用方可以重试/降级，
后者的语义是代码出错。
"""


class EmbeddingUnavailable(RuntimeError):
    """Embedding 服务不可用：未配置 key、Ollama/OpenAI 未启动、模型不存在或网络不通。"""

    def __init__(self, message: str, *, model: str | None = None):
        self.model = model
        super().__init__(message)

    def public_message(self) -> str:
        hint = "请检查 EMBEDDING_API_BASE / EMBEDDING_API_KEY 是否可用"
        reason = str(self).rstrip("。. ")
        if self.model:
            return f"Embedding 服务不可用（模型 {self.model}）：{reason}。{hint}"
        return f"Embedding 服务不可用：{reason}。{hint}"
