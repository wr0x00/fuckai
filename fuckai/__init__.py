# -*- coding: utf-8 -*-
"""fuckai。

模块一览：
    client.py        OpenAI 兼容端点客户端（被攻击模型 / 攻击模型）
    datasets.py      datasets/converters YAML 攻击模板加载
    payloads.py      datasets/ 全量载荷库（话题 / 越狱模板 / 执行器话术）
    converters.py    规则/LLM 两种 prompt 变换器
    scorer.py        True/False 越狱判定评分器
    memory.py        SQLite 会话记录
    analyzer.py      多维分析聚合统计（矩阵 / 雷达图 / 总览）
    orchestrator.py  攻击管线编排
    updater.py       GitHub 自动更新
"""
__version__ = "26.11.17"
