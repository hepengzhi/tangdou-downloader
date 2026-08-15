# -*- coding: utf-8 -*-
"""命令行入口（CLI）。"""
import argparse
import os
import sys

from . import (
    default_download_dir,
    download_related,
    download_video,
    extract_vid,
    song_mode,
)
from .log import setup_log_file

DOC = """糖豆广场舞下载器 (命令行)
=================================
给一个糖豆视频的分享链接 / vid，自动下载视频(mp4)并提取音频(mp3)。
也支持按「歌名」搜索下载，以及一键批量下载某个视频的 20 个相关视频。

用法示例
--------
  python tangdou_dl.py <分享链接或vid> [更多链接...]      # 下载视频+音频
  python tangdou_dl.py --song "最炫民族风"                # 按歌名搜索下载
  python tangdou_dl.py --related <vid> --audio-only       # 下载相关视频的音频(舞曲mp3)
  python tangdou_dl.py <vid> --no-audio --quality h540p   # 只要视频, 指定清晰度
  python tangdou_dl.py <vid> --dir "D:/广场舞"            # 指定保存目录
  python tangdou_dl.py <vid> --clip 00:01:30-00:02:30     # 下载后剪辑片段
"""


def parse_args():
    p = argparse.ArgumentParser(description="糖豆广场舞下载器：给歌名/链接，自动下载视频+音频")
    p.add_argument("targets", nargs="*", help="糖豆分享链接或 vid 编号，可多个")
    p.add_argument("--song", metavar="歌名", help="按歌名搜索下载")
    p.add_argument("--related", metavar="vid", help="下载某视频的相关视频（同歌其他版本）")
    p.add_argument("--audio-only", action="store_true", help="--related 时只下载舞曲 mp3")
    p.add_argument("--limit", type=int, default=20, help="--related 最多下载个数")
    p.add_argument("--no-audio", action="store_true", help="不提取音频")
    p.add_argument("--quality", choices=["auto", "h540p", "h720p", "all"], default="auto",
                   help="清晰度（默认 auto=优先720P；all=下载全部可用清晰度）")
    p.add_argument("--clip", metavar="开始-结束", default=None,
                   help="下载后剪辑片段，如 00:01:30-00:02:30")
    p.add_argument("--dir", default=default_download_dir(),
                   help="保存目录（默认 用户Downloads目录）")
    return p.parse_args()


def main():
    # Windows 控制台默认 GBK，统一为 UTF-8 输出
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    setup_log_file()
    args = parse_args()
    outdir = args.dir
    os.makedirs(outdir, exist_ok=True)
    quality = args.quality
    want_audio = not args.no_audio
    clip = args.clip

    if args.song:
        song_mode(args.song, outdir, want_audio, quality, clip=clip)
        return

    if args.related:
        download_related(args.related, outdir, audio_only=args.audio_only, limit=args.limit)
        return

    if not args.targets:
        print(DOC)
        return

    for t in args.targets:
        vid = extract_vid(t)
        if not vid:
            print(f"无法从「{t}」识别 vid，跳过")
            continue
        download_video(vid, outdir, want_audio, quality, clip=clip)

    print(f"\n完成！文件保存在: {os.path.abspath(outdir)}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(1)
