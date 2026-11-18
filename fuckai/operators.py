# -*- coding: utf-8 -*-
"""算子（Operator）注册表 —— 插件化的变换器。

以前「把目标请求变形后再发给目标模型」这件事是写死在 converters.py 里的
if-else 分派。现在改成注册表机制：

* 内置算子（direct / base64 / atbash / tense ...）在 converters.py 里注册；
* 外部插件放在项目根目录 plugins/ 下，每个 .py 文件导出 OPERATORS 列表，
  或导出一个 register(api) 函数，启动时自动加载；
* 界面上的变换手法列表直接来自注册表，插件算子与内置算子平级展示，
  勾选后走同一套 converter_ids 管线，不用改核心代码。

插件里算子的函数签名统一为 fn(objective: str, ctx: OperatorContext) -> str：

    ctx.attack           攻击模型客户端（未配置时为 None）
    ctx.variation_count  变体数量（variation 类算子用）

插件示例见 plugins/text_ops.py。
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# 算子实现：fn(objective, ctx) -> 变形后的 prompt
OperatorFn = Callable[[str, "OperatorContext"], str]


@dataclass
class OperatorContext:
    """算子运行时上下文。"""

    attack: Any = None          # ChatClient，未配置攻击模型时为 None
    variation_count: int = 1    # 变体数量


@dataclass
class Operator:
    """一个变换器算子。"""

    id: str
    label: str = ""
    intro: str = ""             # 界面悬停简介
    kind: str = "builtin"       # builtin / plain / cipher / llm / plugin
    source: str = ""            # 来源：内置模板文件名 或 插件文件名
    fn: OperatorFn | None = None
    tags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "intro": self.intro,
            "kind": self.kind,
            "source": self.source,
        }


_REGISTRY: dict[str, Operator] = {}


def register_operator(op: Operator, *, override: bool = True) -> Operator:
    """把算子登记进注册表。同名算子后注册的覆盖先注册的（插件可覆盖内置）。"""
    if not op.id:
        raise ValueError("算子必须有 id")
    if not override and op.id in _REGISTRY:
        return _REGISTRY[op.id]
    _REGISTRY[op.id] = op
    return op


def get_operator(op_id: str) -> Operator | None:
    return _REGISTRY.get(op_id)


def list_operators() -> list[Operator]:
    """按注册顺序返回全部算子。"""
    return list(_REGISTRY.values())


def operator_meta() -> list[dict]:
    """给 /api/arsenal 用的算子元数据。"""
    return [op.to_dict() for op in list_operators()]


class _PluginAPI:
    """交给插件 register() 用的门面对象。"""

    def __init__(self, source: str):
        self.source = source

    def operator(self, id: str, label: str, intro: str = "", fn: OperatorFn | None = None,
                 kind: str = "plugin") -> Operator:
        return register_operator(
            Operator(id=id, label=label, intro=intro, kind=kind, source=self.source, fn=fn)
        )


def _plugin_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "plugins"


def _register_from_module(module: Any, source: str) -> None:
    """把一个插件模块里的算子登记进注册表。"""
    api = _PluginAPI(source)
    for item in getattr(module, "OPERATORS", []) or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        api.operator(
            id=str(item["id"]),
            label=str(item.get("label") or item["id"]),
            intro=str(item.get("intro") or ""),
            fn=item.get("fn"),
        )
    register_fn = getattr(module, "register", None)
    if callable(register_fn):
        register_fn(api)


def load_plugins(plugin_dir: Path | None = None) -> list[str]:
    """加载 plugins/ 下的外部算子插件，返回成功加载的文件名列表。

    单个插件出错不影响其它插件，也不会让服务起不来。
    """
    base = plugin_dir or _plugin_dir()
    loaded: list[str] = []
    if not base.exists():
        return loaded
    for path in sorted(base.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"fuckai_operator_plugin_{path.stem}", path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _register_from_module(module, path.name)
        except Exception:
            continue
        loaded.append(path.name)
    return loaded
