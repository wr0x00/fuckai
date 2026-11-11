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
                 temperature: float = 0.0, timeout: int = 120, max_tokens: int | None = 1024):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        # max_tokens=None 表示不限制输出长度（请求里省略该字段，由模型/服务端决定）
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
        }
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
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
        msg = data["choices"][0]["message"] or {}
        text = msg.get("content")
        # 部分思考模型把额度耗在思考上，正文为空时兜底取思考内容
        if not text:
            text = msg.get("reasoning_content") or ""
        return text

    # ---- 流式对话：逐段产出回复文本（OpenAI 兼容 SSE） ----
    def chat_stream(self, messages: list[dict], temperature: float | None = None):
        if not self.base_url or not self.model:
            raise RuntimeError("模型端点未配置：请先在 config.yaml 里填写 base_url 和 model")
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "stream": True,
        }
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}",
                     "Accept": "text/event-stream"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"HTTP {e.code} 调用失败: {body}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"连接失败 ({self.base_url}): {e.reason}") from e
        with resp:
            ctype = resp.headers.get("Content-Type", "")
            # 部分网关/后端（如 MiniMax）会忽略 stream 参数直接回 JSON，需兼容
            if "text/event-stream" not in ctype:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
                base_resp = data.get("base_resp") or {}
                if base_resp.get("status_code") not in (0, None):
                    raise RuntimeError(f"上游返回错误: {base_resp.get('status_msg') or base_resp}")
                choices = data.get("choices") or []
                if choices:
                    text = (choices[0].get("message") or {}).get("content") or ""
                    if text:
                        yield ("content", text)
                return
            # 按行读取：read(1024) 会在缓冲区攒满才返回，导致流式变成一次性输出
            while True:
                line = resp.readline()
                if not line:
                    break
                line = line.strip()
                if not line.startswith(b"data:"):
                    continue
                data = line[5:].strip().decode("utf-8", errors="replace")
                if data == "[DONE]":
                    return
                try:
                    obj = json.loads(data)
                except ValueError:
                    continue
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                # 思考模型（如 MiniMax-M3.1）会先推 reasoning_content
                think = delta.get("reasoning_content")
                if think:
                    yield ("reasoning", think)
                text = delta.get("content")
                if text:
                    yield ("content", text)

    def ping(self) -> str:
        return self.chat([{"role": "user", "content": "Reply with exactly: PONG"}], temperature=0.0)
