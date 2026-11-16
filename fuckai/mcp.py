# -*- coding: utf-8 -*-
"""MCP（Model Context Protocol）接入层 —— 让模型可以直接调用外部 MCP 工具。

三块职责：
  1. 服务器配置管理：stdio / sse / http 三种传输，配置落盘到项目根目录 mcp_servers.json
  2. 工具调用：连接服务器 → tools/list 拉工具 → tools/call 执行
  3. 对话编排：把 MCP 工具转成 OpenAI function-calling 格式，驱动
     「模型 → 调工具 → 回填结果 → 模型继续回答」的多轮循环

为什么要单独开一个后台事件循环线程：
  MCP 官方 SDK 是异步的，而本项目的 LLM 客户端（fuckai/client.py）是同步阻塞的。
  在 FastAPI 的事件循环里直接跑 MCP 会把整个服务卡住；每次调用现开事件循环又会让
  MCP 服务器子进程和会话无法复用。所以这里给 MCP 配一个常驻的后台事件循环线程，
  所有 MCP 操作都通过 run_coroutine_threadsafe 投递过去，对外仍保持同步接口。
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MCP_SERVERS_PATH = PROJECT_ROOT / "mcp_servers.json"

STDIO = "stdio"
SSE = "sse"
HTTP = "http"
TRANSPORTS = (STDIO, SSE, HTTP)

MAX_TOOL_ITER = 8          # 单次回答内最多允许几轮工具调用
TOOL_RESULT_MAX = 8000     # 工具结果回填给模型的最大字符数
TOOL_DESC_MAX = 800        # 工具描述给模型时的最大字符数

_store_lock = threading.RLock()


def mcp_sdk_available() -> bool:
    """检查 MCP 官方 SDK 是否装了（没装也不影响项目其它功能）。"""
    try:
        import mcp  # noqa: F401
    except Exception:
        return False
    return True


# ---------------------------------------------------------------- 配置模型


@dataclass
class McpServerConfig:
    name: str = ""
    transport: str = STDIO
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    timeout: int = 60

    def validate(self) -> str:
        """返回空串表示配置合法，否则返回错误原因。"""
        if not (self.name or "").strip():
            return "缺少服务器名称"
        if self.transport == STDIO:
            if not (self.command or "").strip():
                return "stdio 传输需要填写启动命令"
        elif self.transport in (SSE, HTTP):
            if not (self.url or "").strip():
                return f"{self.transport} 传输需要填写服务地址"
        else:
            return f"不支持的传输方式：{self.transport}"
        return ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "transport": self.transport,
            "command": self.command,
            "args": list(self.args or []),
            "env": dict(self.env or {}),
            "url": self.url,
            "headers": dict(self.headers or {}),
            "enabled": bool(self.enabled),
            "timeout": int(self.timeout or 60),
        }

    @staticmethod
    def from_dict(raw: dict) -> "McpServerConfig":
        raw = raw or {}
        return McpServerConfig(
            name=str(raw.get("name") or ""),
            transport=str(raw.get("transport") or STDIO),
            command=str(raw.get("command") or ""),
            args=[str(a) for a in (raw.get("args") or [])],
            env={str(k): str(v) for k, v in (raw.get("env") or {}).items()},
            url=str(raw.get("url") or ""),
            headers={str(k): str(v) for k, v in (raw.get("headers") or {}).items()},
            enabled=bool(raw.get("enabled", True)),
            timeout=int(raw.get("timeout") or 60),
        )


def load_servers() -> list[McpServerConfig]:
    """读取 MCP 服务器配置列表（文件不存在时返回空列表）。"""
    with _store_lock:
        try:
            raw = json.loads(MCP_SERVERS_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except Exception:
            return []
    items = raw.get("servers") if isinstance(raw, dict) else raw
    out = []
    for it in items or []:
        try:
            out.append(McpServerConfig.from_dict(it))
        except Exception:
            continue
    return out


def save_servers(servers: list[McpServerConfig]) -> None:
    """把配置写回磁盘。"""
    with _store_lock:
        payload = {"servers": [s.to_dict() for s in servers]}
        MCP_SERVERS_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )


# ---------------------------------------------------------------- 管理器


class McpManager:
    """MCP 连接与工具调用的总管（进程内单例）。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._sessions: dict[str, dict] = {}     # 服务器名 -> {"cfg", "session", "stack"}
        self._tools: dict[str, list[dict]] = {}   # 服务器名 -> 工具列表
        self._status: dict[str, dict] = {}        # 服务器名 -> {"state", "error", "tools"}

    # -- 后台事件循环 --------------------------------------------------

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop and not self._loop.is_closed():
                return self._loop
            loop = asyncio.new_event_loop()

            def _runner() -> None:
                asyncio.set_event_loop(loop)
                loop.run_forever()

            th = threading.Thread(target=_runner, name="fuckai-mcp-loop", daemon=True)
            th.start()
            self._loop = loop
            self._thread = th
            return loop

    def _submit(self, coro, timeout: float = 120):
        loop = self._ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result(timeout=timeout)

    # -- 连接 ----------------------------------------------------------

    async def _open(self, cfg: McpServerConfig):
        """建立一个 MCP 会话，返回 (stack, session)。"""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        stack = AsyncExitStack()
        try:
            if cfg.transport == STDIO:
                env = {**os.environ, **{str(k): str(v) for k, v in (cfg.env or {}).items()}}
                params = StdioServerParameters(
                    command=cfg.command, args=[str(a) for a in (cfg.args or [])], env=env
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            elif cfg.transport == SSE:
                from mcp.client.sse import sse_client

                read, write = await stack.enter_async_context(
                    sse_client(url=cfg.url, headers=cfg.headers or {}, timeout=cfg.timeout)
                )
            else:
                from mcp.client.streamable_http import streamablehttp_client

                read, write, _ = await stack.enter_async_context(
                    streamablehttp_client(url=cfg.url, headers=cfg.headers or {})
                )
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            return stack, session
        except BaseException:
            try:
                await stack.aclose()
            except Exception:
                pass
            raise

    @staticmethod
    def _tool_entry(cfg: McpServerConfig, tool: Any) -> dict:
        schema = getattr(tool, "inputSchema", None)
        if schema is None:
            schema = getattr(tool, "input_schema", None)
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}}
        raw_name = str(getattr(tool, "name", "") or "")
        return {
            "server": cfg.name,
            "name": raw_name,
            "exposed": f"{cfg.name}__{raw_name}" if raw_name else cfg.name,
            "description": str(getattr(tool, "description", "") or ""),
            "input_schema": schema,
        }

    async def _open_and_list(self, cfg: McpServerConfig):
        stack, session = await self._open(cfg)
        try:
            result = await session.list_tools()
            tools = [self._tool_entry(cfg, t) for t in (getattr(result, "tools", None) or [])]
        except BaseException:
            try:
                await stack.aclose()
            except Exception:
                pass
            raise
        return stack, session, tools

    async def _refresh_many(self, cfgs: list[McpServerConfig]):
        """并行连接多个服务器并拉取工具列表。"""
        async def one(cfg: McpServerConfig):
            try:
                stack, session, tools = await self._open_and_list(cfg)
                return cfg, stack, session, tools, None
            except Exception as exc:  # noqa: BLE001
                return cfg, None, None, [], exc

        return await asyncio.gather(*[one(c) for c in cfgs])

    def refresh(self, names: list[str] | None = None) -> dict:
        """连接（或重连）指定的 MCP 服务器并拉取工具，返回各服务器状态。"""
        servers = load_servers()
        wanted = set(names) if names else None
        targets = [s for s in servers if s.enabled and (wanted is None or s.name in wanted)]
        if not targets:
            return {}

        async def job():
            return await self._refresh_many(targets)

        timeout = max(t.timeout for t in targets) + 30
        try:
            results = self._submit(job(), timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            for cfg in targets:
                self._status[cfg.name] = {
                    "state": "error",
                    "error": _brief_err(exc),
                    "tools": 0,
                }
            return {c.name: self._status[c.name] for c in targets}

        for cfg, stack, session, tools, err in results:
            if err is not None:
                self._drop(cfg.name)
                self._status[cfg.name] = {
                    "state": "error",
                    "error": _brief_err(err),
                    "tools": 0,
                }
                continue
            self._drop(cfg.name)
            self._sessions[cfg.name] = {"cfg": cfg, "session": session, "stack": stack}
            self._tools[cfg.name] = tools
            self._status[cfg.name] = {"state": "connected", "error": "", "tools": len(tools)}
        return {c.name: self._status[c.name] for c in targets}

    def _drop(self, name: str) -> None:
        """丢弃某个服务器的会话（关闭子进程）。"""
        entry = self._sessions.pop(name, None)
        if not entry:
            return
        stack = entry.get("stack")
        if stack is None:
            return
        try:
            self._submit(stack.aclose(), timeout=15)
        except Exception:
            pass

    def disconnect(self, name: str) -> None:
        self._drop(name)
        self._tools.pop(name, None)
        self._status[name] = {"state": "idle", "error": "", "tools": 0}

    def disconnect_all(self) -> None:
        for name in list(self._sessions.keys()):
            self.disconnect(name)

    # -- 查询 ----------------------------------------------------------

    def list_servers(self) -> list[dict]:
        """列出全部配置 + 当前连接状态。"""
        out = []
        for cfg in load_servers():
            st = self._status.get(cfg.name) or {"state": "idle", "error": "", "tools": 0}
            item = cfg.to_dict()
            item["state"] = st.get("state", "idle")
            item["error"] = st.get("error", "")
            item["tools"] = st.get("tools", 0)
            out.append(item)
        return out

    def tools(self) -> list[dict]:
        """所有已连接服务器的工具（扁平列表）。"""
        out = []
        for name, tools in self._tools.items():
            out.extend(tools)
        return out

    def openai_tools(self) -> list[dict]:
        """把 MCP 工具转成 OpenAI function-calling 格式。"""
        out = []
        for t in self.tools():
            desc = t.get("description") or f"{t['server']} 提供的 {t['name']} 工具"
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": t["exposed"],
                        "description": desc[:TOOL_DESC_MAX],
                        "parameters": t.get("input_schema")
                        or {"type": "object", "properties": {}},
                    },
                }
            )
        return out

    def server_of(self, exposed: str) -> str:
        for t in self.tools():
            if t["exposed"] == exposed:
                return t["server"]
        return ""

    def _lookup(self, exposed: str) -> tuple[str, str] | None:
        """工具名 → (服务器名, 原始工具名)；找不到再按原始名模糊匹配一次。"""
        for t in self.tools():
            if t["exposed"] == exposed:
                return t["server"], t["name"]
        for t in self.tools():
            if t["name"] == exposed:
                return t["server"], t["name"]
        return None

    # -- 执行 ----------------------------------------------------------

    @staticmethod
    def _result_to_text(res: Any) -> str:
        parts: list[str] = []
        for c in getattr(res, "content", None) or []:
            ctype = str(getattr(c, "type", "") or "")
            if ctype == "text":
                parts.append(str(getattr(c, "text", "") or ""))
            elif ctype == "image":
                parts.append("[图片内容，模型无法直接查看]")
            elif ctype == "resource":
                res_obj = getattr(c, "resource", None)
                text = getattr(res_obj, "text", None) if res_obj is not None else None
                parts.append(str(text) if text else "[资源内容]")
            else:
                parts.append(str(c))
        text = "\n".join(p for p in parts if p).strip()
        if getattr(res, "isError", False):
            text = ("[工具返回错误] " + text) if text else "[工具返回错误]"
        if len(text) > TOOL_RESULT_MAX:
            text = text[:TOOL_RESULT_MAX] + "\n…（结果过长已截断）"
        return text or "(空结果)"

    def call_tool(self, exposed: str, arguments: dict) -> str:
        """执行一个 MCP 工具，返回给模型看的文本结果。"""
        hit = self._lookup(exposed)
        if not hit:
            return f"错误：未找到 MCP 工具 {exposed}"
        server, raw_name = hit
        entry = self._sessions.get(server)
        if entry is None:
            self.refresh([server])
            entry = self._sessions.get(server)
        if entry is None:
            return f"错误：MCP 服务器 {server} 未连接，请先在 MCP 面板里连接"

        async def job():
            res = await entry["session"].call_tool(raw_name, arguments or {})
            return self._result_to_text(res)

        try:
            return self._submit(job(), timeout=120)
        except Exception as exc:  # noqa: BLE001
            return f"工具执行失败：{_brief_err(exc)}"


