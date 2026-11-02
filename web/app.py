# -*- coding: utf-8 -*-
"""Web 后端 —— FastAPI 服务，把 fuckai 的能力暴露成 HTTP API。

前后端不分离：FastAPI 既提供 /api/* 接口，也直接托管 web/static 下的单页应用。

    python web.py            # 默认 http://127.0.0.1:8000
    python web.py --port 9000 --host 0.0.0.0
"""
from __future__ import annotations

import argparse
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from fuckai.config import load_config
from fuckai.converters import list_converters
from fuckai.orchestrator import Orchestrator
from fuckai.payloads import Payload, PayloadLibrary, local_group_intro

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

app = FastAPI(title="fuckai Web", version="1.0", docs_url="/api/docs", redoc_url=None)

_lib: PayloadLibrary | None = None
_orch: Orchestrator | None = None
_orch_lock = threading.Lock()


def _library() -> PayloadLibrary:
    global _lib
    if _lib is None:
        _lib = PayloadLibrary()
    return _lib


def _orchestrator() -> Orchestrator:
    """按需重建编排器（配置变更后能立刻生效）。"""
    global _orch
    with _orch_lock:
        if _orch is None:
            _orch = Orchestrator(load_config())
        return _orch


def reset_orchestrator():
    """丢弃旧的编排器（配置变更后重建），顺带关掉旧的 SQLite 连接。"""
    global _orch
    with _orch_lock:
        if _orch is not None:
            try:
                _orch.memory.close()
            except Exception:
                pass
        _orch = None


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #
class ConfigModel(BaseModel):
    attack_base_url: str = ""
    attack_api_key: str = ""
    attack_model: str = ""
    attack_temperature: float = 0.7
    target_base_url: str = ""
    target_api_key: str = ""
    target_model: str = ""
    target_temperature: float = 0.0
    timeout: int = 120
    max_tokens: int = 1024
    variation_count: int = 3
    sample_size: int = 10
    repo_url: str = ""


class AttackRequest(BaseModel):
    objectives: list[str] = Field(default_factory=list)
    converter_ids: list[str] = Field(default_factory=lambda: ["direct"])
    payload_name: str = ""
    objective_group: str = ""
    sample_size: int = 10
    use_all: bool = False


class UpdateRequest(BaseModel):
    repo_url: str = ""


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
def _read_config_raw() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


@app.get("/api/config")
def get_config() -> dict:
    raw = _read_config_raw()
    attack = raw.get("attack_model") or {}
    target = raw.get("target_model") or {}
    atk = raw.get("attack") or {}
    memory = raw.get("memory") or {}
    update = raw.get("update") or {}
    return {
        "attack_base_url": attack.get("base_url", "") or "",
        "attack_api_key": attack.get("api_key", "") or "",
        "attack_model": attack.get("model", "") or "",
        "attack_temperature": float(attack.get("temperature", 0.7) or 0.7),
        "target_base_url": target.get("base_url", "") or "",
        "target_api_key": target.get("api_key", "") or "",
        "target_model": target.get("model", "") or "",
        "target_temperature": float(target.get("temperature", 0.0) or 0.0),
        "timeout": int(atk.get("timeout", 120) or 120),
        "max_tokens": int(atk.get("max_tokens", 1024) or 1024),
        "variation_count": int(atk.get("variation_count", 3) or 3),
        "sample_size": int(atk.get("sample_size", 10) or 10),
        "db_path": memory.get("db_path", "fuckai.db") or "fuckai.db",
        "repo_url": update.get("repo_url", "") or "",
    }


