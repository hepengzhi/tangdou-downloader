#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""糖豆广场舞下载器 - 命令行入口（核心逻辑在 tdcore 包）。

用法示例
--------
  python tangdou_dl.py <分享链接或vid> [更多链接...]      # 下载视频+音频
  python tangdou_dl.py --song "最炫民族风"                # 按歌名搜索下载
  python tangdou_dl.py --related <vid> --audio-only       # 下载相关视频的音频(舞曲mp3)
  python tangdou_dl.py <vid> --no-audio --quality h540p   # 只要视频, 指定清晰度
  python tangdou_dl.py <vid> --dir "D:/广场舞"            # 指定保存目录
"""
import sys

from tdcore import *  # noqa: F401,F403  重导出全部公开接口
from tdcore.cli import main

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(1)
