# -*- coding: utf-8 -*-
"""多维分析器 —— 把攻击明细记录聚合成多维统计。

所有"算数字"的逻辑都收在这个文件里，前端要加新图表 / 后端要加新维度，
只动这里就行，不用碰存储层和路由层。

    matrix()         任意两维交叉矩阵（前端热力图）
    radar()          单维分布（前端雷达图）
    avg_severity()   平均危害等级
    severity_hist()  危害等级直方图
    overall()        总体 ASR
    overview()       总览打包（前端一屏看全）

所有函数第一个参数 source 可以是：
    - list[dict]  明细记录列表
    - 带 .all() 方法的对象（Memory 实例）
"""
from __future__ import annotations

from fuckai.scorer import CATEGORY_LABELS, REFUSAL_LABELS

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
# 允许参与统计的维度（路由层拿它做白名单校验）
ANALYTIC_DIMENSIONS = (
    "category", "converter", "dataset", "harm", "harm_major",
    "refusal_level", "severity", "target_model", "attack_model", "payload",
)

# 总览里默认出雷达图的维度
RADAR_DIMENSIONS = ("category", "dataset", "converter", "refusal_level")

# 危害等级取值范围
SEVERITY_LEVELS = (1, 2, 3, 4, 5)

# 空值统一占位符（前端会把它翻译成「未分类 / Unclassified」）
UNCATEGORIZED = "未分类"


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def _rows(source) -> list[dict]:
    """把入参统一成明细记录列表。"""
    if source is None:
        return []
    if isinstance(source, list):
        return source
    return list(source.all())


def _is_success(row: dict) -> bool:
    return bool(row.get("success"))


def _severity(row: dict) -> int:
    try:
        return int(row.get("severity") or 0)
    except (TypeError, ValueError):
        return 0


def _label(row: dict, key: str) -> str:
    """取某维度的取值，空值统一成「未分类」。"""
    return str(row.get(key) or "").strip() or UNCATEGORIZED


def _rate(success: int, total: int) -> float:
    """ASR = 成功数 / 总数。"""
    return round(success / total, 4) if total else 0.0


def _avg_severity_of(bucket: dict) -> float:
    """桶内平均危害等级（只统计有打分的记录）。"""
    n = bucket.get("severity_n", 0)
    return round(bucket.get("severity_sum", 0) / n, 2) if n else 0.0


def check_dimension(name: str) -> str:
    """校验维度合法性，不合法直接抛 ValueError（路由层转 400）。"""
    if name not in ANALYTIC_DIMENSIONS:
        raise ValueError(f"不支持的维度，可选: {sorted(ANALYTIC_DIMENSIONS)}")
    return name


# --------------------------------------------------------------------------- #
# 统计
# --------------------------------------------------------------------------- #
def overall(source) -> dict:
    """总体统计：总数 / 成功数 / ASR。"""
    rows = _rows(source)
    success = sum(1 for r in rows if _is_success(r))
    return {"total": len(rows), "success": success, "asr": _rate(success, len(rows))}


def avg_severity(source) -> float:
    """全部已评分记录的平均危害等级（1-5，无评分记录不参与）。"""
    vals = [_severity(r) for r in _rows(source)]
    vals = [v for v in vals if v > 0]
    return round(sum(vals) / len(vals), 2) if vals else 0.0


def severity_hist(source) -> list[dict]:
    """危害等级直方图：每个等级的总数 / 成功数 / ASR。"""
    rows = _rows(source)
    buckets = {i: {"total": 0, "success": 0} for i in SEVERITY_LEVELS}
    for r in rows:
        sev = _severity(r)
        if sev in buckets:
            buckets[sev]["total"] += 1
            if _is_success(r):
                buckets[sev]["success"] += 1
    out = []
    for sev in SEVERITY_LEVELS:
        b = buckets[sev]
        out.append({
            "severity": sev,
            "total": b["total"],
            "success": b["success"],
            "asr": _rate(b["success"], b["total"]),
        })
    return out


def matrix(source, row_key: str = "category", col_key: str = "converter",
           extra_keys: tuple = ("dataset", "harm", "harm_major")) -> dict:
    """按 row_key × col_key 交叉聚合，返回矩阵 + 各轴标签。

    单元格 = 该交叉点的 {total, success, asr, avg_severity}
    """
    rows = _rows(source)
    cells: dict[tuple[str, str], dict] = {}
    row_labels: list[str] = []
    col_labels: list[str] = []
    extras: dict[str, dict] = {}

    for r in rows:
        rk = _label(r, row_key)
        ck = _label(r, col_key)
        key = (rk, ck)
        cell = cells.setdefault(key, {"total": 0, "success": 0, "severity_sum": 0,
                                      "severity_n": 0})
        cell["total"] += 1
        if _is_success(r):
            cell["success"] += 1
        sev = _severity(r)
        if sev > 0:
            cell["severity_sum"] += sev
            cell["severity_n"] += 1
        if rk not in row_labels:
            row_labels.append(rk)
        if ck not in col_labels:
            col_labels.append(ck)
        for ek in extra_keys:
            ev = str(r.get(ek) or "").strip()
            if not ev:
                continue
            bucket = extras.setdefault(ek, {})
            b = bucket.setdefault(ev, {"total": 0, "success": 0})
            b["total"] += 1
            if _is_success(r):
                b["success"] += 1

    grid = []
    for rk in row_labels:
        line = []
        for ck in col_labels:
            cell = cells.get((rk, ck))
            if not cell:
                line.append(None)
                continue
            line.append({
                "total": cell["total"],
                "success": cell["success"],
                "asr": _rate(cell["success"], cell["total"]),
                "avg_severity": _avg_severity_of(cell),
            })
        grid.append(line)

    for bucket in extras.values():
        for b in bucket.values():
            b["asr"] = _rate(b["success"], b["total"])

    return {
        "row_key": row_key,
        "col_key": col_key,
        "rows": row_labels,
        "cols": col_labels,
        "matrix": grid,
        "extras": extras,
        "total": len(rows),
        "overall": overall(rows),
    }


def radar(source, dimension: str = "category") -> dict:
    """雷达图数据：按指定维度统计 ASR（1 - pass_rate），AIG 同口径。"""
    rows = _rows(source)
    buckets: dict[str, dict] = {}
    for r in rows:
        key = _label(r, dimension)
        b = buckets.setdefault(key, {"total": 0, "success": 0, "severity_sum": 0,
                                     "severity_n": 0})
        b["total"] += 1
        if _is_success(r):
            b["success"] += 1
        sev = _severity(r)
        if sev > 0:
            b["severity_sum"] += sev
            b["severity_n"] += 1

    axes = []
    for key, b in sorted(buckets.items(), key=lambda kv: -kv[1]["total"]):
        axes.append({
            "name": key,
            "total": b["total"],
            "success": b["success"],
            "asr": _rate(b["success"], b["total"]),
            "avg_severity": _avg_severity_of(b),
        })
    return {"dimension": dimension, "axes": axes, "total": len(rows)}


def overview(source, radar_dimensions: tuple = RADAR_DIMENSIONS) -> dict:
    """总览：总体 ASR + 各维度分布 + 危害等级直方图，前端一屏看全。"""
    rows = _rows(source)
    ov = overall(rows)
    ov["avg_severity"] = avg_severity(rows)
    return {
        "overall": ov,
        "radar": {dim: radar(rows, dim)["axes"] for dim in radar_dimensions},
        "severity_hist": severity_hist(rows),
        "category_labels": CATEGORY_LABELS,
        "refusal_labels": REFUSAL_LABELS,
    }
