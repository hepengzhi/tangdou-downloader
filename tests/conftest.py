# -*- coding: utf-8 -*-
"""pytest 公共配置：保证项目根目录在 sys.path，离屏模式。"""
import os
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

# GUI 测试需要离屏平台
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
