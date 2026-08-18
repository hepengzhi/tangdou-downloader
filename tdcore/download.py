# -*- coding: utf-8 -*-
"""下载核心：文件下载（断点续传）、音频提取、剪辑、单视频与相关批量下载。"""
import os
import re
import subprocess
import time
import urllib.request

from .api import (
    HEADERS_DL,
    find_ffmpeg,
    get_related,
    get_video_info,
    get_video_info_share,
    get_video_url_html,
    resolve_qualities,
    sanitize,
    _pick_quality_url,
)


def download(url, dest, timeout=60, retries=3, log=print, progress=None, resume=True, headers=None):
    """带 Referer、重试与断点续传的文件下载，返回是否成功。
    resume: 支持断点续传（写入 dest+".part"，成功后改名）。
    headers: 自定义请求头（默认糖豆的 Referer；B 站等源传自己的）。"""
    part = dest + ".part"
    for attempt in range(1, retries + 1):
        start = os.path.getsize(part) if resume and os.path.exists(part) else 0
        mode = "ab" if start > 0 else "wb"
        hdrs = dict(headers if headers is not None else HEADERS_DL)
        if start > 0:
            hdrs["Range"] = f"bytes={start}-"
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                code = getattr(resp, "status", 200)
                if start > 0 and code == 200:
                    # 服务器不支持 Range，从头下
                    start = 0
                    total = int(resp.headers.get("Content-Length") or 0)
                    mode = "wb"
                got = start
                with open(part, mode) as f:
                    last = time.time()
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                        if progress:
                            progress(got, total + start if start else total)
                        now = time.time()
                        if now - last > 2:
                            last = now
                            mb = got / 1048576
                            if total:
                                log(f"    已下载 {mb:.1f} / {(total + start)/1048576:.1f} MB")
                            else:
                                log(f"    已下载 {mb:.1f} MB")
            expect = total + start if start else total
            if expect and got < expect * 0.9:
                raise IOError(f"下载不完整: {got}/{expect}")
            os.replace(part, dest)  # 完成：.part 改名
            return True
        except Exception as e:
            log(f"    下载失败(第{attempt}次): {e}")
            time.sleep(2 * attempt)
    return False


def extract_mp3(ffmpeg, mp4_path, mp3_path):
    """用 ffmpeg 从视频提取 mp3；libmp3lame 不可用时退化为无损 m4a。"""
    if not ffmpeg:
        return False, "未找到 ffmpeg"
    try:
        r = subprocess.run(
            [ffmpeg, "-y", "-i", mp4_path, "-vn", "-c:a", "libmp3lame", "-q:a", "4", mp3_path],
            capture_output=True, timeout=600,
        )
        if r.returncode == 0 and os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
            return True, "mp3"
        # 退化为无损抽取 m4a
        m4a = mp3_path.rsplit(".", 1)[0] + ".m4a"
        r2 = subprocess.run(
            [ffmpeg, "-y", "-i", mp4_path, "-vn", "-c:a", "copy", m4a],
            capture_output=True, timeout=600,
        )
        if r2.returncode == 0 and os.path.exists(m4a) and os.path.getsize(m4a) > 0:
            return True, "m4a"
        return False, (r.stderr or b"").decode("utf-8", "ignore")[-500:]
    except Exception as e:
        return False, str(e)


def clip_video(ffmpeg, mp4_path, clip_range, log=print):
    """用 ffmpeg 剪辑视频片段（尽量流拷贝，失败则重编码）。返回剪辑后路径。"""
    try:
        start, end = clip_range.split("-", 1)
    except ValueError:
        log(f"    ! 剪辑参数格式应为 开始-结束，如 00:01:30-00:02:30，收到: {clip_range}")
        return mp4_path
    base, ext = os.path.splitext(mp4_path)
    out = base + "_clip" + ext
    args = [ffmpeg, "-y", "-i", mp4_path, "-ss", start.strip(), "-to", end.strip(),
            "-c", "copy", out]
    r = subprocess.run(args, capture_output=True, timeout=600)
    if r.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) == 0:
        # 流拷贝失败（如关键帧对齐问题），改用重编码
        args = [ffmpeg, "-y", "-i", mp4_path, "-ss", start.strip(), "-to", end.strip(),
                "-c:v", "libx264", "-preset", "fast", "-c:a", "aac", out]
        r = subprocess.run(args, capture_output=True, timeout=1200)
    if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
        log(f"    剪辑完成 -> {os.path.basename(out)}")
        return out
    log("    ! 剪辑失败（保持原视频）")
    return mp4_path


