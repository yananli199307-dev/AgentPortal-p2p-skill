#!/usr/bin/env python3
"""
Develop 栈中 bridge 容器入口：与 local/bridge.py 完全一致，仅便于 compose 显式区分环境。

生产可直接运行: python local/bridge.py
"""
import runpy
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

if __name__ == "__main__":
    runpy.run_path(str(_ROOT / "local" / "bridge.py"), run_name="__main__")
