# -*- coding: utf-8 -*-
"""Web 后端 —— FastAPI 服务，把 fuckai 的能力暴露成 HTTP API。

前后端不分离：FastAPI 既提供 /api/* 接口，也直接托管 web/static 下的单页应用。

    python web.py            # 默认 http://127.0.0.1:8000
    python web.py --port 9000 --host 0.0.0.0
"""
from __future__ import annotations

import argparse
import base64
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from fuckai.client import ChatClient
from fuckai.config import load_config
from fuckai.converters import list_converters
from fuckai.orchestrator import Orchestrator
from fuckai.payloads import Payload, PayloadLibrary, local_group_intro
from fuckai.workbench import Workbench

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


class ParamsModel(BaseModel):
    timeout: int = 120
    max_tokens: int = 1024
    variation_count: int = 3
    sample_size: int = 10


class ModelItem(BaseModel):
    id: str = ""
    name: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.7


class ModelRoleRequest(BaseModel):
    id: str = ""
    role: str = ""


class ChatRequest(BaseModel):
    id: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float | None = None
    system_prompt: str = ""
    messages: list[dict] = Field(default_factory=list)
    max_tokens: int = 0
    context_rounds: int = 6
    history_mode: str = "compress"
    history_chars: int = 300


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


@app.post("/api/params")
def save_params(p: ParamsModel) -> dict:
    """只保存攻击参数（模型部分由模型管理模块维护）。"""
    raw = _read_config_raw()
    raw["attack"] = {
        "timeout": p.timeout,
        "max_tokens": p.max_tokens,
        "variation_count": p.variation_count,
        "sample_size": p.sample_size,
    }
    CONFIG_PATH.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    reset_orchestrator()
    return {"ok": True, "message": "参数已保存"}


# --------------------------------------------------------------------------- #
# 模型管理
# --------------------------------------------------------------------------- #
def _model_dict(raw: dict) -> dict:
    return {
        "id": str(raw.get("id") or ""),
        "name": str(raw.get("name") or raw.get("model") or "未命名模型"),
        "base_url": str(raw.get("base_url") or ""),
        "api_key": str(raw.get("api_key") or ""),
        "model": str(raw.get("model") or ""),
        "temperature": float(raw.get("temperature", 0.7) or 0.0),
    }


def _ensure_models() -> tuple[list[dict], str, str]:
    """读取模型列表；首次使用时把旧的 attack_model / target_model 段迁移进来。"""
    raw = _read_config_raw()
    models = [_model_dict(m) for m in (raw.get("models") or []) if isinstance(m, dict)]
    models = [m for m in models if m["id"]]
    attack_id = str(raw.get("attack_model_id") or "")
    target_id = str(raw.get("target_model_id") or "")
    if models:
        return models, attack_id, target_id

    seeds: list[dict] = []
    roles: list[tuple[str, str]] = []
    for key, role in (("attack_model", "attack"), ("target_model", "target")):
        section = raw.get(key) or {}
        if not (section.get("model") or section.get("base_url")):
            continue
        item = _model_dict({**section, "name": section.get("model") or key})
        item["id"] = "m_" + uuid.uuid4().hex[:8]
        seeds.append(item)
        roles.append((role, item["id"]))
    if not seeds:
        return [], attack_id, target_id

    raw["models"] = seeds
    for role, mid in roles:
        raw["attack_model_id" if role == "attack" else "target_model_id"] = mid
    CONFIG_PATH.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return seeds, raw.get("attack_model_id", ""), raw.get("target_model_id", "")


def _save_models(models: list[dict], attack_id: str, target_id: str) -> None:
    """写回模型列表，并同步 CLI 使用的 attack_model / target_model 两段。"""
    raw = _read_config_raw()
    raw["models"] = models
    raw["attack_model_id"] = attack_id
    raw["target_model_id"] = target_id
    by_id = {m["id"]: m for m in models}
    for key, mid in (("attack_model", attack_id), ("target_model", target_id)):
        m = by_id.get(mid)
        raw[key] = {
            "base_url": m["base_url"] if m else "",
            "api_key": m["api_key"] if m else "",
            "model": m["model"] if m else "",
            "temperature": m["temperature"] if m else 0.0,
        }
    CONFIG_PATH.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    reset_orchestrator()


