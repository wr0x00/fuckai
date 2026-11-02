# -*- coding: utf-8 -*-
"""fuckai Web 启动入口。

    python web.py                # http://127.0.0.1:8000
    python web.py --port 9000
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
