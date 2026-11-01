# -*- coding: utf-8 -*-
"""配置加载（对应本程序的 CentralMemory / 环境变量配置体系）。"""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


@dataclass
class ModelConfig:
    """一个 OpenAI 兼容端点的配置（攻击模型和目标模型共用这个结构）。"""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.0


@dataclass
class AttackConfig:
    timeout: int = 180
    max_tokens: int = 1024
    variation_count: int = 3
    sample_size: int = 10


@dataclass
class AppConfig:
    attack_model: ModelConfig = field(default_factory=ModelConfig)
    target_model: ModelConfig = field(default_factory=ModelConfig)
    attack: AttackConfig = field(default_factory=AttackConfig)
    db_path: str = "fuckai.db"


def load_config(path: Path | None = None) -> AppConfig:
    path = path or DEFAULT_CONFIG_PATH
    raw: dict = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    cfg = AppConfig()
    for key, model_cfg in (("attack_model", cfg.attack_model), ("target_model", cfg.target_model)):
        section = raw.get(key) or {}
        model_cfg.base_url = section.get("base_url", model_cfg.base_url)
        model_cfg.api_key = str(section.get("api_key", model_cfg.api_key))
        model_cfg.model = section.get("model", model_cfg.model)
        model_cfg.temperature = float(section.get("temperature", model_cfg.temperature))

    attack = raw.get("attack") or {}
    cfg.attack.timeout = int(attack.get("timeout", cfg.attack.timeout))
    cfg.attack.max_tokens = int(attack.get("max_tokens", cfg.attack.max_tokens))
    cfg.attack.variation_count = int(attack.get("variation_count", cfg.attack.variation_count))
    cfg.attack.sample_size = int(attack.get("sample_size", cfg.attack.sample_size))

    memory = raw.get("memory") or {}
    cfg.db_path = memory.get("db_path", cfg.db_path)
    if not Path(cfg.db_path).is_absolute():
        cfg.db_path = str(PROJECT_ROOT / cfg.db_path)
    return cfg
