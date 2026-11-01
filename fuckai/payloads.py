# -*- coding: utf-8 -*-
"""载荷库 —— 本程序自带的 datasets/ 目录全量接入。

把"弹药"分成三类：

  objective  测试话题（问什么）：
      seed_datasets/local/**/*.prompt|*.yaml   AdvBench、airt 分类、garak 探针、0din 注入...
  payload    越狱/注入模板（怎么包）：
      jailbreak/templates/*.yaml               DAN 1~11、AIM、dev_mode、prefix_injection...
      executors/**/*.yaml                      Crescendo 话术、Skeleton Key、FlipAttack...
  converter  变换手法（怎么变形）：见 converters.py

管线：objective →(可选 payload 包装)→ converter → target → scorer → memory
"""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# 话题模板里 objective 的常见占位符名（不同模板叫法不一）
_OBJECTIVE_PARAMS = ("prompt", "conversation_objective", "objective", "request", "message")

# 本地话题集各文件组的简介（key 为 datasets/seed_datasets/local 下的相对目录）
LOCAL_GROUP_INTROS = {
    ".": "AdvBench 有害行为基准(520条) + 系统提示窃取探针",
    "0din": "OWASP 0Din 注入载荷：占位符注入、表格补全诱导",
    "airt": "AIRT 分类话题：非法/恶意软件/信息泄露/诈骗/暴力等 15 类",
    "examples": "多模态/多轮会话攻击示例话题",
    "garak": "LLM 探针：命令注入/XSS/包幻觉/系统提示提取",
}


def local_group_intro(key: str) -> str:
    return LOCAL_GROUP_INTROS.get(key, "")


@dataclass
class Payload:
    """一条载荷：objective 或模板。"""
    kind: str            # "objective" | "jailbreak" | "executor"
    source: str          # 来源（相对 datasets 的路径）
    name: str            # 显示名
    value: str           # objective 文本 或 模板全文（含 {{ 参数 }} 占位符）
    harm: str = ""       # harm_categories
    params: list = field(default_factory=list)   # 模板参数（objective 类为空）

    @property
    def is_template(self) -> bool:
        return self.kind in ("jailbreak", "executor") and bool(self.params)

    def compose(self, objective: str) -> str:
        """把 objective 填进模板占位符（本程序 的 template rendering 步骤）。"""
        if not self.is_template:
            return objective
        text = self.value
        for key in _OBJECTIVE_PARAMS:
            text = text.replace("{{ " + key + " }}", objective)
            text = text.replace("{{" + key + "}}", objective)
        # 其余未提供的占位符直接剔除，避免发给目标造成困惑
        import re
        return re.sub(r"\{\{\s*\w+\s*\}\}", "", text).strip()


def _datasets_dir() -> Path:
    """项目内自带的 datasets 目录（完整隔离、全相对路径）。"""
    base = Path(__file__).resolve().parent.parent / "datasets"
    if not base.exists():
        raise RuntimeError("找不到 datasets 目录：请确保 datasets/ 位于项目根目录")
    return base


def _parse_seed_file(path: Path, rel: str) -> list[Payload]:
    """解析本程序 seed 数据集文件（.prompt/.yaml 都是 YAML seed 格式）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:
        return []
    if not isinstance(data, dict) or not data.get("seeds"):
        return []
    ds_name = data.get("dataset_name") or path.stem
    out = []
    for seed in data["seeds"]:
        if not isinstance(seed, dict) or not seed.get("value"):
            continue
        harm = ", ".join(seed.get("harm_categories") or [])
        out.append(Payload(kind="objective", source=rel, name=ds_name,
                           value=str(seed["value"]).strip(), harm=harm))
    return out


class PayloadLibrary:
    """datasets 全量载荷库（懒加载）。"""

    def __init__(self):
        self._local_groups: dict[str, list[Payload]] | None = None
        self._jailbreaks: list[Payload] | None = None
        self._executors: list[Payload] | None = None

    # ---------------- 本地目标集 ----------------
    def local_groups(self) -> dict[str, list[Payload]]:
        """{数据集相对路径 -> [Payload]}，来自 seed_datasets/local/。"""
        if self._local_groups is not None:
            return self._local_groups
        base = _datasets_dir() / "seed_datasets" / "local"
        groups: dict[str, list[Payload]] = {}
        if base.exists():
            for path in sorted(base.rglob("*")):
                if path.suffix.lower() not in (".prompt", ".yaml", ".yml"):
                    continue
                rel = path.relative_to(base).as_posix()
                items = _parse_seed_file(path, rel)
                if items:
                    key = str(path.parent.relative_to(base).as_posix()) or "."
                    groups.setdefault(key, []).extend(items)
        self._local_groups = groups
        return groups

    # ---------------- 越狱模板 ----------------
    def jailbreaks(self) -> list[Payload]:
        if self._jailbreaks is not None:
            return self._jailbreaks
        self._jailbreaks = self._load_templates("jailbreak", "jailbreak")
        return self._jailbreaks

    # ---------------- 执行器话术 ----------------
    def executors(self) -> list[Payload]:
        if self._executors is not None:
            return self._executors
        self._executors = self._load_templates("executors", "executor")
        return self._executors

    def _load_templates(self, subdir: str, kind: str) -> list[Payload]:
        base = _datasets_dir() / subdir
        items: list[Payload] = []
        if not base.exists():
            return items
        for path in sorted(base.rglob("*.yaml")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
            except Exception:
                continue
            if not isinstance(data, dict) or not data.get("value"):
                continue
            items.append(Payload(
                kind=kind,
                source=path.relative_to(_datasets_dir()).as_posix(),
                name=data.get("name") or path.stem,
                value=str(data["value"]),
                params=data.get("parameters") or [],
            ))
        return items

    # ---------------- 统计 ----------------
    def stats(self) -> dict:
        local = self.local_groups()
        return {
            "本地话题集": f"{sum(len(v) for v in local.values())} 条 / {len(local)} 个文件组",
            "提示词模板": f"{len(self.jailbreaks())} 个",
            "执行器话术": f"{len(self.executors())} 个",
        }
