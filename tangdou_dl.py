#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
糖豆广场舞下载器 (tangdou_dl.py)
=================================
给一个糖豆视频的分享链接 / vid，自动下载视频(mp4)并提取音频(mp3)。
也支持按「歌名」搜索下载（自动搜索糖豆站内链接，找不到时引导粘贴 App 分享链接），
以及一键批量下载某个视频的 20 个相关视频（通常含同一首歌的其他版本）。

用法示例
--------
  python tangdou_dl.py <分享链接或vid> [更多链接...]      # 下载视频+音频
  python tangdou_dl.py --song "最炫民族风"                # 按歌名搜索下载
  python tangdou_dl.py --related <vid> --audio-only       # 下载相关视频的音频(舞曲mp3)
  python tangdou_dl.py <vid> --no-audio --quality h540p   # 只要视频, 指定清晰度
  python tangdou_dl.py <vid> --dir "D:/广场舞"            # 指定保存目录

依赖
----
  Python 3.8+，仅用标准库。
  音频提取需要 ffmpeg：优先使用系统 ffmpeg，其次自动使用 pip 包 imageio-ffmpeg
  （安装：python -m pip install imageio-ffmpeg），都没有则跳过音频并给出提示。

接口说明（2026 年实测可用，无需登录）
------------------------------------
  视频: GET https://api-h5.tangdou.com/mtangdou/video/play?vid={vid}
        -> data.play_url (H540P)，把 URL 中的 H540P 替换为 H720P 可升清晰度
  相关: GET https://api-h5.tangdou.com/sample/share/recommend?page_num=1&vid={vid}
        -> data[] 每项含 videourl(视频) 与 mp3url(舞曲音频)
  下载文件时必须带请求头 Referer: https://www.tangdoucdn.com
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

API_PLAY = "https://api-h5.tangdou.com/mtangdou/video/play?vid={vid}"
API_RECOMMEND = "https://api-h5.tangdou.com/sample/share/recommend?page_num=1&vid={vid}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Referer": "https://www.tangdoucdn.com/",
    "Accept": "application/json, text/plain, */*",
}
HEADERS_DL = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Referer": "https://www.tangdoucdn.com",
}

VID_RE = re.compile(r"(?:vid=)(\d+)", re.I)
BARE_VID_RE = re.compile(r"^\d{9,20}$")

ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def http_get_json(url, timeout=20):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def extract_vid(text):
    """从分享链接 / URL / 纯数字里提取 vid。"""
    m = VID_RE.search(text)
    if m:
        return m.group(1)
    m = BARE_VID_RE.match(text.strip())
    if m:
        return m.group(0)
    return None


def sanitize(name):
    name = ILLEGAL.sub("_", name).strip().strip(".")
    return name[:120] or "video"


def default_download_dir():
    """默认保存目录：用户家目录的 Downloads（不存在则退回家目录）。"""
    home = os.path.expanduser("~")
    d = os.path.join(home, "Downloads")
    return d if os.path.isdir(d) else home


