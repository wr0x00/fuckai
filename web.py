# -*- coding: utf-8 -*-
"""fuckai Web 启动入口。

    python web.py                # http://127.0.0.1:8000
    python web.py --port 9000

> 此项目成立于2026.11。目前llm自身安全研究领域处于方兴未艾时期，关于security for ai大部分研究停留在论文阶段，工程化应用较少。已公布的llm自身漏洞种类原理较浅(主要以提示词注入为主)，还未爆出长链路、通用面广、深度高、危害性高的漏洞类型。

> 本项目旨在吸收全网优秀llm攻击手法，长久更新，力求构建一个体系化开源版本的llm自身安全测试框架

"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from web.app import main

if __name__ == "__main__":
    main()
