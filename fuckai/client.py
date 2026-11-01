# -*- coding: utf-8 -*-
"""LLM 客户端 —— 对应本程序的 prompt_target 模块。

本程序 每类目标（OpenAITarget / HTTPTarget / HuggingFaceTarget...）都实现统一
接口：收 PromptRequest、返回文本。这里简化为任意 OpenAI 兼容
/chat/completions 端点，纯标准库实现。
"""
import json
import urllib.error
import urllib.request


class ChatClient:
    def __init__(self, base_url: str, api_key: str, model: str,
                 temperature: float = 0.0, timeout: int = 120, max_tokens: int = 1024):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_tokens = max_tokens

    # ---- 对应本程序 Target.send_promptAsync(prompt) ----
    def chat(self, messages: list[dict], temperature: float | None = None) -> str:
        if not self.base_url or not self.model:
            raise RuntimeError("模型端点未配置：请先在 config.yaml 里填写 base_url 和 model")
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"HTTP {e.code} 调用失败: {body}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"连接失败 ({self.base_url}): {e.reason}") from e
        return data["choices"][0]["message"]["content"]

    def ping(self) -> str:
        return self.chat([{"role": "user", "content": "Reply with exactly: PONG"}], temperature=0.0)
