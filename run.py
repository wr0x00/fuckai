# -*- coding: utf-8 -*-
"""fuckai 入口。

用法:
    python.exe run.py   （在装有 pyyaml 的任意 Python 3.10+ 环境下运行）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from fuckai.cli import main

if __name__ == "__main__":
    main()
