# -*- coding: utf-8 -*-
"""本地 vid-title 对应表（sqlite3）查询：歌名 → vid。

用户自备一个 sqlite 数据库（表结构 videos(vid INTEGER PRIMARY KEY, title TEXT)），
歌名搜索时按标题模糊匹配出 vid，可直接加入下载任务。
支持多关键词搜索：用 空格 / + / 、 分隔，要求标题同时包含所有词（AND）。
"""
import os
import re
import sqlite3


def _esc_like(s):
    """转义 LIKE 通配符，避免标题里的 % _ 被当作通配符。"""
    return (s or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def split_keywords(text):
    """把搜索词拆成多个关键词（按 空格/+/、/逗号/分号 分隔），去空。"""
    parts = re.split(r"[+\s、，,;；]+", (text or "").strip())
    return [p for p in parts if p]


def find_vids(db_path, title, limit=50):
    """在 sqlite 的 videos 表中按标题模糊查找 vid。

    多个关键词时要求标题同时包含所有词（AND）。
    返回 [(vid:int, title:str), ...]；db 不存在 / 表缺失 / 出错时返回 []（不抛异常）。
    """
    kws = split_keywords(title)
    if not db_path or not os.path.isfile(db_path) or not kws:
        return []
    conds = " AND ".join(["title LIKE ? ESCAPE '\\'"] * len(kws))
    params = [f"%{_esc_like(k)}%" for k in kws] + [int(limit)]
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3)
        try:
            cur = con.cursor()
            cur.execute(
                f"SELECT vid, title FROM videos WHERE {conds} ORDER BY vid LIMIT ?",
                params)
            return [(int(r[0]), str(r[1])) for r in cur.fetchall()]
        finally:
            con.close()
    except Exception:
        return []


def check_db(db_path):
    """校验 db 文件与 videos 表是否可用；返回 (ok:bool, message:str)。"""
    if not db_path:
        return False, "未配置数据库文件路径"
    if not os.path.isfile(db_path):
        return False, f"文件不存在：{db_path}"
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3)
        try:
            cur = con.cursor()
            cur.execute("SELECT COUNT(*) FROM videos")
            n = cur.fetchone()[0]
        finally:
            con.close()
        return True, f"数据库正常：videos 表共 {n} 条记录"
    except sqlite3.Error as e:
        return False, f"数据库不可用：{e}"
