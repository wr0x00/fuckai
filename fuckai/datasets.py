# -*- coding: utf-8 -*-
"""数据集加载 —— 对应本程序的 datasets 模块。

直接复用已安装本程序 的攻击模板库：
    datasets/converters/*.yaml
每个 YAML 的核心字段：
    name / description / parameters / value
其中 value 是 prompt 模板，含 {{ 参数 }} 占位符（本程序 用 jinja2 渲染，
这里简化成字符串替换 —— 对理解机制完全等价）。
"""
from pathlib import Path

import yaml


def _find_datasets_dir() -> Path | None:
    """项目内自带的 datasets/converters 目录（完整隔离、全相对路径）。"""
    base = Path(__file__).resolve().parent.parent / "datasets" / "converters"
    return base if base.exists() else None


class ConverterTemplate:
    """一个本程序 攻击模板。"""

    def __init__(self, path: Path):
        self.path = path
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        self.name: str = data.get("name", path.stem)
        self.description: str = (data.get("description") or "").strip()
        self.parameters: list[str] = data.get("parameters") or []
        self.value: str = data.get("value") or ""

    def render(self, **params) -> str:
        """把 {{ param }} 占位符替换成实际值（本程序 的 template rendering 步骤）。"""
        text = self.value
        for key, val in params.items():
            text = text.replace("{{ " + key + " }}", str(val))
            text = text.replace("{{" + key + "}}", str(val))
        return text.strip()


# ---------------------------------------------------------------- #
# 变换器登记表：id -> (本程序 模板文件, 模板参数, 是否用 begin/end 标签包住 objective)
# 说明见 converters.py
# ---------------------------------------------------------------- #
LLM_TEMPLATES: dict[str, dict] = {
    "tense":      {"yaml": "tense_converter.yaml",       "params": {"tense": "past"},          "tags": False,
                   "label": "时态改写（过去时越狱, arXiv:2407.11969）"},
    "tone":       {"yaml": "tone_converter.yaml",        "params": {"tone": "angry"},          "tags": False,
                   "label": "语气改写"},
    "translation":{"yaml": "translation_converter.yaml", "params": {"language": "Low German"}, "tags": True,
                   "label": "翻译为低地德语（低资源语言绕过）"},
    "variation":  {"yaml": "variation_converter.yaml",   "params": {"number_iterations": 1},   "tags": True,
                   "label": "同义变体改写"},
    "academic":   {"yaml": "academic_science_converter.yaml",  "params": {}, "tags": False,
                   "label": "学术语境伪装（作业/考试式）"},
    "research":   {"yaml": "research_science_converter.yaml",  "params": {}, "tags": False,
                   "label": "科研语境伪装（研究问题/假设）"},
    "technical":  {"yaml": "technical_science_converter.yaml", "params": {}, "tags": False,
                   "label": "技术术语伪装"},
    "math_word":  {"yaml": "math_science_converter.yaml",      "params": {}, "tags": False,
                   "label": "数学应用题伪装"},
    "smiles":     {"yaml": "smiles_science_converter.yaml",    "params": {}, "tags": False,
                   "label": "SMILES 化学式伪装"},
    "mathprompt": {"yaml": "math_prompt_converter.yaml",       "params": {}, "tags": False,
                   "label": "MathPrompt：符号数学编码（inline {{prompt}} 模板）"},
}

CIPHER_TEMPLATES: dict[str, dict] = {
    "atbash": {"yaml": "atbash_description.yaml", "params": {}, "tags": False,
               "label": "Atbash 密码（倒序字母表）"},
    "caesar": {"yaml": "caesar_description.yaml", "params": {"offset": 3}, "tags": False,
               "label": "凯撒密码（偏移 3）"},
    "morse":  {"yaml": "morse_description.yaml",  "params": {}, "tags": False,
               "label": "摩尔斯电码"},
}


def load_template(template_id: str) -> ConverterTemplate:
    """按登记表 id 加载对应 YAML 模板。"""
    entry = LLM_TEMPLATES.get(template_id) or CIPHER_TEMPLATES.get(template_id)
    if entry is None:
        raise KeyError(f"未登记的模板: {template_id}")
    base = _find_datasets_dir()
    if base is None:
        raise RuntimeError("找不到 datasets/converters 目录 —— 请确保 datasets/ 位于项目根目录")
    return ConverterTemplate(base / entry["yaml"])
