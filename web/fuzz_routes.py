# -*- coding: utf-8 -*-
"""LLM 自动化模糊测试（AI Fuzzing）的 HTTP 路由。

只做三件事：
    1. 把 fuzz_routes 挂到主应用上（app.py 里 include_router）
    2. 开一条 SSE 长连接，实时把引擎事件推给前端
    3. 暴露暂停 / 继续 / 取消 / 人工接管 + 会话列表 / 详情 / 删除 / 导出

引擎逻辑全在 fuckai/llm_orchestrator.py，这里不掺和业务。
"""
from __future__ import annotations

import json
import queue
import threading
import uuid
from typing import Callable

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from fuckai.llm_orchestrator import (
    FuzzControl,
    FuzzSessionStore,
    LLMOrchestrator,
    export_session_csv,
    export_session_json,
    export_session_markdown,
    export_sessions_markdown,
)


class FuzzRunRequest(BaseModel):
    objective: str = ""
    max_rounds: int = 10   # 0 = 不限轮数
    title: str = ""


class FuzzControlRequest(BaseModel):
    run_id: str = ""


class FuzzManualRequest(BaseModel):
    run_id: str = ""
    text: str = ""


def build_router(get_orchestrator: Callable[[], object]) -> APIRouter:
    """生成路由。get_orchestrator 返回主 Orchestrator（复用它的模型配置与数据库）。"""
    router = APIRouter(prefix="/api/fuzz", tags=["fuzz"])

    runs: dict[str, FuzzControl] = {}
    runs_lock = threading.Lock()
    store = FuzzSessionStore()

    def _engine() -> LLMOrchestrator:
        orch = get_orchestrator()
        return LLMOrchestrator(
            orch.cfg,
            memory=orch.memory,
            attack_client=orch.attack_client,
            target_client=orch.target_client,
        )

    def _control(run_id: str) -> FuzzControl:
        with runs_lock:
            c = runs.get(run_id)
        if c is None:
            raise HTTPException(status_code=404, detail="任务不存在或已结束")
        return c

    # ---------------- 流式执行 ----------------
    @router.post("/stream")
    def fuzz_stream(req: FuzzRunRequest):
        objective = (req.objective or "").strip()
        if not objective:
            raise HTTPException(status_code=400, detail="请填写最终攻击目标")

        run_id = uuid.uuid4().hex[:10]
        control = FuzzControl()
        with runs_lock:
            runs[run_id] = control

        def gen():
            q: "queue.Queue" = queue.Queue()
            engine = _engine()
            session = engine.new_session(objective, max_rounds=req.max_rounds, title=req.title)

            def emit(kind: str, payload: dict):
                q.put((kind, payload))

            def worker():
                try:
                    engine.run(session, control, emit)
                except Exception as e:
                    # 致命错误才终止整条流；单轮失败由引擎自己发 error 事件继续跑
                    q.put(("fatal", {"message": str(e)}))
                finally:
                    with runs_lock:
                        runs.pop(run_id, None)

            t = threading.Thread(target=worker, daemon=True)
            t.start()

            yield f"data: {json.dumps({'type': 'start', 'run_id': run_id}, ensure_ascii=False)}\n\n"
            while True:
                try:
                    kind, payload = q.get(timeout=30)
                except queue.Empty:
                    # 心跳，避免中间代理掐断长连接
                    yield ": ping\n\n"
                    continue
                data = {"type": kind}
                data.update(payload or {})
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                if kind in ("done", "cancelled", "fatal"):
                    break

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---------------- 控制 ----------------
    @router.post("/pause")
    def fuzz_pause(req: FuzzControlRequest) -> dict:
        _control(req.run_id).pause()
        return {"ok": True, "paused": True}

    @router.post("/resume")
    def fuzz_resume(req: FuzzControlRequest) -> dict:
        _control(req.run_id).resume()
        return {"ok": True, "paused": False}

    @router.post("/cancel")
    def fuzz_cancel(req: FuzzControlRequest) -> dict:
        _control(req.run_id).cancel()
        return {"ok": True}

    @router.post("/manual")
    def fuzz_manual(req: FuzzManualRequest) -> dict:
        """人工接管：暂停状态下直接发给被攻击模型，不经过攻击模型改写。"""
        text = (req.text or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="消息不能为空")
        control = _control(req.run_id)
        if not control.paused.is_set():
            raise HTTPException(status_code=400, detail="当前不是暂停状态，请先暂停再人工接管")
        control.manual.put(text)
        return {"ok": True}

    # ---------------- 会话记录 ----------------
    @router.get("/sessions")
    def fuzz_sessions() -> dict:
        return {"sessions": store.briefs()}

    @router.get("/sessions/{sid}")
    def fuzz_session(sid: str) -> dict:
        s = store.get(sid)
        if s is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        return {"ok": True, "session": s}

    @router.delete("/sessions/{sid}")
    def fuzz_delete(sid: str) -> dict:
        if not store.delete(sid):
            raise HTTPException(status_code=404, detail="会话不存在")
        return {"ok": True}

    # ---------------- 导出 ----------------
    @router.get("/export/{sid}")
    def fuzz_export(sid: str, fmt: str = "md") -> Response:
        fmt = (fmt or "md").lower()
        if sid == "all":
            sessions = store.load()
            if fmt == "json":
                body = json.dumps({"sessions": sessions}, ensure_ascii=False, indent=2)
                fname = "fuzz_sessions.json"
                media = "application/json"
            elif fmt == "csv":
                import csv
                import io
                buf = io.StringIO()
                writer = csv.writer(buf)
                writer.writerow(("session_id", "round", "source", "ammo", "topic", "prompt",
                                 "response", "success", "verdict", "ts"))
                for s in sessions:
                    for r in s.get("rounds") or []:
                        writer.writerow((s.get("id", ""), r.get("round", ""), r.get("source", ""),
                                         r.get("ammo_name", ""), r.get("topic", ""), r.get("prompt", ""),
                                         r.get("response", ""), int(bool(r.get("success"))),
                                         r.get("verdict", ""), r.get("ts", "")))
                body = buf.getvalue()
                fname = "fuzz_sessions.csv"
                media = "text/csv"
            else:
                body = export_sessions_markdown(sessions)
                fname = "fuzz_sessions.md"
                media = "text/markdown"
        else:
            s = store.get(sid)
            if s is None:
                raise HTTPException(status_code=404, detail="会话不存在")
            if fmt == "json":
                body = export_session_json(s)
                fname = f"fuzz_{sid}.json"
                media = "application/json"
            elif fmt == "csv":
                body = export_session_csv(s)
                fname = f"fuzz_{sid}.csv"
                media = "text/csv"
            else:
                body = export_session_markdown(s)
                fname = f"fuzz_{sid}.md"
                media = "text/markdown"

        return Response(
            content=body.encode("utf-8-sig" if fmt == "csv" else "utf-8"),
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    return router