def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg  # pip 包自带 ffmpeg 二进制
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    for p in (r"C:\ffmpeg\bin\ffmpeg.exe",
              r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"):
        if os.path.exists(p):
            return p
    return None


def head_ok(url, timeout=20):
    req = urllib.request.Request(url, headers=HEADERS_DL, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


QUALITIES = ("H1080P", "V1080P", "H720P", "V720P", "H540P", "V540P", "H360P", "V360P")


def resolve_qualities(play_url):
    """枚举 play_url 里可能存在的所有清晰度，返回 {清晰度: 可用URL}（按顺序）。"""
    m = re.search(r"_(H?\d+P|V?\d+P)", play_url)
    if not m:
        return {"原清晰度": play_url} if head_ok(play_url) else {}
    tag = m.group(1)
    out = {}
    for q in QUALITIES:
        cand = play_url.replace(tag, q)
        if cand != play_url and head_ok(cand):
            out[q] = cand
    if tag not in out and head_ok(play_url):
        out[tag] = play_url
    return out


def get_video_url_html(vid):
    """HTML 解析兜底：share.tangdou.com/splay.php 页面里的 <video> 标签。
    在 API 不可用时作为备用视频地址来源。"""
    url = f"http://share.tangdou.com/splay.php?vid={vid}"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", "ignore")
    except Exception:
        return None
    m = re.search(r'<video[^>]*src="([^"]+)"', html, re.I)
    return m.group(1) if m else None


def download(url, dest, timeout=60, retries=3, log=print, progress=None):
    """带 Referer 与重试的文件下载，返回是否成功。
    log: 日志回调(msg)；progress: 进度回调(done_bytes, total_bytes)。"""
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS_DL)
            with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as f:
                total = int(resp.headers.get("Content-Length") or 0)
                got = 0
                last = time.time()
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if progress:
                        progress(got, total)
                    now = time.time()
                    if now - last > 2:
                        last = now
                        mb = got / 1048576
                        if total:
                            log(f"    已下载 {mb:.1f} / {total/1048576:.1f} MB")
                        else:
                            log(f"    已下载 {mb:.1f} MB")
            if total and got < total * 0.9:
                raise IOError(f"下载不完整: {got}/{total}")
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


def get_video_info(vid):
    j = http_get_json(API_PLAY.format(vid=vid))
    if j.get("code") != 0 or not j.get("data"):
        raise RuntimeError(f"视频信息获取失败: {j.get('msg') or j}")
    return j["data"]


def get_related(vid):
    j = http_get_json(API_RECOMMEND.format(vid=vid))
    if j.get("code") != 0:
        raise RuntimeError(f"相关视频获取失败: {j.get('msg') or j}")
    return j.get("data") or []


def _pick_quality_url(play_url, quality):
    """按 quality(auto/h720p/h540p) 挑选最终播放地址。"""
    m = re.search(r"_(H?\d+P|V?\d+P)", play_url)
    base_tag = m.group(1) if m else None
    if quality == "h540p" or base_tag is None:
        return play_url
    if quality == "h720p":
        for q in ("H720P", "V720P", "H1080P"):
            if q == base_tag:
                return play_url
            cand = play_url.replace(base_tag, q)
            if head_ok(cand):
                return cand
        return play_url
    # auto：优先 720P，逐级回退
    for q in ("H720P", "V720P", "H1080P"):
        if q == base_tag:
            return play_url
        cand = play_url.replace(base_tag, q)
        if head_ok(cand):
            return cand
    return play_url


def download_video(vid, outdir, want_audio=True, quality="auto", log=print, progress=None, clip=None):
    """下载单个视频 + 提取音频。返回 (ok, mp4路径, mp3路径)。
    quality: auto(优先720P) / h720p / h540p / all(全部清晰度)
    clip: "开始-结束"（如 00:01:30-00:02:30），下载后剪辑出片段。"""
    info = get_video_info(vid)
    title = sanitize(info.get("title") or vid)
    log(f"\n[{vid}] {title}")

    play_url = info.get("play_url")
    if not play_url:
        log("    主接口未返回播放地址，尝试 HTML 解析兜底…")
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
                                     suffix="_" + q, clip=clip)
            if mp4:
                ok_any = True
                if first is None:
                    first = (mp4, mp3)
        return ok_any, (first[0] if first else None), (first[1] if first else None)

    play_url = _pick_quality_url(play_url, quality)
    qm = re.search(r"_(H?\d+P|V?\d+P)", play_url)
    log(f"    清晰度: {qm.group(1) if qm else '?'}")
    mp4, mp3 = _download_one(vid, title, play_url, outdir, want_audio, log, progress, clip=clip)
    return bool(mp4), mp4, mp3


def _download_one(vid, title, play_url, outdir, want_audio, log, progress, suffix="", clip=None):
    """下载一个具体地址的视频 + 提取音频。返回 (mp4路径, mp3路径)。"""
    mp4 = os.path.join(outdir, title + suffix + ".mp4")
    if os.path.exists(mp4) and os.path.getsize(mp4) > 0:
        log("    视频已存在，跳过下载")
    else:
        log(f"    下载视频 -> {os.path.basename(mp4)}")
        if not download(play_url, mp4, log=log, progress=progress):
            log("    ! 视频下载失败")
            return None, None

    if clip:
        ffmpeg = find_ffmpeg()
        if ffmpeg:
            clipped = clip_video(ffmpeg, mp4, clip, log=log)
            if clipped != mp4:
                return clipped, None
        else:
            log("    ! 未找到 ffmpeg，跳过剪辑")

    mp3 = os.path.join(outdir, title + suffix + ".mp3")
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
    return mp4, mp3


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