def download_video(vid, outdir, want_audio=True, want_video=True, quality="auto", log=print, progress=None, clip=None):
    """下载单个视频 + 提取音频。返回 (ok, mp4路径, mp3路径)。
    模式：
      want_video=True,  want_audio=True  -> mp4 + mp3（默认）
      want_video=True,  want_audio=False -> 仅 mp4
      want_video=False, want_audio=True  -> 仅 mp3（临时下载视频，提取后删除）
    quality: auto(优先720P) / h720p / h540p / all(全部清晰度)
    clip: "开始-结束"（如 00:01:30-00:02:30），下载后剪辑出片段。"""
    info = None
    try:
        info = get_video_info(vid)
    except RuntimeError as e:
        log(f"    主接口失败({e})，尝试备用通道…")
        try:
            info = get_video_info_share(vid)
        except RuntimeError:
            log("    备用接口也失败，尝试 HTML 解析…")
            html_url = get_video_url_html(vid)
            if html_url:
                info = {"title": f"video_{vid}", "play_url": html_url}
    if not info or not info.get("play_url"):
        log("    ! 所有通道均无法获取视频地址")
        return False, None, None

    title = sanitize(info.get("title") or vid)
    log(f"\n[{vid}] {title}")

    play_url = info.get("play_url")
    if not play_url:
        log("    未返回播放地址，尝试 HTML 解析兜底…")
        play_url = get_video_url_html(vid)
        if not play_url:
            log("    ! 未能获取视频地址")
            return False, None, None

    if quality == "all":
        qualities = resolve_qualities(play_url)
        if not qualities:
            log("    ! 未检测到任何可用清晰度")
            return False, None, None
        log(f"    可用清晰度: {', '.join(qualities.keys())}")
        first = None
        ok_any = False
        for q, url in qualities.items():
            mp4, mp3 = _download_one(vid, title, url, outdir, want_audio, log, progress,
                                     suffix="_" + q, clip=clip, want_video=want_video)
            if mp4 or mp3:
                ok_any = True
                if first is None:
                    first = (mp4, mp3)
        return ok_any, (first[0] if first else None), (first[1] if first else None)

    play_url = _pick_quality_url(play_url, quality)
    qm = re.search(r"_(H?\d+P|V?\d+P)", play_url)
    log(f"    清晰度: {qm.group(1) if qm else '?'}")
    mp4, mp3 = _download_one(vid, title, play_url, outdir, want_audio, log, progress,
                             clip=clip, want_video=want_video)
    return bool(mp4 or mp3), mp4, mp3


def _download_one(vid, title, play_url, outdir, want_audio, log, progress, suffix="", clip=None, want_video=True):
    """下载一个具体地址的视频 + 提取音频。返回 (mp4路径, mp3路径)。
    want_video=False：仅需音频，视频下到 _tmp.mp4，提取后删除。"""
    mp3 = os.path.join(outdir, title + suffix + ".mp3")
    if want_audio and os.path.exists(mp3) and os.path.getsize(mp3) > 0:
        log("    音频已存在，跳过")
        return None, mp3

    mp4 = os.path.join(outdir, title + suffix + (".mp4" if want_video else "_tmp.mp4"))
    if want_video and os.path.exists(mp4) and os.path.getsize(mp4) > 0:
        log("    视频已存在，跳过下载")
    else:
        log(f"    下载视频 -> {os.path.basename(mp4)}")
        if not download(play_url, mp4, log=log, progress=progress):
            log("    ! 视频下载失败")
            return None, None

    if clip and want_video:
        ffmpeg = find_ffmpeg()
        if ffmpeg:
            clipped = clip_video(ffmpeg, mp4, clip, log=log)
            if clipped != mp4:
                return clipped, None
        else:
            log("    ! 未找到 ffmpeg，跳过剪辑")

    if want_audio:
        if os.path.exists(mp3) and os.path.getsize(mp3) > 0:
            log("    音频已存在，跳过")
        else:
            ffmpeg = find_ffmpeg()
            if not ffmpeg:
                log("    ! 未找到 ffmpeg，跳过音频提取。可安装：python -m pip install imageio-ffmpeg")
            else:
                ok, kind = extract_mp3(ffmpeg, mp4, mp3)
                if ok:
                    log(f"    音频已提取 ({kind})")
                else:
                    log(f"    ! 音频提取失败: {kind}")

    if not want_video:
        # 仅音频模式：删掉临时视频
        try:
            os.remove(mp4)
            log("    临时视频已删除")
        except OSError:
            pass
        return None, mp3
    return mp4, (mp3 if want_audio else None)


def download_related(vid, outdir, audio_only=False, limit=20, log=print, progress=None):
    """批量下载相关视频（视频+音频 或 仅音频舞曲mp3）。"""
    items = get_related(vid)
    if not items:
        log("没有相关视频。")
        return
    log(f"\n共找到 {len(items)} 个相关视频（通常是同歌的其他版本）：")
    for i, it in enumerate(items[:limit], 1):
        t = sanitize(it.get("title") or str(it.get("vid")))
        dur = it.get("duration") or 0
        log(f"  {i}. [{it.get('vid')}] {t} ({dur}秒)")
    for i, it in enumerate(items[:limit], 1):
        t = sanitize(it.get("title") or str(it.get("vid")))
        log(f"\n({i}/{min(limit, len(items))}) {t}")
        if audio_only:
            mp3url = it.get("mp3url")
            if not mp3url:
                log("    ! 无 mp3url，跳过")
                continue
            dest = os.path.join(outdir, t + ".mp3")
            if os.path.exists(dest) and os.path.getsize(dest) > 0:
                log("    已存在，跳过")
                continue
            log("    下载舞曲 mp3 ...")
            download(mp3url, dest, log=log, progress=progress)
        else:
            vid2 = it.get("vid")
            if vid2:
                download_video(str(vid2), outdir, want_audio=True, log=log, progress=progress)
            else:
                log("    ! 无 vid，跳过")