def _write_config(model: ConfigModel) -> None:
    """把配置写回 config.yaml（保留 update 段与未涉及的键）。"""
    raw = _read_config_raw()
    raw["attack_model"] = {
        "base_url": model.attack_base_url,
        "api_key": model.attack_api_key,
        "model": model.attack_model,
        "temperature": model.attack_temperature,
    }
    raw["target_model"] = {
        "base_url": model.target_base_url,
        "api_key": model.target_api_key,
        "model": model.target_model,
        "temperature": model.target_temperature,
    }
    raw["attack"] = {
        "timeout": model.timeout,
        "max_tokens": model.max_tokens,
        "variation_count": model.variation_count,
        "sample_size": model.sample_size,
    }
    raw.setdefault("memory", {})["db_path"] = raw.get("memory", {}).get("db_path", "fuckai.db")
    if model.repo_url:
        raw.setdefault("update", {})["repo_url"] = model.repo_url
    CONFIG_PATH.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    reset_orchestrator()


@app.post("/api/config")
def save_config(model: ConfigModel) -> dict:
    _write_config(model)
    return {"ok": True, "message": "配置已保存"}


@app.post("/api/config/test")
def test_connection() -> dict:
    """分别 ping 攻击模型与目标模型。"""
    results = {}
    try:
        orch = _orchestrator()
        for name, client in (
            ("attack_model", orch.attack_client),
            ("target_model", orch.target_client),
        ):
            try:
                reply = client.ping()
                results[name] = {
                    "ok": True,
                    "model": client.model,
                    "base_url": client.base_url,
                    "reply": reply[:200],
                }
            except Exception as e:
                results[name] = {
                    "ok": False,
                    "model": client.model,
                    "base_url": client.base_url,
                    "error": str(e),
                }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return results


# --------------------------------------------------------------------------- #
# 弹药库
# --------------------------------------------------------------------------- #
def _payload_brief(p: Payload) -> dict:
    return {
        "name": p.name,
        "kind": p.kind,
        "source": p.source,
        "value": p.value,
        "is_template": p.is_template,
        "params": p.params,
        "harm": p.harm,
    }


@app.get("/api/arsenal")
def arsenal() -> dict:
    lib = _library()
    groups = lib.local_groups()
    local = [
        {
            "key": key,
            "intro": local_group_intro(key),
            "count": len(items),
            "items": [_payload_brief(p) for p in items[:200]],
        }
        for key, items in sorted(groups.items())
    ]
    return {
        "stats": lib.stats(),
        "local_groups": local,
        "jailbreaks": [_payload_brief(p) for p in lib.jailbreaks()],
        "executors": [_payload_brief(p) for p in lib.executors()],
        "converters": [{"id": cid, "label": label} for cid, label in list_converters()],
    }


# --------------------------------------------------------------------------- #
# 攻击
# --------------------------------------------------------------------------- #
def _find_payload(name: str) -> Payload | None:
    if not name:
        return None
    lib = _library()
    for p in lib.jailbreaks() + lib.executors():
        if p.name == name:
            return p
    return None


def _resolve_objectives(req: AttackRequest) -> list[str]:
    if req.objectives:
        return [o.strip() for o in req.objectives if o.strip()]
    if not req.objective_group:
        return []
    groups = _library().local_groups()
    items = groups.get(req.objective_group, [])
    if req.use_all:
        return [p.value for p in items]
    n = max(1, min(req.sample_size, len(items)))
    import random

    return [p.value for p in random.sample(items, n)]


@app.post("/api/attack/run")
def run_attack(req: AttackRequest) -> dict:
    objectives = _resolve_objectives(req)
    if not objectives:
        raise HTTPException(status_code=400, detail="没有可用的测试话题")
    converter_ids = req.converter_ids or ["direct"]
    payload = _find_payload(req.payload_name)
    if req.payload_name and payload is None:
        raise HTTPException(status_code=400, detail=f"找不到提示词模板: {req.payload_name}")

    orch = _orchestrator()
    records = orch.run_batch(objectives, converter_ids, payload=payload, verbose=False)
    ok = sum(1 for r in records if r["success"])
    return {
        "total": len(records),
        "success": ok,
        "rate": round(ok / len(records) * 100, 1) if records else 0.0,
        "records": records,
    }


