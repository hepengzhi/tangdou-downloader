# -*- coding: utf-8 -*-
"""B 站源：搜索 → 视频信息 → WBI 签名 → DASH 音视频下载 → ffmpeg 合并。

接口链路（2026 年实测可用，需 buvid3 cookie 与 WBI 签名）：
  搜索   GET api.bilibili.com/x/web-interface/search/type?search_type=video&keyword=...
  信息   GET api.bilibili.com/x/web-interface/view?bvid=...
  播放   GET api.bilibili.com/x/player/wbi/playurl?bvid=&cid=&fnval=16  (WBI 签名)
  下载   视频/音频为独立 DASH 流(m4s)，需 ffmpeg 合并成 mp4
"""
import hashlib
import http.cookiejar
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request

from .api import sanitize
from .download import download, find_ffmpeg

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
BILI_HEADERS = {"User-Agent": UA, "Referer": "https://www.bilibili.com/"}
BILI_DL_HEADERS = {"User-Agent": UA, "Referer": "https://www.bilibili.com/"}
API = "https://api.bilibili.com"

# WBI 签名固定字符表
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]
BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
_mixin_cache = None

# Cookie 会话：访问主页拿 buvid3（B 站反爬要求），并自动附带
_cj = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cj))


def _refresh_cookies():
    """访问 B 站主页获取 buvid3 等 cookie。"""
    try:
        req = urllib.request.Request("https://www.bilibili.com/",
                                     headers={"User-Agent": UA})
        _opener.open(req, timeout=15).read(1024)
    except Exception:
        pass


