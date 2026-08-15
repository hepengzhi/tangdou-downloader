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

