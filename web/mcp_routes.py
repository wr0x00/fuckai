# -*- coding: utf-8 -*-
"""MCP 路由 —— 服务器配置管理 / 连接测试 / 工具列表。

    GET    /api/mcp/servers        列出全部 MCP 服务器配置 + 连接状态
    POST   /api/mcp/servers        新增一个服务器配置
    PUT    /api/mcp/servers        更新服务器配置（按 name 定位）
    DELETE /api/mcp/servers/{name} 删除服务器配置
    POST   /api/mcp/connect        连接 / 重连服务器（拉取工具列表）
    POST   /api/mcp/disconnect     断开服务器
    GET    /api/mcp/tools          当前可用工具（OpenAI function 格式）
    POST   /api/mcp/call           直接调用一个工具（调试用）
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fuckai.mcp import (
    TRANSPORTS,
    McpServerConfig,
    get_mcp_manager,
    load_servers,
    mcp_sdk_available,
    save_servers,
)


class ServerBody(BaseModel):
    name: str
    transport: str = "stdio"
    command: str = ""
    args: list[str] = []
    env: dict[str, str] = {}
    url: str = ""
    headers: dict[str, str] = {}
    enabled: bool = True
    timeout: int = 60


class ConnectBody(BaseModel):
    names: list[str] | None = None


class CallBody(BaseModel):
    name: str
    arguments: dict = {}


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/mcp")
    mgr = get_mcp_manager()

    def _require_sdk() -> None:
        if not mcp_sdk_available():
            raise HTTPException(400, "未安装 MCP SDK，请先执行：pip install mcp")

    @router.get("/servers")
    def servers() -> dict:
        return {"sdk": mcp_sdk_available(), "items": mgr.list_servers()}

    @router.post("/servers")
    def add_server(body: ServerBody) -> dict:
        cfg = McpServerConfig(
            name=body.name.strip(),
            transport=body.transport,
            command=body.command,
            args=list(body.args),
            env=dict(body.env),
            url=body.url,
            headers=dict(body.headers),
            enabled=body.enabled,
            timeout=body.timeout,
        )
        err = cfg.validate()
        if err:
            raise HTTPException(400, err)
        if cfg.transport not in TRANSPORTS:
            raise HTTPException(400, f"不支持的传输方式：{cfg.transport}")
        items = load_servers()
        items = [s for s in items if s.name != cfg.name]
        items.append(cfg)
        save_servers(items)
        if cfg.enabled:
            mgr.refresh([cfg.name])
        return {"items": mgr.list_servers()}

    @router.put("/servers")
    def update_server(body: ServerBody) -> dict:
        items = load_servers()
        target = None
        for s in items:
            if s.name == body.name:
                target = s
                break
        if target is None:
            raise HTTPException(404, f"未找到 MCP 服务器：{body.name}")
        cfg = McpServerConfig(
            name=body.name.strip(),
            transport=body.transport,
            command=body.command,
            args=list(body.args),
            env=dict(body.env),
            url=body.url,
            headers=dict(body.headers),
            enabled=body.enabled,
            timeout=body.timeout,
        )
        err = cfg.validate()
        if err:
            raise HTTPException(400, err)
        items = [cfg if s.name == body.name else s for s in items]
        save_servers(items)
        mgr.disconnect(body.name)
        if cfg.enabled:
            mgr.refresh([cfg.name])
        return {"items": mgr.list_servers()}

    @router.delete("/servers/{name}")
    def delete_server(name: str) -> dict:
        items = load_servers()
        if not any(s.name == name for s in items):
            raise HTTPException(404, f"未找到 MCP 服务器：{name}")
        mgr.disconnect(name)
        save_servers([s for s in items if s.name != name])
        return {"items": mgr.list_servers()}

    @router.post("/connect")
    def connect(body: ConnectBody) -> dict:
        _require_sdk()
        mgr.refresh(body.names)
        return {"items": mgr.list_servers()}

    @router.post("/disconnect")
    def disconnect(body: ConnectBody) -> dict:
        for name in body.names or []:
            mgr.disconnect(name)
        return {"items": mgr.list_servers()}

    @router.get("/tools")
    def tools() -> dict:
        return {"items": mgr.openai_tools()}

    @router.post("/call")
    def call(body: CallBody) -> dict:
        _require_sdk()
        return {"result": mgr.call_tool(body.name, body.arguments or {})}

    return router
