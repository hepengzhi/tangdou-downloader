# -*- coding: utf-8 -*-
"""糖豆 API 封装：视频信息、播放地址、清晰度、HTML 兜底。"""
import json
import os
import re
import shutil
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
    """HTML 解析兜底：share.tangdou.com/splay.php 页面里的 <video> 标签。"""
    url = f"http://share.tangdou.com/splay.php?vid={vid}"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", "ignore")
    except Exception:
        return None
    m = re.search(r'<video[^>]*src="([^"]+)"', html, re.I)
    return m.group(1) if m else None


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


def get_video_info_share(vid):
    """备用信息接口：api-h5.tangdou.com/sample/share/main（老分享接口）。
    会员(VIP)视频用主接口会报"请登录APP观看会员视频"，此接口仍能拿到标题和播放地址。"""
    url = f"http://api-h5.tangdou.com/sample/share/main?vid={vid}"
    j = http_get_json(url)
    if j.get("code") != 0 or not j.get("data"):
        raise RuntimeError(f"备用接口获取视频信息失败: {j.get('msg') or j}")
    data = j["data"]
    # 统一字段：老接口的播放地址在 video_url
    if not data.get("play_url") and data.get("video_url"):
        data["play_url"] = data["video_url"]
    return data


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
