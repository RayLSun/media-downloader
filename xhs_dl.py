#!/usr/bin/env python3
"""便捷入口：python xhs_dl.py <链接> 等价于 python -m xhs_dl.cli。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from xhs_dl.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
