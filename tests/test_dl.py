# -*- coding: utf-8 -*-
"""tdcore 核心逻辑单元测试（纯离线，不依赖网络）。"""
import os

import tdcore as td
import tdcore.api as td_api


# ---------- 基础工具 ----------

def test_extract_vid_from_share_url():
    assert td.extract_vid("https://www.tangdoucdn.com/h5/play?vid=20000002258422&utm=x") == "20000002258422"
    assert td.extract_vid("https://share.tangdou.com/splay.php?vid=1500661688388") == "1500661688388"


def test_extract_vid_bare_number():
    assert td.extract_vid("20000002258422") == "20000002258422"
    assert td.extract_vid("  123456789012  ") == "123456789012"


def test_extract_vid_invalid():
    assert td.extract_vid("https://www.bilibili.com/video/BV1xx") is None
    assert td.extract_vid("hello world") is None
    assert td.extract_vid("") is None


def test_sanitize_illegal_chars():
    assert td.sanitize('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"
    assert td.sanitize("  前后空格  ") == "前后空格"


def test_default_download_dir_exists():
    d = td.default_download_dir()
    assert os.path.isdir(d) or d == os.path.expanduser("~")


# ---------- 视频信息解析 ----------

def test_get_video_info_share_fallback(monkeypatch):
    """老分享接口：video_url 字段应统一为 play_url（离线 mock）。"""
    fake = {
        "code": 0,
        "data": {"title": "测试《歌曲》", "video_url": "https://x/v_1_H540P.mp4?sign=abc",
                 "play_url": ""},
    }
    monkeypatch.setattr(td_api, "http_get_json", lambda url: fake)
    data = td.get_video_info_share("20000002258422")
    assert data["play_url"] == "https://x/v_1_H540P.mp4?sign=abc"
    assert data["title"] == "测试《歌曲》"


def test_get_video_info_share_error(monkeypatch):
    monkeypatch.setattr(td_api, "http_get_json", lambda url: {"code": 1, "msg": "no"})
    try:
        td.get_video_info_share("123")
        assert False, "应抛出 RuntimeError"
    except RuntimeError:
        pass


# ---------- 清晰度选择 ----------

def test_pick_quality_h540p_keeps_base(monkeypatch):
    monkeypatch.setattr(td_api, "head_ok", lambda url: True)
    url = "https://x/wz/1_H540P.mp4?sign=a"
    assert td._pick_quality_url(url, "h540p") == url


def test_pick_quality_auto_upgrades(monkeypatch):
    hits = []

    def fake_head(url):
        hits.append(url)
        return "H720P" in url

    monkeypatch.setattr(td_api, "head_ok", fake_head)
    url = "https://x/wz/1_H540P.mp4?sign=a"
    picked = td._pick_quality_url(url, "auto")
    assert "_H720P" in picked
    assert any("H720P" in h for h in hits)


def test_resolve_qualities(monkeypatch):
    monkeypatch.setattr(td_api, "head_ok", lambda url: url.endswith("_H720P.mp4?sign=a"))
    url = "https://x/wz/1_H540P.mp4?sign=a"
    q = td.resolve_qualities(url)
    assert "H720P" in q
    assert q["H720P"] == "https://x/wz/1_H720P.mp4?sign=a"


# ---------- B 站源 ----------

def test_extract_bvid():
    from tdcore.bilibili import extract_bvid
    assert extract_bvid("https://www.bilibili.com/video/BV1vy4y17762") == "BV1vy4y17762"
    assert extract_bvid("BV14X4y1c75k 任意文本") == "BV14X4y1c75k"
    assert extract_bvid("https://www.tangdou.com/play/?vid=123") is None


def test_search_all_marks_sources(monkeypatch):
    """search_all 对搜狗与 B 站结果打来源标记（离线 mock）。"""
    import tdcore.search as s
    monkeypatch.setattr(s, "sogou_search", lambda kw: [
        {"title": "糖豆视频", "url": "https://www.tangdou.com/play/?vid=20000002258422", "vid": "20000002258422"},
        {"title": "B站视频", "url": "https://www.bilibili.com/video/BV1vy4y17762", "vid": None},
        {"title": "其它站", "url": "https://v.qq.com/x/page/a.html", "vid": None},
    ])
    monkeypatch.setattr(s, "bili_search", lambda kw, limit=15: [
        {"bvid": "BV1vy4y17762", "title": "B站视频", "author": "A", "play": 1, "duration": "1:00"},
        {"bvid": "BV1aaaaaaa1", "title": "另一个", "author": "B", "play": 2, "duration": "2:00"},
    ])
    rs = s.search_all("歌名")
    src = {r["source"] for r in rs}
    assert "tangdou" in src and "bili" in src and "web" in src
    assert sum(1 for r in rs if r["source"] == "bili") == 2


def test_bilibili_get_video_info_parsing(monkeypatch):
    from tdcore import bilibili
    monkeypatch.setattr(bilibili, "_get_json",
                        lambda url, headers=None, retries=2: {"code": 0, "data": {
                            "title": "测试视频", "cid": 12345, "duration": 120, "pages": []}})
    info = bilibili.get_video_info("BV1vy4y17762")
    assert info["cid"] == 12345
    assert info["title"] == "测试视频"


def test_bilibili_error_propagates(monkeypatch):
    from tdcore import bilibili
    monkeypatch.setattr(bilibili, "_get_json",
                        lambda url, headers=None, retries=2: {"code": -403, "message": "访问权限不足"})
    try:
        bilibili.get_video_info("BV1vy4y17762")
        assert False, "应抛出 BilibiliError"
    except bilibili.BilibiliError:
        pass


# ---------- 在线更新 ----------

def test_updater_version_key():
    from tdcore.updater import version_key, is_newer
    assert version_key("v1.4.0") == (1, 4, 0)
    assert version_key("v1.10.0") > version_key("v1.9.0")
    assert is_newer("v1.5.0", "1.4.0")
    assert not is_newer("v1.4.0", "1.5.0")
    assert not is_newer("", "1.5.0")


class _FakeResp:
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_updater_latest_release(monkeypatch):
    """latest_release 解析与失败兜底（离线 mock）。"""
    import json
    import tdcore.updater as up
    fake = {
        "tag_name": "v9.9.9",
        "body": "更新说明",
        "assets": [{"name": "x.exe", "browser_download_url": "https://x/x.exe", "size": 123456}],
    }
    monkeypatch.setattr(up.urllib.request, "urlopen",
                        lambda req, timeout=10: _FakeResp(json.dumps(fake)))
    info = up.latest_release("a/b")
    assert info["tag"] == "v9.9.9"
    assert info["url"] == "https://x/x.exe"
    assert info["size"] == 123456

    def boom(*a, **k):
        raise OSError("网络错误")

    monkeypatch.setattr(up.urllib.request, "urlopen", boom)
    assert up.latest_release("a/b") is None


# ---------- 日志 ----------

def test_setup_log_file_idempotent():
    lg = td.setup_log_file()
    assert lg is td.setup_log_file()
    assert lg.handlers, "应有文件 handler"


# ---------- 版本比较（GUI 共用逻辑） ----------

def test_version_key_in_gui():
    from tangdou_gui import version_key
    assert version_key("v1.1.0") == (1, 1, 0)
    assert version_key("v1.10.0") > version_key("v1.9.0")
    assert version_key("v1.0.2") < version_key("v1.2.0")