@app.get("/api/models")
def list_models() -> dict:
    models, attack_id, target_id = _ensure_models()
    return {"models": models, "attack_id": attack_id, "target_id": target_id}


@app.post("/api/models")
def save_model(item: ModelItem) -> dict:
    models, attack_id, target_id = _ensure_models()
    mid = item.id or ("m_" + uuid.uuid4().hex[:8])
    entry = {
        "id": mid,
        "name": item.name.strip() or item.model.strip() or "未命名模型",
        "base_url": item.base_url.strip().rstrip("/"),
        "api_key": item.api_key.strip(),
        "model": item.model.strip(),
        "temperature": float(item.temperature),
    }
    idx = next((i for i, m in enumerate(models) if m["id"] == mid), -1)
    if idx >= 0:
        models[idx] = entry
    else:
        models.append(entry)
    _save_models(models, attack_id, target_id)
    return {"ok": True, "models": models, "attack_id": attack_id, "target_id": target_id}


@app.delete("/api/models/{mid}")
def delete_model(mid: str) -> dict:
    models, attack_id, target_id = _ensure_models()
    models = [m for m in models if m["id"] != mid]
    if attack_id == mid:
        attack_id = ""
    if target_id == mid:
        target_id = ""
    _save_models(models, attack_id, target_id)
    return {"ok": True, "models": models, "attack_id": attack_id, "target_id": target_id}


@app.post("/api/models/role")
def set_model_role(req: ModelRoleRequest) -> dict:
    """把某个模型指定为攻击模型 / 被攻击模型（或取消角色）。"""
    models, attack_id, target_id = _ensure_models()
    if not any(m["id"] == req.id for m in models):
        raise HTTPException(status_code=404, detail="模型不存在")
    role = req.role if req.role in ("attack", "target") else ""
    if role == "attack":
        attack_id = req.id
    elif role == "target":
        target_id = req.id
    else:
        if attack_id == req.id:
            attack_id = ""
        if target_id == req.id:
            target_id = ""
    _save_models(models, attack_id, target_id)
    return {"ok": True, "models": models, "attack_id": attack_id, "target_id": target_id}


def _resolve_model(req: ModelItem) -> dict:
    """用请求里的字段，或用已保存的模型补全连接参数。"""
    base_url = req.base_url.strip()
    api_key = req.api_key.strip()
    model = req.model.strip()
    temperature = float(req.temperature)
    if req.id:
        found = next((m for m in _ensure_models()[0] if m["id"] == req.id), None)
        if found:
            base_url = base_url or found["base_url"]
            api_key = api_key or found["api_key"]
            model = model or found["model"]
    return {
        "base_url": base_url.rstrip("/"),
        "api_key": api_key,
        "model": model,
        "temperature": temperature,
    }


