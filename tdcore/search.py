# -*- coding: utf-8 -*-
"""歌名搜索：全网搜索（糖豆优先）+ 交互式兜底下载。"""
import re
import time
import urllib.parse
import urllib.request

from .api import extract_vid
from .download import download_video


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
