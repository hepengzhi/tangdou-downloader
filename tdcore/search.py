# -*- coding: utf-8 -*-
"""歌名搜索：全网搜索（糖豆优先 + B 站可下载源）+ 交互式兜底下载。"""
import re
import time
import urllib.parse
import urllib.request

from .api import extract_vid
from .bilibili import extract_bvid, search as bili_search
from .download import download_video


def search_all(keyword, limit=15):
    """合并多源搜索：糖豆站内(经搜狗) + B 站可下载源 + 全网参考。
    返回 [{title, url, vid, bvid, source}]：
      source = "tangdou"(可下载) / "bili"(可下载) / "web"(仅参考)"""
    results = []
    seen = set()
    # 1) 搜狗：糖豆站内 + 全网参考（含 B 站链接时补提取 bvid）
    for r in sogou_search(keyword):
        bvid = extract_bvid(r.get("url") or "")
        if r.get("vid"):
            r["source"] = "tangdou"
            key = "td:" + r["vid"]
        elif bvid:
            r["source"] = "bili"
            r["bvid"] = bvid
            key = "bili:" + bvid
        else:
            r["source"] = "web"
            key = "url:" + r.get("url", "")[:60]
        if key in seen:
            continue
        seen.add(key)
        results.append(r)
    # 2) 直接查 B 站（保证有可下载结果）
    try:
        for it in bili_search(keyword, limit=limit):
            key = "bili:" + it["bvid"]
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "title": it["title"], "url": f"https://www.bilibili.com/video/{it['bvid']}",
                "vid": None, "bvid": it["bvid"], "source": "bili",
                "author": it.get("author"), "play": it.get("play"),
                "duration": it.get("duration"),
            })
    except Exception:
        pass  # B 站搜索失败不影响其它源
    return results


def sogou_search(keyword):
    """搜狗搜索歌名，返回 [{title, url, vid}]。
    vid 非空 = 糖豆站内链接（可直接自动下载）；vid 为空 = 全网其他平台的广场舞视频（供参考）。
    先搜普通关键词（覆盖全网），再补搜 site:tangdou.com（尽量找糖豆站内页）。"""

    def _query(q):
        url = "https://www.sogou.com/web?query=" + urllib.parse.quote(q)
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        last = None
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
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
            req = urllib.request.Request(full, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
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
    results = search_all(keyword)
    tangdou_items = [r for r in results if r.get("source") == "tangdou"]
    bili_items = [r for r in results if r.get("source") == "bili"]
    others = [r for r in results if r.get("source") == "web"]

    downloadables = tangdou_items + bili_items
    if downloadables:
        log(f"搜索到 {len(downloadables)} 个可下载视频（糖豆 {len(tangdou_items)} 个 + B站 {len(bili_items)} 个）：")
        for i, r in enumerate(downloadables, 1):
            tag = "糖豆" if r.get("source") == "tangdou" else "B站"
            key = r.get("vid") or r.get("bvid")
            log(f"  {i}. [{tag} {key}] {r['title']}")
        try:
            choice = input("输入序号下载（直接回车=全部，0=不下载）: ").strip()
        except EOFError:
            choice = "0"
        if choice == "":
            chosen = downloadables
        elif choice == "0":
            chosen = []
        else:
            chosen = [downloadables[int(choice) - 1]]
        for r in chosen:
            if r.get("source") == "tangdou":
                download_video(r["vid"], outdir, want_audio, quality, log=log, clip=clip)
            else:
                from .bilibili import download_video_bili
                download_video_bili(r["bvid"], outdir, log=log)
    else:
        log("未找到糖豆/B站站内视频（糖豆官网搜索已下线，站内视频未被搜索引擎收录）。")
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