@app.post("/api/models/test")
def test_model(req: ModelItem) -> dict:
    """单独测试某个模型的连通性。"""
    info = _resolve_model(req)
    if not info["base_url"] or not info["model"]:
        return {"ok": False, "error": "缺少 Base URL 或模型名称"}
    atk = _read_config_raw().get("attack") or {}
    client = ChatClient(
        info["base_url"],
        info["api_key"],
        info["model"],
        info["temperature"],
        int(atk.get("timeout", 120) or 120),
        int(atk.get("max_tokens", 1024) or 1024),
    )
    t0 = time.perf_counter()
    try:
        reply = client.ping()
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "base_url": client.base_url,
            "model": client.model,
        }
    return {
        "ok": True,
        "reply": reply[:400],
        "base_url": client.base_url,
        "model": client.model,
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if limit > 0 and len(text) > limit:
        return text[:limit] + "…"
    return text


def _compose_messages(req: ChatRequest) -> list[dict]:
    """按上下文优化策略拼装最终发送给模型的 messages。"""
    hist = [
        m for m in req.messages
        if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()
    ]
    mode = req.history_mode or "compress"
    rounds = max(0, int(req.context_rounds))
    older: list[dict] = []
    if mode == "drop":
        hist = hist[-1:]
    elif mode == "compress":
        keep = max(2, rounds * 2)
        if len(hist) > keep:
            older, hist = hist[:-keep], hist[-keep:]

    sys_chunks: list[str] = []
    if (req.system_prompt or "").strip():
        sys_chunks.append(req.system_prompt.strip())
    if older:
        lines = [
            f"{'用户' if m['role'] == 'user' else '助手'}：{_clip(m['content'], req.history_chars)}"
            for m in older
        ]
        sys_chunks.append("【历史对话摘要（早期轮次已压缩）】\n" + "\n".join(lines))

    out: list[dict] = []
    if sys_chunks:
        out.append({"role": "system", "content": "\n\n".join(sys_chunks)})
    out.extend(hist)
    return out


@app.post("/api/models/chat")
def chat_model(req: ChatRequest) -> dict:
    """与指定模型直接对话（带上下文优化与提示词配置）。"""
    info = _resolve_model(
        ModelItem(
            id=req.id,
            base_url=req.base_url,
            api_key=req.api_key,
            model=req.model,
            temperature=req.temperature if req.temperature is not None else 0.7,
        )
    )
    if not info["base_url"] or not info["model"]:
        raise HTTPException(status_code=400, detail="模型缺少 Base URL 或模型名称")
    atk = _read_config_raw().get("attack") or {}
    client = ChatClient(
        info["base_url"],
        info["api_key"],
        info["model"],
        req.temperature if req.temperature is not None else info["temperature"],
        int(atk.get("timeout", 120) or 120),
        int(req.max_tokens or atk.get("max_tokens", 1024) or 1024),
    )
    composed = _compose_messages(req)
    t0 = time.perf_counter()
    try:
        reply = client.chat(composed)
    except Exception as e:
        return {"ok": False, "error": str(e), "sent": composed}
    return {
        "ok": True,
        "reply": reply,
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        "sent": composed,
    }


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
# 人工工作台
# --------------------------------------------------------------------------- #
_wb: Workbench | None = None
_wb_lock = threading.Lock()


def _workbench() -> Workbench:
    """工作台引擎单例（模板库较大，构造一次即可）。"""
    global _wb
    with _wb_lock:
        if _wb is None:
            _wb = Workbench()
        return _wb


class WorkbenchSearchRequest(BaseModel):
    lang: str = ""
    category: str = ""
    keyword: str = ""
    source_type: str = ""
    limit: int = 60
    offset: int = 0


class WorkbenchGenerateRequest(BaseModel):
    language: str = "zh"
    category: str = "all"
    count: int = 3
    seed: str = "0"
    compose: bool = False
    variant: bool = False
    long: bool = False
    long_length: int = 500
    host: str = ""
    position: str = "start"
    paragraph: int = 0
    transforms: list[str] = Field(default_factory=list)
    custom: str = ""
    locks: dict = Field(default_factory=dict)
    preset: str = "receipt"
    payload: str = ""
    url: str = ""
    tool_name: str = ""


class WorkbenchSerializeRequest(BaseModel):
    samples: list[dict] = Field(default_factory=list)
    batch: dict = Field(default_factory=dict)
    fmt: str = "txt"


class WorkbenchCarrierRequest(BaseModel):
    form: str = "webpage"
    payload: str = ""
    fields: dict = Field(default_factory=dict)


class WorkbenchMyTemplateRequest(BaseModel):
    text: str = ""
    name: str = ""
    source: str = ""


class WorkbenchPdfRequest(BaseModel):
    """字段留空（None）表示沿用 pdfbuild 的默认值。"""

    mode: str = "normal"
    channels: list[str] = Field(default_factory=list)
    title: str | None = None
    body: str | None = None
    visible_footer: str | None = None
    hidden_prompt: str | None = None
    mismatch_footer: str | None = None
    theme: str | None = None
    texture: str | None = None
    strength: int | None = None
    title_size: int | None = None
    body_size: int | None = None
    footer_size: int | None = None
    hidden_size: int | None = None
    padding: int | None = None
    visible_x: int | None = None
    hidden_x: int | None = None
    footer_y: int | None = None
    hidden_y: int | None = None
    source_mode: str = "sample"
    placement: str = "append"
    technique: dict = Field(default_factory=dict)
    base_pdf_b64: str = ""


@app.get("/api/workbench/meta")
def workbench_meta() -> dict:
    """工作台元数据：分类 / 语言 / 三层 / 载荷预设 / PDF 通道库。"""
    return _workbench().meta()


@app.post("/api/workbench/search")
def workbench_search(req: WorkbenchSearchRequest) -> dict:
    """检索模板库（2550 条）。"""
    return _workbench().search(
        lang=req.lang,
        category=req.category,
        keyword=req.keyword,
        source_type=req.source_type,
        limit=max(1, min(300, req.limit)),
        offset=max(0, req.offset),
    )


@app.post("/api/workbench/generate")
def workbench_generate(req: WorkbenchGenerateRequest) -> dict:
    """生成注入样本（单条 / 三层组合 / 变体 / 长文本 / 变换链）。"""
    return _workbench().generate(req.model_dump())


@app.post("/api/workbench/serialize")
def workbench_serialize(req: WorkbenchSerializeRequest) -> dict:
    """把样本导出为 txt / json / jsonl。"""
    text, ext = _workbench().serialize(req.samples, req.fmt, req.batch)
    return {
        "filename": f"injection-samples.{ext}",
        "ext": ext,
        "content": text,
    }


@app.post("/api/workbench/carrier")
def workbench_carrier(req: WorkbenchCarrierRequest) -> dict:
    """把载荷包装成完整仿真载体（网页 / 邮件 / CSV / MCP ...）。"""
    return _workbench().build_carrier(req.form, req.payload, req.fields)


@app.get("/api/workbench/my-templates")
def workbench_my_templates() -> dict:
    """列出用户自有模板。"""
    return {"items": _workbench().list_my_templates()}


@app.post("/api/workbench/my-templates")
def workbench_save_my_template(req: WorkbenchMyTemplateRequest) -> dict:
    """把一条样本存为自有模板（落盘到项目根 my_templates.json）。"""
    try:
        return _workbench().save_my_template(req.text, req.name, req.source)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/workbench/my-templates/{tid}")
def workbench_delete_my_template(tid: str) -> dict:
    """删除一条自有模板。"""
    if not _workbench().delete_my_template(tid):
        raise HTTPException(status_code=404, detail="模板不存在")
    return {"ok": True}


@app.post("/api/workbench/pdf")
def workbench_pdf(req: WorkbenchPdfRequest) -> dict:
    """生成 PDF 样本并回传差异分析结果。"""
    from fuckai import pdfbuild

    spec = {k: v for k, v in req.model_dump().items() if v is not None}
    base_b64 = spec.pop("base_pdf_b64", "")
    if base_b64:
        try:
            spec["base_pdf"] = base64.b64decode(base_b64)
        except Exception:
            raise HTTPException(status_code=400, detail="base_pdf_b64 不是合法的 Base64")
    try:
        built = pdfbuild.build_pdf(spec)
        report = pdfbuild.analyze(built["bytes"], built["spec"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF 生成失败: {e}")
    return {
        "filename": built["filename"],
        "size": len(built["bytes"]),
        "object_count": built["object_count"],
        "page_count": built["page_count"],
        "mode": built["mode"],
        "channels": built["channels"],
        "requested_channels": built["requested_channels"],
        "notes": built["notes"],
        "warnings": built["warnings"],
        "pdf_b64": base64.b64encode(built["bytes"]).decode("ascii"),
        "report": report,
    }


@app.post("/api/workbench/pdf/analyze")
async def workbench_pdf_analyze(file: UploadFile = File(...)) -> dict:
    """上传一份 PDF，做隐藏通道检测（用于验证外部样本）。"""
    from fuckai import pdfbuild

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    try:
        report = pdfbuild.analyze(data, {})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失败: {e}")
    return {"filename": file.filename or "sample.pdf", "report": report}


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
