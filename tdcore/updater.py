# -*- coding: utf-8 -*-
"""在线更新核心：查询 GitHub Release 最新版、版本比较。"""
import json
import urllib.request

UA = "tangdou-downloader"


def version_key(tag):
    """'v1.2.3' -> (1, 2, 3) 用于版本比较。"""
    nums = []
    for part in tag.lstrip("vV").split("."):
        d = ""
        for ch in part:
            if ch.isdigit():
                d += ch
            else:
                break
        nums.append(int(d) if d else 0)
    return tuple(nums)


def is_newer(tag, current):
    return bool(tag) and version_key(tag) > version_key(current)


def latest_release(repo, timeout=10):
    """查询最新 Release。返回 {tag, name, url, size, body}，失败返回 None。"""
    try:
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            j = json.loads(resp.read().decode("utf-8"))
        assets = j.get("assets") or []
        if not assets:
            return None
        a = assets[0]
        return {
            "tag": j.get("tag_name") or "",
            "name": a.get("name") or "",
            "url": a.get("browser_download_url") or "",
            "size": int(a.get("size") or 0),
            "body": (j.get("body") or "")[:500],
        }
    except Exception:
        return None
