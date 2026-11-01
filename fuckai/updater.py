# -*- coding: utf-8 -*-
"""GitHub 自动更新模块。

原理：从配置的 GitHub 仓库下载最新源码 zip，解压后覆盖本项目代码目录
（fuckai/、datasets/、run.py 等），但保留用户数据：
    config.yaml  —— 你的模型配置
    fuckai.db    —— 历史测试记录
"""
import io
import re
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
# 更新时被覆盖的内容（用户数据不在其中）
UPDATE_ITEMS = ("datasets", "fuckai", "run.py", "config_example.yaml")
# 更新时绝不触碰的用户数据
PROTECTED = {"config.yaml", "fuckai.db"}

_UA = {"User-Agent": "fuckai-updater"}


def get_repo_url() -> str:
    """从 config.yaml 读取 update.repo_url。"""
    if not CONFIG_PATH.exists():
        return ""
    import yaml
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return str((data.get("update") or {}).get("repo_url", "") or "")


def set_repo_url(url: str):
    """把 repo_url 写回 config.yaml 的 update 段（保留其余注释，简单文本处理）。"""
    url = url.strip()
    if not CONFIG_PATH.exists():
        text = ""
    else:
        text = CONFIG_PATH.read_text(encoding="utf-8")

    if re.search(r"^update:", text, flags=re.M):
        if re.search(r"^\s+repo_url:", text, flags=re.M):
            text = re.sub(r"^(\s+repo_url:).*$", rf"\1 \"{url}\"", text, flags=re.M)
        else:
            text = re.sub(r"^update:\s*$", f"update:\n  repo_url: \"{url}\"", text, flags=re.M)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += f"\nupdate:\n  repo_url: \"{url}\"\n"
    CONFIG_PATH.write_text(text, encoding="utf-8")


def _download_zip(repo_url: str) -> bytes:
    """下载仓库默认分支的 zip（github.com/owner/repo）。"""
    repo = repo_url.rstrip("/").removesuffix(".git")
    m = re.match(r"^(?:https?://)?github\.com/([\w.-]+/[\w.-]+)$", repo)
    if not m:
        raise ValueError(f"不是有效的 GitHub 仓库地址: {repo_url}")
    slug = m.group(1)
    last_err = None
    for branch in ("main", "master"):
        url = f"https://github.com/{slug}/archive/refs/heads/{branch}.zip"
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=120) as resp:
                if resp.status == 200:
                    return resp.read()
        except Exception as e:
            last_err = e
    raise RuntimeError(f"下载失败 ({slug}): {last_err}")


def update(repo_url: str) -> str:
    """执行更新，返回摘要文本。"""
    data = _download_zip(repo_url)
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(tmp)
        # zip 内有一层根目录 fuckai-<branch>/
        entries = [p for p in Path(tmp).iterdir()]
        src_root = entries[0] if len(entries) == 1 and entries[0].is_dir() else Path(tmp)

        updated, skipped = [], []
        for item in UPDATE_ITEMS:
            src = src_root / item
            dst = PROJECT_ROOT / item
            if not src.exists():
                continue
            if dst.exists():
                if dst.is_dir():
                    shutil.rmtree(dst, ignore_errors=True)
                else:
                    dst.unlink()
            if src.is_dir():
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(src, dst)
            updated.append(item)

        # 确认用户数据仍在（本就不在 UPDATE_ITEMS 中，双保险）
        for p in PROTECTED:
            if (PROJECT_ROOT / p).exists():
                skipped.append(p)

    return f"已更新: {', '.join(updated) or '无'} | 保留用户数据: {', '.join(skipped) or '无'}"