_manager: McpManager | None = None
_manager_lock = threading.Lock()


def get_mcp_manager() -> McpManager:
    """进程内单例。"""
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = McpManager()
        return _manager


# ---------------------------------------------------------------- 对话编排


def merge_tool_calls(deltas: list[dict]) -> list[dict]:
    """把流式返回的 tool_calls 分片合并成完整的调用列表。"""
    merged: dict[int, dict] = {}
    for pos, d in enumerate(deltas or []):
        if not isinstance(d, dict):
            continue
        idx = d.get("index")
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            # 非流式响应里没有 index，按出现顺序编号，避免多个调用被合并成一个
            idx = pos
        cur = merged.setdefault(
            idx, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
        )
        if d.get("id"):
            cur["id"] = str(d["id"])
        fn = d.get("function") or {}
        if fn.get("name"):
            cur["function"]["name"] = str(fn["name"])
        if fn.get("arguments"):
            cur["function"]["arguments"] += str(fn["arguments"])
    out = []
    for k in sorted(merged):
        cur = merged[k]
        if not cur["id"]:
            cur["id"] = f"call_{int(time.time() * 1000)}_{k}"
        out.append(cur)
    return out


def run_chat_with_tools(client, messages, tools, manager=None, max_iter: int = MAX_TOOL_ITER):
    """驱动「模型 → 调工具 → 回填结果 → 模型继续回答」的循环。

    产出事件字典：
      {"type": "reasoning", "text": str}
      {"type": "delta", "text": str}
      {"type": "tool_start", "id", "name", "args"}
      {"type": "tool_end", "id", "name", "server", "args", "result"}
      {"type": "mcp_warn", "error": str}
      {"type": "final", "reply": str}
    """
    mgr = manager or get_mcp_manager()
    msgs = [dict(m) for m in messages]
    use_tools = bool(tools)
    warned = False

    for _ in range(max_iter + 1):
        acc: list[str] = []
        tdeltas: list[dict] = []
        try:
            for kind, payload in client.chat_stream(msgs, tools=tools if use_tools else None):
                if kind == "reasoning":
                    yield {"type": "reasoning", "text": payload}
                elif kind == "content":
                    acc.append(payload)
                    yield {"type": "delta", "text": payload}
                elif kind == "tool_call":
                    # client 一次给的是整组分片，这里摊平成单条
                    if isinstance(payload, list):
                        tdeltas.extend(payload)
                    elif isinstance(payload, dict):
                        tdeltas.append(payload)
        except RuntimeError as exc:
            # 上游模型接口不支持 tools 参数时，去掉 tools 重跑一次
            if use_tools and not warned and not acc and "tool" in str(exc).lower():
                warned = True
                use_tools = False
                tools = None
                yield {"type": "mcp_warn", "error": "该模型接口不支持 tools 参数，已自动关闭工具调用"}
                acc = []
                tdeltas = []
                for kind, payload in client.chat_stream(msgs):
                    if kind == "reasoning":
                        yield {"type": "reasoning", "text": payload}
                    elif kind == "content":
                        acc.append(payload)
                        yield {"type": "delta", "text": payload}
            else:
                raise

        calls = merge_tool_calls(tdeltas)
        reply = "".join(acc)
        if not calls:
            yield {"type": "final", "reply": reply}
            return

        msgs.append({"role": "assistant", "content": reply or None, "tool_calls": calls})
        for c in calls:
            fn = c.get("function") or {}
            fname = str(fn.get("name") or "")
            raw_args = str(fn.get("arguments") or "")
            try:
                args = json.loads(raw_args) if raw_args.strip() else {}
            except ValueError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            yield {"type": "tool_start", "id": c.get("id", ""), "name": fname, "args": args}
            try:
                result = mgr.call_tool(fname, args)
            except Exception as exc:  # noqa: BLE001
                result = f"工具执行异常：{_brief_err(exc)}"
            yield {
                "type": "tool_end",
                "id": c.get("id", ""),
                "name": fname,
                "server": mgr.server_of(fname),
                "args": args,
                "result": result,
            }
            msgs.append({"role": "tool", "tool_call_id": c.get("id", ""), "content": result})


def _brief_err(exc: BaseException) -> str:
    """把异常压成一行短文本。"""
    text = str(exc).strip() or exc.__class__.__name__
    text = text.replace("\r", " ").replace("\n", " ")
    return text[:300]
