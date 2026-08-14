# 糖豆广场舞下载器 (Tangdou Downloader)

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![GUI](https://img.shields.io/badge/GUI-PySide6-green)](https://pypi.org/project/PySide6/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)]()

> 输入糖豆广场舞视频链接 / vid / 歌名，自动下载视频（MP4）与音频（MP3）。

本项目提供 **图形界面（GUI）** 与 **命令行（CLI）** 两种使用方式，无需登录糖豆账号即可下载。

---

## 目录

- [功能特性](#功能特性)
- [环境要求](#环境要求)
- [安装](#安装)
- [快速开始](#快速开始)
  - [图形界面（推荐）](#图形界面推荐)
  - [命令行](#命令行)
- [命令行参数](#命令行参数)
- [使用示例](#使用示例)
- [项目结构](#项目结构)
- [工作原理](#工作原理)
- [常见问题](#常见问题)
- [已知限制](#已知限制)
- [免责声明](#免责声明)
- [许可证](#许可证)

---

## 功能特性

- ✅ **按链接 / vid 下载**：粘贴糖豆 App 分享链接或 vid 编号，自动下载视频并提取音频
- ✅ **按歌名搜索**：自动搜索全网该歌名的广场舞视频，命中糖豆站内链接即自动下载；其他平台结果供参考；另提供 App 分享链接兜底
- ✅ **多清晰度**：自动优先 720P，可指定 540P/720P，或 `all` 一次下载全部可用清晰度
- ✅ **视频剪辑**：`--clip 00:01:30-00:02:30` 下载后自动剪辑片段（如去掉教学开头）
- ✅ **相关视频批量下载**：一键拉取某视频的 20 个相关推荐（通常为同一首歌的其他版本）
- ✅ **舞曲 MP3**：直接下载糖豆舞曲原音频，或从视频中提取音轨（ffmpeg）
- ✅ **双通道视频解析**：主接口失败时自动用 HTML 解析（share.tangdou.com）兜底
- ✅ **后台任务队列**：GUI 线程下载不卡界面，实时进度条、日志、可停止

---

## 环境要求

| 依赖 | 说明 |
|---|---|
| Python 3.8+ | 必需 |
| PySide6 | 仅 GUI 需要（`pip install PySide6`） |
| ffmpeg | 音频提取需要；可用 `pip install imageio-ffmpeg` 自动获得 |

> CLI 版仅使用 Python 标准库，无第三方依赖。

---

## 安装

```bash
# 1. 克隆或下载本项目
git clone https://github.com/hepengzhi/tangdou-downloader.git
cd tangdou-downloader

# 2. 安装 GUI 依赖（仅使用图形界面时需要）
pip install PySide6

# 3. 安装音频提取依赖（二选一）
#    方案 A：系统已安装 ffmpeg —— 无需任何操作
#    方案 B：自动获取 ffmpeg 二进制
pip install imageio-ffmpeg
```

---

## 快速开始

### 图形界面（推荐）

```bash
python tangdou_gui.py
```

界面包含三个功能页签与任务管理区：

| 页签 | 用途 |
|---|---|
| **链接下载** | 粘贴分享链接或 vid（每行一个）→ 加入任务 |
| **歌名搜索** | 输入歌名搜索糖豆站内链接；无结果时按提示在 App 内搜索并粘贴分享链接 |
| **相关批量** | 输入基准 vid，一键批量下载其相关视频（可仅下载舞曲 MP3） |

顶部工具栏可切换清晰度（自动 / 720P / 540P）、是否提取音频、保存目录；
任务表实时显示进度，支持停止下载、打开保存目录。

### 命令行

```bash
# 1) 按链接 / vid 下载（视频 + 音频）
python tangdou_dl.py "https://www.tangdoucdn.com/h5/play?vid=20000002258422&utm_..."
python tangdou_dl.py 20000002258422

# 2) 按歌名搜索下载
python tangdou_dl.py --song "最炫民族风"

# 3) 批量下载相关视频（同歌其他版本）
python tangdou_dl.py --related 20000002258422
python tangdou_dl.py --related 20000002258422 --audio-only   # 仅舞曲 MP3
```

---

## 命令行参数

| 参数 | 说明 | 默认值 |
|---|---|---|
| `targets` | 糖豆分享链接或 vid 编号，可多个 | — |
| `--song 歌名` | 按歌名搜索下载 | — |
| `--related vid` | 批量下载某视频的相关视频 | — |
| `--audio-only` | 与 `--related` 连用，仅下载舞曲 MP3 | 关闭 |
| `--limit N` | `--related` 最大下载个数 | 20 |
| `--no-audio` | 不提取音频 | 关闭 |
| `--quality {auto,h540p,h720p,all}` | 清晰度 | `auto`（优先 720P；`all` 下载全部可用清晰度） |
| `--clip 开始-结束` | 下载后剪辑片段，如 `00:01:30-00:02:30` | 关闭 |
| `--dir 路径` | 保存目录 | `./Download` |

---

## 使用示例

```bash
# 批量下载多个链接（每行一个）
python tangdou_dl.py \
  "https://www.tangdoucdn.com/h5/play?vid=20000002258422" \
  "https://www.tangdou.com/play/?vid=20000013474038"

# 指定清晰度与保存目录，仅下载视频
python tangdou_dl.py 20000002258422 --quality h540p --no-audio --dir "D:/广场舞"
```

---

## 项目结构

```
tangdou-downloader/
├── tangdou_dl.py      # 命令行版 + 核心下载逻辑（标准库实现）
├── tangdou_gui.py     # PySide6 图形界面
├── smoke_gui.py       # GUI 离屏自动化冒烟测试
├── README.md          # 本文档
└── LICENSE            # MIT 许可证
```

---

## 工作原理

糖豆的下载接口无需登录即可访问，本项目基于以下接口实现（2026 年实测可用）：

| 功能 | 接口 |
|---|---|
| 视频信息与播放地址 | `GET https://api-h5.tangdou.com/mtangdou/video/play?vid={vid}` → `data.play_url`（默认 540P，URL 中替换为 `H720P` 可升清晰度） |
| 相关视频（含舞曲 MP3） | `GET https://api-h5.tangdou.com/sample/share/recommend?page_num=1&vid={vid}` → `data[]`，每项含 `videourl` 与 `mp3url` |
| 文件下载请求头 | 必须携带 `Referer: https://www.tangdoucdn.com`，否则返回默认 `hello.mp4` |

**音频来源**：
1. 从下载的 MP4 中用 ffmpeg 提取音轨转 MP3（忠实于视频所用音乐）；
2. `--related --audio-only` 模式直接下载糖豆舞曲 MP3 原文件。

---

## 常见问题

**Q：为什么"按歌名搜索"经常搜不到结果？**
糖豆官网的网页搜索功能已下线（`/so/search.htm` 返回 404），站内视频未被搜索引擎收录。
请在糖豆 App 中搜索歌名 → 点开视频 → 分享 → 复制链接，粘贴到工具中即可继续自动下载。

**Q：音频提取失败？**
确认已安装 ffmpeg 或 `pip install imageio-ffmpeg`。命令行模式会打印跳过提示。

**Q：下载到的是 `hello.mp4`？**
下载请求缺少 `Referer` 请求头，请使用本项目脚本（已内置正确请求头）。

---

## 已知限制

- **糖豆官网搜索已下线**（2026 年实测确认：`/so/search.htm` 404、App 接口加密混淆），搜索引擎也不收录糖豆站内视频。
  因此"按歌名搜索"的策略是：自动搜索全网该歌名的广场舞视频（糖豆站内链接命中则直接自动下载，
  其他平台的结果列出供参考），同时提供最可靠的兜底流程——在糖豆 App 搜歌名 → 分享 → 粘贴链接，之后全自动。
- 自动搜索依赖搜狗等引擎的可用性，频繁使用可能触发反爬（工具会自动重试并给出明确提示）。
- 需要网络可达 `tangdou.com`；若糖豆调整接口，脚本会打印明确错误，更新即可。
- 下载受糖豆服务端带宽与限流影响，为单线程下载。

---

## 免责声明

本项目仅用于个人学习、研究与合法范围内的内容备份。请尊重糖豆平台及视频作者的版权，
**不得将下载内容用于商业用途或未经授权的传播**。因使用本项目产生的一切法律责任由使用者自行承担。

---

## 许可证

[MIT](LICENSE) © 2026 hepengzhi
