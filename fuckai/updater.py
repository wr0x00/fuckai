# -*- coding: utf-8 -*-
"""GitHub 自动更新模块。

原理：从配置的 GitHub 仓库下载最新源码 zip，解压后覆盖本项目代码目录
（fuckai/、datasets/、run.py、README.md 等），但保留用户数据：
    config.yaml  —— 你的模型配置
    fuckai.db    —— 历史测试记录
"""
import io
import json
import os
import re
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
# 更新时被覆盖的内容（用户数据不在其中）
UPDATE_ITEMS = ("datasets", "fuckai", "web", "run.py", "web.py", "config_example.yaml", "README.md")
# 更新时绝不触碰的用户数据
PROTECTED = {"config.yaml", "fuckai.db"}

_UA = {"User-Agent": "fuckai-updater"}


def _clean(value) -> str:
    """清掉地址里混入的转义符/引号（历史上写坏的 config.yaml 形如 \"https://...\"）。"""
    s = str(value or "").strip().replace("\\", "").strip()
    return s.strip("\"'").strip()


def get_repo_url() -> str:
    """从 config.yaml 读取 update.repo_url。"""
    if not CONFIG_PATH.exists():
        return ""
    import yaml
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return _clean((data.get("update") or {}).get("repo_url", ""))


def set_repo_url(url: str):
    """把 repo_url 写回 config.yaml 的 update 段（保留其余注释与内容）。"""
    url = _clean(url)
    if not url:
        return
    value = '"' + url.replace("\\", "\\\\").replace('"', '\\"') + '"'
    lines = (
        CONFIG_PATH.read_text(encoding="utf-8").splitlines()
        if CONFIG_PATH.exists()
        else []
    )

    update_idx = None
    for i, line in enumerate(lines):
        if re.match(r"^update\s*:", line):
            update_idx = i
            break

    if update_idx is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines += ["update:", f"  repo_url: {value}"]
    else:
        # update 块的范围：其后所有缩进行，直到遇到下一个顶格非空行
        end = update_idx + 1
        while end < len(lines):
            line = lines[end]
            if line.strip() and not line[0].isspace():
                break
            end += 1
        block = lines[update_idx + 1 : end]

        repo_idx = None
        for j, line in enumerate(block):
            if re.match(r"^\s+repo_url\s*:", line):
                repo_idx = j
                break
        if repo_idx is None:
            indent = "  "
            for line in block:
                m = re.match(r"^(\s+)\S", line)
                if m:
                    indent = m.group(1)
                    break
            block.insert(0, f"{indent}repo_url: {value}")
        else:
            indent = re.match(r"^(\s*)", block[repo_idx]).group(1)
            block[repo_idx] = f"{indent}repo_url: {value}"
        lines[update_idx + 1 : end] = block

    CONFIG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_repo_url(repo_url: str) -> str:
    """校验仓库地址是否合法，合法则返回 owner/repo，否则抛 ValueError。"""
    return _slug_of(repo_url)


def _slug_of(repo_url: str) -> str:
    """从仓库地址提取 owner/repo。"""
    s = _clean(repo_url).rstrip("/")
    if s.endswith(".git"):
        s = s[:-4]
    m = re.match(r"^(?:https?://)?(?:www\.)?github\.com/([\w.-]+/[\w.-]+)$", s, re.I)
    if m:
        return m.group(1)
    m = re.fullmatch(r"([\w.-]+/[\w.-]+)", s)
    if m:
        return m.group(1)
    raise ValueError(f"不是有效的 GitHub 仓库地址: {repo_url}")


def _candidate_branches(slug: str) -> list[str]:
    """候选分支：优先用 API 查默认分支，查不到再试 main/master。"""
    branches: list[str] = []
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{slug}",
            headers={**_UA, "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            default = (json.load(resp) or {}).get("default_branch")
        if default:
            branches.append(str(default))
    except Exception:
        pass
    for b in ("main", "master"):
        if b not in branches:
            branches.append(b)
    return branches


def _download_zip(repo_url: str) -> bytes:
    """下载仓库的 zip 源码包。"""
    slug = _slug_of(repo_url)
    last_err = None
    for branch in _candidate_branches(slug):
        url = f"https://github.com/{slug}/archive/refs/heads/{branch}.zip"
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            if resp.status == 200 and data[:2] == b"PK":
                return data
            last_err = RuntimeError(f"HTTP {resp.status}，返回内容不是 zip")
        except Exception as e:
            last_err = e
    raise RuntimeError(f"下载失败 ({slug}): {last_err}")


def _safe_extract(zf: zipfile.ZipFile, dest: Path):
    """解压到 dest，拒绝越界路径（zip slip）。"""
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ".." in Path(name).parts:
            raise RuntimeError(f"压缩包包含非法路径: {info.filename}")
    zf.extractall(dest)


def _detect_root(tmp: Path) -> Path:
    """找到解压后的项目根目录（zip 里那层 xxx-branch/）。"""
    entries = list(tmp.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    for entry in entries:
        if entry.is_dir() and (entry / "fuckai").is_dir():
            return entry
    return tmp


def _remove(path: Path):
    """删除文件或目录（rmtree 只能删目录，文件必须用 unlink）。"""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        try:
            path.unlink()
        except OSError:
            pass


def _swap(src: Path, dst: Path):
    """用 src 替换 dst：先落到暂存目录，再改名顶上，出错可回滚。"""
    staging = dst.parent / f".{dst.name}.new"
    backup = dst.parent / f".{dst.name}.old"
    _remove(staging)
    _remove(backup)
    ok = False
    try:
        if src.is_dir():
            shutil.copytree(
                src, staging, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
            )
        else:
            shutil.copy2(src, staging)
        if dst.exists():
            os.rename(dst, backup)
        os.rename(staging, dst)
        ok = True
    finally:
        if ok:
            _remove(backup)
        elif not dst.exists() and backup.exists():
            os.rename(backup, dst)  # 回滚
        _remove(staging)


def _cleanup_stale():
    """清理上次更新中断留下的 .xxx.new / .xxx.old（只针对已知更新项）。"""
    for item in UPDATE_ITEMS:
        for suffix in (".new", ".old"):
            _remove(PROJECT_ROOT / f".{item}{suffix}")


def update(repo_url: str) -> str:
    """执行更新，返回摘要文本。"""
    data = _download_zip(repo_url)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            _safe_extract(zf, tmp_path)
        src_root = _detect_root(tmp_path)

        if not (src_root / "fuckai").is_dir() and not (src_root / "run.py").exists():
            raise RuntimeError("下载到的内容与本项目结构不匹配，已中止更新")

        _cleanup_stale()
        updated, missing = [], []
        for item in UPDATE_ITEMS:
            src = src_root / item
            dst = PROJECT_ROOT / item
            if not src.exists():
                missing.append(item)
                continue
            _swap(src, dst)
            updated.append(item)

        # 确认用户数据仍在（本就不在 UPDATE_ITEMS 中，双保险）
        skipped = [p for p in sorted(PROTECTED) if (PROJECT_ROOT / p).exists()]

    lines = [f"已更新: {', '.join(updated) or '无'}"]
    if missing:
        lines.append(f"仓库中不存在(已跳过): {', '.join(missing)}")
    lines.append(f"保留用户数据: {', '.join(skipped) or '无'}")
    return " | ".join(lines)