def _get_json(url, headers=None, retries=2):
    """带 cookie 会话的 GET（412 反爬时刷新 cookie 重试）。"""
    hdrs = dict(headers or BILI_HEADERS)
    hdrs.setdefault("User-Agent", UA)
    hdrs.setdefault("Referer", "https://www.bilibili.com/")
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with _opener.open(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 412 and attempt == 0:
                _refresh_cookies()  # 补 cookie 后重试一次
                continue
            raise BilibiliError(f"HTTP {e.code}: {url[:80]}")
    raise BilibiliError("请求失败")


class BilibiliError(Exception):
    pass


def extract_bvid(text):
    m = BV_RE.search(text)
    return m.group(1) if m else None


def search(keyword, limit=15):
    """按歌名搜索 B 站视频，返回 [{bvid, title, author, play, duration}]。"""
    url = (f"{API}/x/web-interface/search/type?search_type=video&keyword="
           + urllib.parse.quote(keyword))
    j = _get_json(url)
    if j.get("code") != 0:
        raise BilibiliError(f"B站搜索失败: {j.get('message') or j.get('code')}")
    out = []
    for it in (j.get("data") or {}).get("result") or []:
        if not it.get("bvid"):
            continue
        title = re.sub(r"<[^>]+>", "", it.get("title") or "")
        out.append({
            "bvid": it["bvid"],
            "title": title.strip(),
            "author": it.get("author") or "",
            "play": it.get("play") or 0,
            "duration": it.get("duration") or "",
        })
        if len(out) >= limit:
            break
    return out


def get_video_info(bvid):
    """view 接口：标题、cid、时长、多P。"""
    j = _get_json(f"{API}/x/web-interface/view?bvid={bvid}")
    if j.get("code") != 0 or not j.get("data"):
        raise BilibiliError(f"获取B站视频信息失败: {j.get('message') or j.get('code')}")
    d = j["data"]
    return {
        "title": d.get("title") or bvid,
        "cid": d.get("cid"),
        "duration": d.get("duration") or 0,
        "pages": d.get("pages") or [],
    }


def _get_mixin_key():
    global _mixin_cache
    if _mixin_cache:
        return _mixin_cache
    nav = _get_json(f"{API}/x/web-interface/nav")
    wbi = (nav.get("data") or {}).get("wbi_img") or {}
    img = (wbi.get("img_url") or "").split("/")[-1].split(".")[0]
    sub = (wbi.get("sub_url") or "").split("/")[-1].split(".")[0]
    if not img or not sub:
        raise BilibiliError("获取 B站 WBI 密钥失败")
    raw = img + sub
    _mixin_cache = "".join(raw[i] for i in MIXIN_KEY_ENC_TAB)[:32]
    return _mixin_cache


def _wbi_sign(params):
    params = dict(params)
    params["wts"] = int(time.time())
    filtered = {k: "".join(ch for ch in str(v) if ch not in "!'()*")
                for k, v in params.items()}
    query = urllib.parse.urlencode(sorted(filtered.items()))
    filtered["w_rid"] = hashlib.md5((query + _get_mixin_key()).encode()).hexdigest()
    return filtered


def get_playurl(bvid, cid):
    """DASH 播放地址，返回 {video: [..], audio: [..]}（流字典含 baseUrl/codecs/bandwidth）。"""
    signed = _wbi_sign({"bvid": bvid, "cid": cid, "fnval": 16, "fourk": 1})
    url = f"{API}/x/player/wbi/playurl?" + urllib.parse.urlencode(signed)
    j = _get_json(url)
    if j.get("code") != 0:
        raise BilibiliError(f"获取B站播放地址失败: {j.get('message') or j.get('code')}")
    dash = (j.get("data") or {}).get("dash") or {}
    return {"video": dash.get("video") or [], "audio": dash.get("audio") or []}


def _pick_streams(streams):
    """优先选 avc(H.264) 码率最高的视频流；音频选码率最高的。"""
    video = [s for s in streams["video"] if "avc" in (s.get("codecs") or "")]
    if not video:
        video = streams["video"]
    video = sorted(video, key=lambda s: s.get("bandwidth") or 0, reverse=True)
    audio = sorted(streams["audio"], key=lambda s: s.get("bandwidth") or 0, reverse=True)
    return (video[0] if video else None), (audio[0] if audio else None)


def _ffmpeg_merge(ffmpeg, video_file, audio_file, out_mp4, log=print):
    """合并 DASH 音视频为 mp4（流拷贝，快）。"""
    args = [ffmpeg, "-y", "-i", video_file, "-i", audio_file,
            "-c", "copy", "-movflags", "+faststart", out_mp4]
    r = subprocess.run(args, capture_output=True, timeout=1800)
    if r.returncode == 0 and os.path.exists(out_mp4) and os.path.getsize(out_mp4) > 0:
        return True
    # 部分浏览器/设备不支持流拷贝源格式，尝试重编码
    args = [ffmpeg, "-y", "-i", video_file, "-i", audio_file,
            "-c:v", "libx264", "-preset", "fast", "-c:a", "aac", "-movflags", "+faststart", out_mp4]
    r = subprocess.run(args, capture_output=True, timeout=3600)
    return r.returncode == 0 and os.path.exists(out_mp4) and os.path.getsize(out_mp4) > 0


def download_video_bili(bvid, outdir, log=print, progress=None):
    """下载 B 站视频并合并为 mp4。返回 (ok, mp4路径, None)。
    输出文件名用视频标题（bvid 后缀避免同名冲突）。"""
    info = get_video_info(bvid)
    title = sanitize(info["title"])
    if len(info.get("pages") or []) > 1:
        log(f"    该视频有多个分P，仅下载第 1 个分P（{info['pages'][0].get('part','')}）")
    cid = info["cid"]
    if not cid:
        log("    ! 未获取到 cid")
        return False, None, None

    log(f"    解析B站播放地址…")
    streams = get_playurl(bvid, cid)
    vstream, astream = _pick_streams(streams)
    if not vstream:
        log("    ! 未获取到视频流")
        return False, None, None

    os.makedirs(outdir, exist_ok=True)
    tmp = os.path.join(outdir, f".bili_{bvid}")
    os.makedirs(tmp, exist_ok=True)
    vfile = os.path.join(tmp, "video.m4s")
    afile = os.path.join(tmp, "audio.m4s")
    out_mp4 = os.path.join(outdir, title + f"_{bvid}.mp4")

    try:
        log("    下载视频流…")
        if not download(vstream["baseUrl"], vfile, log=log, progress=progress,
                        headers=BILI_DL_HEADERS):
            log("    ! 视频流下载失败")
            return False, None, None
        if astream:
            log("    下载音频流…")
            if not download(astream["baseUrl"], afile, log=log, progress=progress,
                            headers=BILI_DL_HEADERS):
                log("    ! 音频流下载失败")
                return False, None, None
        log("    合并音视频…")
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            log("    ! 未找到 ffmpeg，无法合并。可安装：python -m pip install imageio-ffmpeg")
            return False, None, None
        if _ffmpeg_merge(ffmpeg, vfile, afile if os.path.exists(afile) else vfile, out_mp4, log=log):
            log(f"    完成 -> {os.path.basename(out_mp4)}")
            return True, out_mp4, None
        log("    ! 合并失败")
        return False, None, None
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
