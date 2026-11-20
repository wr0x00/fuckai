# -*- coding: utf-8 -*-
"""内嵌浏览器引擎路由 —— 画面串流 + 交互转发。

    GET  /api/engine/stream        MJPEG 实时画面（<img> 直接可用）
    GET  /api/engine/url           当前页面真实 URL（前端轮询同步地址栏）
    POST /api/engine/nav           {url}                  导航
    POST /api/engine/reload        {}                     刷新
    POST /api/engine/back          {}                     后退
    POST /api/engine/forward       {}                     前进
    POST /api/engine/click         {x, y}                 视口坐标点击
    POST /api/engine/scroll        {dy}                   滚轮
    POST /api/engine/key           {key}                  按键 / 单字符输入
    GET  /api/engine/status        {ready, url}           引擎状态
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from fuckai.browser_engine import engine


class NavBody(BaseModel):
    url: str


class ClickBody(BaseModel):
    x: float
    y: float


class ScrollBody(BaseModel):
    dy: float


class KeyBody(BaseModel):
    key: str


class TextBody(BaseModel):
    text: str


class ResizeBody(BaseModel):
    width: float
    height: float
    dpr: float | None = None


class EnabledBody(BaseModel):
    enabled: bool


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/engine")

    @router.get("/status")
    async def status() -> dict:
        url = ""
        if engine.enabled and engine.ready:
            try:
                url = await engine.current_url()
            except Exception:
                pass
        return {"enabled": engine.enabled, "ready": engine.ready, "url": url,
                "frame_seq": engine.frame_seq,
                "clients": engine.clients}

    @router.post("/enabled")
    async def set_enabled(body: EnabledBody) -> dict:
        await engine.set_enabled(body.enabled)
        return {"enabled": engine.enabled, "ready": engine.ready}

    @router.get("/url")
    async def url() -> dict:
        try:
            return {"url": await engine.current_url()}
        except Exception:
            return {"url": ""}

    @router.get("/stream")
    async def stream() -> StreamingResponse:
        async def gen():
            engine.client_enter()
            try:
                await engine.page()  # 引擎被闲置回收后按需拉起
                boundary = b"--frame\r\n"
                last_seq = -1
                while True:
                    if not engine.enabled:
                        break
                    # 事件驱动：内核重绘才推帧，静止页面零开销
                    frame, seq = await engine.wait_frame(0.5)
                    if seq != last_seq and frame:
                        # 陈帧折叠：缓冲区只存最新帧，解码跟不上时跳过中间帧防顿挫
                        newest = await engine.latest_frame()
                        nseq = engine.frame_seq
                        if nseq > seq:
                            frame, seq = newest, nseq
                        last_seq = seq
                        yield (boundary + b"Content-Type: image/png\r\n\r\n"
                               + frame + b"\r\n")
                    elif not frame:
                        # 串流不可用的兜底：主动截图，慢速保底
                        try:
                            frame = await engine.screenshot_frame()
                            yield (boundary + b"Content-Type: image/png\r\n\r\n"
                                   + frame + b"\r\n")
                        except Exception:
                            await asyncio.sleep(0.5)
                    else:
                        await asyncio.sleep(0.02)
            finally:
                engine.client_leave()

        return StreamingResponse(gen(),
                                 media_type="multipart/x-mixed-replace; boundary=frame",
                                 headers={"Cache-Control": "no-store"})

    @router.post("/nav")
    async def nav(body: NavBody) -> dict:
        target = (body.url or "").strip()
        if target and not target.startswith(("http://", "https://")):
            target = "https://" + target
        try:
            final = await engine.navigate(target)
            return {"ok": True, "url": final}
        except Exception as e:
            return {"ok": False, "error": str(e), "url": await engine.current_url()}

    @router.post("/reload")
    async def reload() -> dict:
        return {"ok": True, "url": await engine.reload()}

    @router.post("/back")
    async def back() -> dict:
        return {"ok": True, "url": await engine.back()}

    @router.post("/forward")
    async def forward() -> dict:
        return {"ok": True, "url": await engine.forward()}

    @router.post("/click")
    async def click(body: ClickBody) -> dict:
        try:
            await engine.click(body.x, body.y)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @router.post("/scroll")
    async def scroll(body: ScrollBody) -> dict:
        try:
            await engine.scroll(body.dy)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @router.post("/key")
    async def key(body: KeyBody) -> dict:
        if not body.key:
            return {"ok": False, "error": "empty key"}
        try:
            await engine.key(body.key)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @router.post("/text")
    async def text(body: TextBody) -> dict:
        if not body.text:
            return {"ok": False, "error": "empty text"}
        try:
            await engine.insert_text(body.text)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @router.get("/selection")
    async def selection() -> dict:
        try:
            return {"text": await engine.get_selection()}
        except Exception:
            return {"text": ""}

    @router.websocket("/ws")
    async def ws_stream(ws: WebSocket):
        """WebSocket 二进制帧直推：前端 canvas 以刷新率渲染，latest-wins 防积压。"""
        await ws.accept()
        engine.client_enter()
        last_seq = -1
        try:
            await engine.page()  # 引擎被闲置回收后按需拉起（恢复上次访问页）
            while True:
                if not engine.enabled:
                    break
                frame, seq = await engine.wait_frame(0.25)
                if seq != last_seq and frame:
                    newest = await engine.latest_frame()
                    nseq = engine.frame_seq
                    if nseq > seq:
                        frame, seq = newest, nseq
                    last_seq = seq
                    await ws.send_bytes(frame)
                elif not frame:
                    # 串流不可用的兜底：主动截图，慢速保底
                    try:
                        await ws.send_bytes(await engine.screenshot_frame())
                    except Exception:
                        await asyncio.sleep(0.5)
        except WebSocketDisconnect:
            pass
        except Exception:
            try:
                await ws.close()
            except Exception:
                pass
        finally:
            engine.client_leave()

    @router.post("/resize")
    async def resize(body: ResizeBody) -> dict:
        try:
            return await engine.resize(body.width, body.height, body.dpr)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return router