# ---------------- 歌名模式：全网搜索（糖豆优先） + 兜底交互 ----------------

def sogou_search(keyword):
    """搜狗搜索歌名，返回 [{title, url, vid}]。
    vid 非空 = 糖豆站内链接（可直接自动下载）；vid 为空 = 全网其他平台的广场舞视频（供参考）。
    先搜普通关键词（覆盖全网），再补搜 site:tangdou.com（尽量找糖豆站内页）。"""
    import urllib.request as _ur

    def _query(q):
        url = "https://www.sogou.com/web?query=" + urllib.parse.quote(q)
        req = _ur.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        last = None
        for attempt in range(2):
            try:
                with _ur.urlopen(req, timeout=15) as resp:
                    body = resp.read().decode("utf-8", "ignore")
                if len(body) > 20000:  # 太短说明被反爬页拦了，重试
                    return body
                last = "页面过短（可能被反爬拦截）"
                time.sleep(2 + attempt * 2)
            except Exception as e:
                last = e
                time.sleep(2 + attempt * 2)
        raise RuntimeError(last)

    def _resolve(link):
        """解析搜狗 /link?url= 重定向，返回最终 URL（无法解析则原样返回）。"""
        if not link.startswith("/link"):
            return link
        full = "https://www.sogou.com" + link
        try:
            req = _ur.Request(full, headers={"User-Agent": "Mozilla/5.0"})
            with _ur.urlopen(req, timeout=15) as resp:
                return resp.geturl()
        except Exception:
            return full

    results, seen = [], set()
    for q in (f'{keyword} 糖豆 广场舞', f'site:tangdou.com "{keyword}"'):
        try:
            html = _query(q)
        except Exception as e:
            print(f"自动搜索失败: {e}")
            continue
        for m in re.finditer(r'<h3[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>', html):
            title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            title = re.sub(r"\s+", " ", title)
            url = _resolve(m.group(1))
            vid = extract_vid(url)
            key = url[:80]
            if key in seen:
                continue
            seen.add(key)
            results.append({"title": title, "url": url, "vid": vid})
            if len(results) >= 15:
                break
    return results


def song_mode(keyword, outdir, want_audio, quality, log=print, clip=None):
    log(f"\n== 搜索歌名: {keyword} ==")
    results = sogou_search(keyword)
    tangdou_items = [r for r in results if r.get("vid")]
    others = [r for r in results if not r.get("vid")]

    if tangdou_items:
        log(f"搜索到 {len(tangdou_items)} 个糖豆站内视频，可直接下载：")
        for i, r in enumerate(tangdou_items, 1):
            log(f"  {i}. [{r['vid']}] {r['title']}")
        try:
            choice = input("输入序号下载（直接回车=全部，0=不下载）: ").strip()
        except EOFError:
            choice = "0"
        if choice == "":
            chosen = tangdou_items
        elif choice == "0":
            chosen = []
        else:
            chosen = [tangdou_items[int(choice) - 1]]
        for r in chosen:
            download_video(r["vid"], outdir, want_audio, quality, log=log, clip=clip)
    else:
        log("未找到糖豆站内视频（糖豆官网搜索已下线，站内视频未被搜索引擎收录）。")
        log("请按下面步骤操作一次，之后全部自动：")
        log("  1) 手机打开「糖豆」App，搜索歌名")
        log("  2) 点开想要的视频 → 分享 → 复制链接")
        log("  3) 把链接粘贴到这里（可粘贴多个，每行一个），直接回车结束")
        try:
            while True:
                line = input("粘贴链接/vid (回车结束): ").strip()
                if not line:
                    break
                vid = extract_vid(line)
                if vid:
                    download_video(vid, outdir, want_audio, quality, log=log, clip=clip)
                else:
                    log("  无法识别，请确认是糖豆的分享链接或 vid 编号")
        except EOFError:
            pass

    if others:
        log(f"\n全网搜到 {len(others)} 个该歌名的广场舞视频（其他平台，供参考）：")
        for i, r in enumerate(others, 1):
            log(f"  {i}. {r['title']}")
            log(f"     {r['url']}")
    # 提示相关视频
    log("\n提示：糖豆每个视频都有相关推荐（通常是同歌其他版本），")
    log("可用 --related <vid> 一键批量下载，或 --related <vid> --audio-only 只下舞曲mp3。")


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
        print(__doc__)
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

