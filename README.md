# 糖豆广场舞下载器 (tangdou_dl.py / tangdou_gui.py)

给歌名/链接，自动下载糖豆广场舞视频(mp4) + 音频(mp3)。

提供两种界面：
- **`tangdou_gui.py`** — PySide6 (Qt) 图形界面（推荐，行业标准 GUI 方案）
- **`tangdou_dl.py`** — 命令行版

命令行版纯 Python 标准库实现，无第三方依赖；GUI 版需 `pip install PySide6`。
音频提取自动使用系统 ffmpeg 或 pip 包 `imageio-ffmpeg` 自带的 ffmpeg 二进制。

## 图形界面（推荐）

```bash
pip install PySide6            # 仅 GUI 需要
python tangdou_gui.py
```

界面三个页签 + 任务表 + 日志：
- **链接下载**：粘贴糖豆 App 分享链接或 vid（每行一个）→ 加入任务
- **歌名搜索**：输入歌名自动搜糖豆站内链接；搜不到时按界面提示在 App 里搜歌名、
  分享、把链接粘贴到下方输入框
- **相关批量**：输入一个 vid，一键加入它的 20 个相关视频（通常同歌其他版本），
  可勾选"仅下载舞曲 mp3"直接拿糖豆舞曲原音频

顶部可切换清晰度（自动/720P/540P）、是否提取 mp3、保存目录。后台线程下载不卡界面，
任务表实时进度条，可停止、打开保存目录。

## 命令行用法

```bash
# 1) 给链接/vid，下载视频+音频（最常用）
python tangdou_dl.py "https://www.tangdoucdn.com/h5/play?vid=20000002258422&utm_..." 
python tangdou_dl.py 20000002258422
```

## 为什么做这个

GitHub 上现有的糖豆下载器（CCBP/TangdouDownloader、SwaggyMacro/TangdouDownloader 等）
都**只能输入视频链接/vid**，不支持"给歌名直接搜"。而糖豆官网的网页搜索功能已下线
（`/so/search.htm` 已 404），搜索只剩 App 内有。本工具在保留"链接下载"的基础上，
补上歌名模式的自动搜索 + App 粘贴兜底，并把每个视频的 20 个相关视频（通常是同一首歌的
其他版本）做成一键批量下载，视频、舞曲 mp3 都能下。

## 安装

```bash
# 只装 Python 3.8+（无需任何 pip 包即可下载视频）
# 音频提取二选一：
#   1) 系统已有 ffmpeg -> 直接可用
#   2) 没有 ffmpeg  -> 一行命令自带：
python -m pip install imageio-ffmpeg
```

## 用法

```bash
# 1) 给链接/vid，下载视频+音频（最常用）
python tangdou_dl.py "https://www.tangdoucdn.com/h5/play?vid=20000002258422&utm_..." 
python tangdou_dl.py 20000002258422

# 2) 给歌名（自动搜索糖豆站内链接；搜不到会引导你在 App 里搜歌名后粘贴分享链接，之后全自动）
python tangdou_dl.py --song "最炫民族风"

# 3) 批量下载某视频的相关视频（同歌其他版本，20 个）
python tangdou_dl.py --related 20000002258422
#    只下舞曲 mp3：
python tangdou_dl.py --related 20000002258422 --audio-only

# 常用选项
--no-audio        # 只要视频
--quality h540p   # 清晰度（默认 auto：优先 720P，自动回退 540P）
--dir "D:/广场舞" # 保存目录（默认 ./Download）
```

一次可粘贴/输入多个链接，每行一个。

## 工作原理（2026 年实测，无需登录）

| 功能 | 接口 |
|---|---|
| 视频信息+播放地址 | `GET api-h5.tangdou.com/mtangdou/video/play?vid={vid}` → `data.play_url`（默认 540P，URL 内替换为 H720P 可升清晰度，已验证） |
| 相关视频（含舞曲mp3） | `GET api-h5.tangdou.com/sample/share/recommend?page_num=1&vid={vid}` → `data[]` 每项含 `videourl`、`mp3url` |
| 下载请求头 | 必须带 `Referer: https://www.tangdoucdn.com`，否则拿到的是默认 `hello.mp4` |

音频来源：下载的 mp4 用 ffmpeg 提取音轨转 mp3（忠实于该视频所用音乐）；
`--related --audio-only` 直接下载糖豆的舞曲 mp3 原文件。

## 已知限制

- 歌名的"自动搜索"依赖搜狗收录的糖豆站内链接，通常搜不到（糖豆网页搜索下线导致站内页未被索引），
  此时工具会给出清晰的 App 操作指引，粘贴一次分享链接即可继续全自动。
- 需要网络可达 tangdou.com；接口若变动，工具会打印明确错误。