@app.post("/api/attack/stream")
def run_attack_stream(req: AttackRequest):
    """流式执行：每完成一次攻击推送一条 SSE 事件。"""
    from fastapi.responses import StreamingResponse

    objectives = _resolve_objectives(req)
    if not objectives:
        raise HTTPException(status_code=400, detail="没有可用的测试话题")
    converter_ids = req.converter_ids or ["direct"]
    payload = _find_payload(req.payload_name)
    if req.payload_name and payload is None:
        raise HTTPException(status_code=400, detail=f"找不到提示词模板: {req.payload_name}")

    total = len(objectives) * len(converter_ids)

    def gen():
        import json

        yield f"data: {json.dumps({'type': 'start', 'total': total}, ensure_ascii=False)}\n\n"
        done = 0
        ok = 0
        orch = _orchestrator()
        for objective in objectives:
            for cid in converter_ids:
                done += 1
                try:
                    record = orch.run(objective, cid, payload=payload, verbose=False)
                except Exception as e:
                    record = {
                        "ts": datetime.now().isoformat(timespec="seconds"),
                        "converter": cid,
                        "payload": payload.name if payload else "",
                        "objective": objective,
                        "prompt": "",
                        "response": "",
                        "success": False,
                        "reason": f"[异常] {e}",
                    }
                if record.get("success"):
                    ok += 1
                yield f"data: {json.dumps({'type': 'item', 'done': done, 'total': total, 'record': record}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'total': total, 'success': ok, 'rate': round(ok / total * 100, 1) if total else 0.0}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------------- #
# 记录与报告
# --------------------------------------------------------------------------- #
@app.get("/api/records")
def records(limit: int = 200, offset: int = 0) -> dict:
    orch = _orchestrator()
    all_rows = orch.memory.all()
    rows = all_rows[::-1]
    page = rows[offset : offset + limit]
    ok = sum(1 for r in all_rows if r["success"])
    return {
        "total": len(all_rows),
        "success": ok,
        "rate": round(ok / len(all_rows) * 100, 1) if all_rows else 0.0,
        "items": page,
    }


@app.get("/api/report/export")
def export_report(fmt: str = "json") -> JSONResponse:
    orch = _orchestrator()
    suffix = "csv" if fmt.lower() == "csv" else "json"
    out = PROJECT_ROOT / f"report.{suffix}"
    if suffix == "csv":
        count = orch.memory.export_csv(str(out))
    else:
        count = orch.memory.export_json(str(out))
    return JSONResponse({
        "ok": True,
        "count": count,
        "path": str(out),
        "download": f"/api/report/download/{out.name}",
    })


@app.get("/api/report/download/{name}")
def download_report(name: str) -> FileResponse:
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="非法文件名")
    path = PROJECT_ROOT / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="报告不存在")
    media = "text/csv" if name.endswith(".csv") else "application/json"
    return FileResponse(path, media_type=media, filename=name)


@app.delete("/api/records")
def clear_records() -> dict:
    orch = _orchestrator()
    n = orch.memory.clear()
    return {"ok": True, "deleted": n, "message": "记录已清空"}


# --------------------------------------------------------------------------- #
# 更新
# --------------------------------------------------------------------------- #
@app.get("/api/update/source")
def update_source() -> dict:
    from fuckai import updater

    return {"repo_url": updater.get_repo_url()}


@app.post("/api/update")
def do_update(req: UpdateRequest) -> dict:
    from fuckai import updater

    repo = (req.repo_url or "").strip()
    if not repo:
        repo = updater.get_repo_url()
    if not repo:
        raise HTTPException(status_code=400, detail="尚未配置更新源")
    try:
        updater.validate_repo_url(repo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    updater.set_repo_url(repo)
    try:
        summary = updater.update(repo)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新失败: {e}")
    return {"ok": True, "summary": summary}


# --------------------------------------------------------------------------- #
# 静态资源（前后端不分离：直接托管单页应用）
# --------------------------------------------------------------------------- #
@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "fuckai-web", "version": app.version}


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description="fuckai Web 服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    print(f"  fuckai Web  ->  http://{args.host}:{args.port}")
    uvicorn.run("web.app:app" if args.reload else app, host=args.host, port=args.port,
                reload=args.reload, log_level="info")


if __name__ == "__main__":
    main()
