#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
糖豆广场舞下载器 - 图形界面 (tangdou_gui.py)
============================================
基于 PySide6 + PyQt-Fluent-Widgets (qfluentwidgets) 的 Fluent 风格 GUI：
  - 链接/vid 批量下载（视频 + 音频）
  - 歌名搜索（自动搜糖豆站内链接，搜不到引导粘贴 App 分享链接）
  - 相关视频批量下载（同歌其他版本，可仅下舞曲 mp3）
  - 多任务并发下载、断点续传、失败重试
  - 设置持久化、深色模式、系统托盘、自动更新检查
后台线程下载，界面不卡顿；任务表 + 进度条 + 日志。

运行：python tangdou_gui.py
依赖：pip install PySide6 PySide6-Fluent-Widgets
      (音频提取还需 ffmpeg 或 pip install imageio-ffmpeg)
"""
import concurrent.futures
import json
import os
import subprocess
import sys
import threading
import webbrowser
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tdcore as td  # 核心逻辑包（api/download/search/log）

from PySide6.QtCore import Qt, QThread, QSettings, QObject, QTimer, QEvent, Signal, Slot
from PySide6.QtGui import QColor, QBrush, QIcon, QAction
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPlainTextEdit, QFileDialog, QTableWidgetItem, QProgressBar, QListWidgetItem,
    QAbstractItemView, QMessageBox, QSplitter, QMenu, QSystemTrayIcon, QGroupBox,
    QLabel,
)
from qfluentwidgets import (
    FluentWindow, FluentIcon, NavigationItemPosition,
    BodyLabel, SubtitleLabel, CaptionLabel,
    LineEdit, SearchLineEdit, ComboBox, SpinBox, SwitchButton,
    PrimaryPushButton, PushButton, TransparentPushButton,
    TableWidget, ListWidget, ProgressBar, HyperlinkButton,
    InfoBar, InfoBarPosition, setTheme, Theme, setThemeColor,
)
from qfluentwidgets.components.navigation.navigation_interface import NavigationInterface
from qfluentwidgets.components.navigation.navigation_panel import NavigationDisplayMode

VERSION = "1.6.0"
REPO = "hepengzhi/tangdou-downloader"
version_key = td.updater.version_key  # 供测试/兼容引用

STATUS_WAIT, STATUS_RUN, STATUS_OK, STATUS_FAIL = "等待", "下载中", "完成", "失败"
K_VIDEO, K_MP3, K_BILI = "video", "mp3", "bili"

# 状态列配色
STATUS_COLORS = {
    STATUS_WAIT: QColor("#8a8f98"),
    STATUS_RUN: QColor("#2f80ed"),
    STATUS_OK: QColor("#27ae60"),
    STATUS_FAIL: QColor("#eb5757"),
}

# 数据类控件样式（随主题切换；不能用 palette()，因 qfluentwidgets 只改样式表不改 QPalette）
DATA_QSS_LIGHT = """
QGroupBox {
    border: 1px solid #d9dee5; border-radius: 8px; margin-top: 12px;
    background: #fbfcfe; font-weight: bold;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: #344054; }
QPlainTextEdit {
    border: 1px solid #d0d7e2; border-radius: 8px; padding: 6px 8px;
    background: #ffffff; color: #1f2937; selection-background-color: rgba(47, 128, 237, 0.35);
}
QPlainTextEdit:focus { border-color: #2f80ed; }
QTableWidget, QListWidget { background: #ffffff; color: #1f2937; }
QHeaderView::section {
    background: #f2f5f9; color: #344054; border: none;
    border-bottom: 1px solid #d0d7e2; padding: 6px 8px; font-weight: bold;
}
QMenu { background: #ffffff; color: #1f2937; }
QMenu::item:selected { background: #e8f1fd; }
"""

DATA_QSS_DARK = """
QGroupBox {
    border: 1px solid #3a3f47; border-radius: 8px; margin-top: 12px;
    background: #292929; font-weight: bold;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: #e0e0e0; }
QPlainTextEdit {
    border: 1px solid #3a3f47; border-radius: 8px; padding: 6px 8px;
    background: #202020; color: #e0e0e0; selection-background-color: rgba(47, 128, 237, 0.5);
}
QPlainTextEdit:focus { border-color: #5b9cf5; }
QTableWidget, QListWidget { background: #202020; color: #e0e0e0; }
QHeaderView::section {
    background: #2a2a2a; color: #c0c8d0; border: none;
    border-bottom: 1px solid #3a3f47; padding: 6px 8px; font-weight: bold;
}
QMenu { background: #2b2b2b; color: #e0e0e0; }
QMenu::item:selected { background: rgba(47, 128, 237, 0.4); }
"""


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


def app_icon():
    """应用图标：打包后从 _MEIPASS/assets 读取，源码运行从项目 assets 读取。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(base, "assets", "icon.ico")
    return QIcon(p) if os.path.exists(p) else QIcon()


class SearchWorker(QThread):
    """歌名搜索线程。"""
    search_done = Signal(list)          # [{vid,title,url}]
    search_log = Signal(str)

    def __init__(self, keyword, parent=None):
        super().__init__(parent)
        self.keyword = keyword

    def run(self):
        try:
            results = td.search_all(self.keyword)
        except Exception as e:
            self.search_log.emit(f"搜索出错: {e}")
            results = []
        self.search_done.emit(results)


class _UpdateSignals(QObject):
    """更新检查的信号桥（普通线程安全地向主线程发射 Qt 信号）。
    不挂 parent：即使窗口先销毁，线程发射也是安全的（接收方销毁时连接自动断开）。"""
    result = Signal(bool, str, str, int, str)  # is_newer, tag, url, size, body


class UpdateChecker:
    """GitHub Release 自动更新检查（普通线程，避免 QThread 生命周期问题）。"""

    def __init__(self, repo, current, parent=None):
        self.repo = repo
        self.current = current
        self.signals = _UpdateSignals()
        self._t = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._t.start()

    def isRunning(self):
        return self._t.is_alive()

    def wait(self, ms=3000):
        self._t.join(timeout=ms / 1000.0)

    def _run(self):
        info = td.updater.latest_release(self.repo)
        if not info:
            self.signals.result.emit(False, "", "", 0, "")
            return
        newer = td.updater.is_newer(info["tag"], self.current)
        self.signals.result.emit(newer, info["tag"], info["url"], info["size"], info["body"])


class UpdateDownloadWorker(QThread):
    """在线更新：后台下载新版 exe（可取消）。"""
    progress = Signal(int, int)          # done, total
    done = Signal(str, bool, str)        # dest, ok, error

    def __init__(self, url, dest, expected_size=0, parent=None):
        super().__init__(parent)
        self.url = url
        self.dest = dest
        self.expected_size = expected_size
        self._stop = threading.Event()

    def cancel(self):
        self._stop.set()

    def run(self):
        ok = False
        err = ""
        try:
            def _prog(d, t):
                if self._stop.is_set():
                    raise KeyboardInterrupt
                self.progress.emit(d, t)

            ok = td.download(self.url, self.dest, log=lambda m: None,
                             progress=_prog,
                             headers={"User-Agent": "tangdou-downloader",
                                      "Referer": "https://github.com/"})
            if ok and self.expected_size:
                real = os.path.getsize(self.dest)
                if abs(real - self.expected_size) > max(1024, self.expected_size * 0.02):
                    ok = False
                    err = f"文件大小不符（{real}/{self.expected_size}）"
        except KeyboardInterrupt:
            err = "已取消"
            ok = False
        except Exception as e:
            err = str(e)
        if not ok and os.path.exists(self.dest):
            try:
                os.remove(self.dest)
            except Exception:
                pass
        self.done.emit(self.dest, ok, err)


class DownloadWorker(QThread):
    """下载任务队列线程（多任务并发）。tasks: [(kind, key, title)]。"""
    task_started = Signal(str, str)         # key, title
    task_progress = Signal(str, int, int)   # key, done, total
    task_done = Signal(str, bool, str, str)  # key, ok, mp4, mp3
    log = Signal(str)
    all_done = Signal()

    def __init__(self, tasks, outdir, want_audio, quality, workers=2, parent=None):
        super().__init__(parent)
        self.tasks = tasks
        self.outdir = outdir
        self.want_audio = want_audio
        self.quality = quality
        self.workers = max(1, min(workers, 4))
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()
        self.requestInterruption()

    def _progress(self, key, done, total):
        if self._stop.is_set() or self.isInterruptionRequested():
            raise KeyboardInterrupt
        self.task_progress.emit(key, done, total)

    def _do_task(self, kind, key, title):
        if self._stop.is_set():
            return
        self.task_started.emit(key, title)
        try:
            if kind == K_VIDEO:
                ok, mp4, mp3 = td.download_video(
                    key, self.outdir,
                    want_audio=self.want_audio,
                    quality=self.quality,
                    log=self.log.emit,
                    progress=lambda d, t: self._progress(key, d, t),
                )
            elif kind == K_BILI:
                ok, mp4, mp3 = td.bilibili.download_video_bili(
                    key, self.outdir,
                    log=self.log.emit,
                    progress=lambda d, t: self._progress(key, d, t),
                )
            else:
                fname = td.sanitize(title.replace("🎵 ", ""))
                dest = os.path.join(self.outdir, fname + ".mp3")
                self.log.emit(f"    下载舞曲 mp3 -> {os.path.basename(dest)}")
                ok = td.download(key, dest, log=self.log.emit,
                                 progress=lambda d, t: self._progress(key, d, t))
                mp4, mp3 = ("", dest) if ok else ("", "")
        except KeyboardInterrupt:
            return
        except Exception as e:
            self.log.emit(f"    ! 任务异常: {e}")
            ok, mp4, mp3 = False, "", ""
        self.task_done.emit(key, ok, mp4 or "", mp3 or "")

    def run(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as ex:
            futures = [ex.submit(self._do_task, *t) for t in self.tasks]
            for f in concurrent.futures.as_completed(futures):
                try:
                    f.result()
                except Exception as e:
                    self.log.emit(f"    ! 线程异常: {e}")
        self.log.emit(f"全部结束：共 {len(self.tasks)} 个任务。")
        self.all_done.emit()


class ResizableNavigation(NavigationInterface):
    """左侧导航栏：支持拖拽右侧边缘手动调整宽度，宽度记忆到 QSettings。

    qfluentwidgets 原版导航栏不支持拖动调宽，这里在其 NavigationPanel 上
    安装事件过滤：右边缘 8px 热区 → 按住拖动 → 实时 setExpandWidth + resize，
    并通过父类 eventFilter 的宽度同步让右侧内容区自动重排。
    """

    NAV_MIN = 180   # 展开态最窄宽度（px）
    NAV_MAX = 480   # 展开态最宽宽度（px）
    EDGE = 8        # 右侧拖拽热区宽度（px）

    def __init__(self, parent=None, showMenuButton=True, showReturnButton=False, collapsible=True):
        super().__init__(parent=parent, showMenuButton=showMenuButton,
                         showReturnButton=showReturnButton, collapsible=collapsible)
        self._drag_w = None       # 非 None = 正在拖拽（保存当前宽度）
        self._drag_start_x = 0
        self._drag_start_w = 0
        self._hover_edge = False
        self.panel.setMouseTracking(True)

    # ---------------- 宽度 ----------------
    def apply_width(self, width):
        """设置展开宽度（启动时恢复用户保存的宽度）"""
        width = max(self.NAV_MIN, min(self.NAV_MAX, int(width)))
        self.panel.setExpandWidth(width)

    def current_width(self):
        return int(getattr(self.panel, "expandWidth", self.NAV_MIN))

    def _save_width(self):
        try:
            QSettings("TangdouDownloader", "TangdouDownloader").setValue("nav_width", self.current_width())
        except Exception:
            pass

    def _nav_max(self):
        # 最宽不能把内容区挤没：至少留 360px 给右侧
        return max(self.NAV_MIN, min(self.NAV_MAX, self.window().width() - 360))

    def _set_nav_width(self, width):
        if self.panel.displayMode != NavigationDisplayMode.EXPAND:
            return
        width = max(self.NAV_MIN, min(self._nav_max(), int(width)))
        self.panel.setExpandWidth(width)                 # 更新展开宽度 + 导航项宽度
        self.panel.resize(width, self.panel.height())    # 触发父类 eventFilter → 外框同步 → 内容重排

    # ---------------- 拖拽 ----------------
    def _at_edge(self, e):
        return self.panel.width() - e.position().x() <= self.EDGE

    def eventFilter(self, obj, e):
        if obj is self.panel:
            t = e.type()
            if t == QEvent.MouseButtonPress and e.button() == Qt.LeftButton and self._at_edge(e):
                if self.panel.displayMode == NavigationDisplayMode.EXPAND:
                    self._drag_start_x = e.globalPosition().x()
                    self._drag_start_w = self.panel.width()
                    self._drag_w = self._drag_start_w
                    self.panel.setCursor(Qt.SizeHorCursor)
                    return True
            elif t == QEvent.MouseMove:
                if self._drag_w is not None:
                    dx = e.globalPosition().x() - self._drag_start_x
                    self._set_nav_width(self._drag_start_w + int(round(dx)))
                    return True
                edge = self._at_edge(e) and self.panel.displayMode == NavigationDisplayMode.EXPAND
                if edge != self._hover_edge:
                    self._hover_edge = edge
                    self.panel.setCursor(Qt.SizeHorCursor if edge else Qt.ArrowCursor)
            elif t == QEvent.MouseButtonRelease and self._drag_w is not None:
                self._drag_w = None
                self._hover_edge = False
                self.panel.setCursor(Qt.ArrowCursor)
                self._save_width()
                return True
        return super().eventFilter(obj, e)


class MainWindow(FluentWindow):
    def __init__(self):
        # 用可拖动调宽的导航栏替换默认导航栏（须在 super().__init__ 之前注入）
        try:
            from qfluentwidgets.window import fluent_window as _fw
            _fw.NavigationInterface = ResizableNavigation
        except Exception:
            pass
        super().__init__()
        self._latest_tag = None  # 检测到的新版本（用于标题栏提示）
        self._refresh_title()
        self.setWindowIcon(app_icon())
        self.resize(1100, 800)
        self.setMinimumSize(920, 640)
        # 导航栏：展开态默认 260px（不再挡住右侧界面），并支持拖拽右侧边缘调宽
        try:
            saved_w = int(QSettings("TangdouDownloader", "TangdouDownloader").value("nav_width", 260) or 260)
            self.navigationInterface.apply_width(saved_w)
            self.navigationInterface.setMinimumExpandWidth(700)  # 窄窗口下文字也常显
        except Exception:
            pass

        self._worker = None
        self._search_worker = None
        self._update_worker = None
        self._row_of_key = {}
        self._ok_count = 0
        self._tray = None
        self._dark = False
        self.settings = QSettings("TangdouDownloader", "TangdouDownloader")

        self._build_pages()
        self._build_navigation()
        # 启动即展开为窄导航（文字常显、不遮内容；点菜单按钮可收起为纯图标）
        try:
            self.navigationInterface.expand(False)
        except Exception:
            pass
        self._load_settings()
        self._setup_tray()
        self._update_task_count()
        self._set_status("就绪")
        QTimer.singleShot(1500, self._maybe_show_tutorial)

    # ---------------- 页面构建 ----------------
    def _build_pages(self):
        self.link_page = self._page_link()
        self.link_page.setObjectName("linkPage")
        self.song_page = self._page_song()
        self.song_page.setObjectName("songPage")
        self.related_page = self._page_related()
        self.related_page.setObjectName("relatedPage")
        self.setting_page = self._page_setting()
        self.setting_page.setObjectName("settingPage")

    def _build_navigation(self):
        self.addSubInterface(self.link_page, FluentIcon.DOWNLOAD, "链接下载")
        self.addSubInterface(self.song_page, FluentIcon.SEARCH, "歌名搜索")
        self.addSubInterface(self.related_page, FluentIcon.ALBUM, "相关批量")
        self.addSubInterface(self.setting_page, FluentIcon.SETTING, "设置",
                             position=NavigationItemPosition.BOTTOM)

    def _page_link(self):
        page = QWidget(self)
        v = QVBoxLayout(page)
        v.setContentsMargins(20, 16, 20, 12)
        v.setSpacing(10)

        v.addWidget(SubtitleLabel("链接下载"))
        v.addWidget(BodyLabel("粘贴糖豆分享链接或 vid 编号（每行一个，可多行）："))

        self.edit_links = QPlainTextEdit()
        self.edit_links.setPlaceholderText(
            "https://www.tangdoucdn.com/h5/play?vid=20000002258422&...\n20000002258422\n\n"
            "提示：糖豆 App 中 视频 → 分享 → 复制链接")
        self.edit_links.setMinimumHeight(100)
        v.addWidget(self.edit_links, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        btn_clear = TransparentPushButton("清空")
        btn_clear.clicked.connect(lambda: self.edit_links.clear())
        row.addWidget(btn_clear)
        btn_add = PrimaryPushButton("＋ 加入任务")
        btn_add.clicked.connect(self.add_links)
        row.addWidget(btn_add)
        v.addLayout(row)

        # 任务列表 + 日志
        splitter = QSplitter(Qt.Vertical)

        self.grp_tasks = QGroupBox("任务列表")
        gv = QVBoxLayout(self.grp_tasks)
        gv.setContentsMargins(14, 18, 14, 10)
        gv.setSpacing(6)
        self.table = TableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["状态", "标题", "进度"])
        self.table.setColumnWidth(0, 76)
        self.table.setColumnWidth(2, 190)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(TableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(TableWidget.SelectRows)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_menu)
        self.table.cellDoubleClicked.connect(self._on_table_double_click)
        gv.addWidget(self.table)

        # 空态引导（任务为 0 时覆盖在表格上）
        self._empty_hint = QLabel(
            "暂无任务\n\n"
            "① 在「链接下载」页粘贴糖豆分享链接 / vid\n"
            "② 或去「歌名搜索」按歌名找视频\n"
            "③ 手机糖豆 App：搜歌名 → 分享 → 复制链接，粘贴即可",
            self.table)
        self._empty_hint.setAlignment(Qt.AlignCenter)
        self._empty_hint.setWordWrap(True)
        self._empty_hint.setStyleSheet(
            "color: #8a8f98; font-size: 11pt; background: transparent;")
        _table_resize = self.table.resizeEvent

        def _resize(e):
            self._empty_hint.setGeometry(self.table.rect())
            _table_resize(e)

        self.table.resizeEvent = _resize

        row_btns = QHBoxLayout()
        row_btns.setSpacing(8)
        self.btn_start = PrimaryPushButton("▶ 开始下载")
        self.btn_start.clicked.connect(self.start_download)
        self.btn_stop = PushButton("■ 停止")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_download)
        btn_retry = PushButton("重试失败")
        btn_retry.clicked.connect(self.retry_failed)
        btn_del = PushButton("删除选中")
        btn_del.clicked.connect(self.delete_selected_tasks)
        btn_clear_done = PushButton("清空完成项")
        btn_clear_done.clicked.connect(self.clear_done)
        for b in (self.btn_start, self.btn_stop, btn_retry, btn_del, btn_clear_done):
            row_btns.addWidget(b)
        row_btns.addStretch(1)
        gv.addLayout(row_btns)
        splitter.addWidget(self.grp_tasks)

        grp_log = QGroupBox("日志")
        lv = QVBoxLayout(grp_log)
        lv.setContentsMargins(14, 18, 14, 8)
        lv.setSpacing(6)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        lv.addWidget(self.log_view)
        lr = QHBoxLayout()
        lr.addStretch(1)
        btn_clear_log = TransparentPushButton("清空日志")
        btn_clear_log.clicked.connect(lambda: self.log_view.clear())
        lr.addWidget(btn_clear_log)
        lv.addLayout(lr)
        splitter.addWidget(grp_log)
        splitter.setSizes([440, 250])

        v.addWidget(splitter, 3)

        self._status_label = CaptionLabel("")
        v.addWidget(self._status_label)
        return page

    def _page_song(self):
        page = QWidget(self)
        v = QVBoxLayout(page)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(10)
        v.addWidget(SubtitleLabel("歌名搜索"))

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(BodyLabel("歌名:"))
        self.edit_song = SearchLineEdit()
        self.edit_song.setPlaceholderText("例如：最炫民族风")
        self.edit_song.returnPressed.connect(self.do_search)
        row.addWidget(self.edit_song, 1)
        self.btn_search = PrimaryPushButton("搜索")
        self.btn_search.setMinimumWidth(100)
        self.btn_search.clicked.connect(self.do_search)
        row.addWidget(self.btn_search)
        v.addLayout(row)

        label_results = BodyLabel("搜索结果（🎬 糖豆 / 📺 B站 = 可自动下载；🔗 全网 = 参考链接）：")
        label_results.setWordWrap(True)
        v.addWidget(label_results)
        self.list_results = ListWidget()
        self.list_results.setSelectionMode(QAbstractItemView.ExtendedSelection)
        v.addWidget(self.list_results, 1)

        row2 = QHBoxLayout()
        row2.addStretch(1)
        btn_add = PrimaryPushButton("＋ 将选中结果加入任务")
        btn_add.clicked.connect(self.add_selected_results)
        row2.addWidget(btn_add)
        v.addLayout(row2)

        v.addSpacing(6)
        label_paste_hint = BodyLabel("自动搜索无结果时：在糖豆 App 搜索歌名 → 点开视频 → 分享 → 复制链接，粘贴到下面：")
        label_paste_hint.setWordWrap(True)
        v.addWidget(label_paste_hint)
        self.edit_paste = QPlainTextEdit()
        self.edit_paste.setPlaceholderText("粘贴 App 分享链接，每行一个")
        self.edit_paste.setMaximumHeight(80)
        v.addWidget(self.edit_paste)
        row3 = QHBoxLayout()
        row3.addStretch(1)
        btn_paste = PrimaryPushButton("＋ 将粘贴的链接加入任务")
        btn_paste.clicked.connect(self.add_pasted_links)
        row3.addWidget(btn_paste)
        v.addLayout(row3)
        return page

    def _page_related(self):
        page = QWidget(self)
        v = QVBoxLayout(page)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(10)
        v.addWidget(SubtitleLabel("相关批量"))

        row = QHBoxLayout()
        row.addWidget(BodyLabel("基准视频 vid:"))
        self.edit_base_vid = LineEdit()
        self.edit_base_vid.setPlaceholderText("20000002258422")
        row.addWidget(self.edit_base_vid, 1)
        self.check_audio_only = SwitchButton("仅下载舞曲 mp3")
        row.addWidget(self.check_audio_only)
        row.addWidget(BodyLabel("数量:"))
        self.spin_limit = SpinBox()
        self.spin_limit.setRange(1, 20)
        self.spin_limit.setValue(20)
        row.addWidget(self.spin_limit)
        btn = PrimaryPushButton("＋ 加入任务")
        btn.clicked.connect(self.add_related)
        row.addWidget(btn)
        v.addLayout(row)

        hint = BodyLabel("说明：拉取该视频的 20 个相关推荐（通常是同一首歌的其他版本）逐个加入任务；\n"
                         "勾选「仅下载舞曲 mp3」则直接下载糖豆舞曲原音频，无需安装 ffmpeg。")
        hint.setWordWrap(True)
        v.addWidget(hint)
        v.addStretch(1)
        return page

    def _page_setting(self):
        page = QWidget(self)
        v = QVBoxLayout(page)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(10)
        v.addWidget(SubtitleLabel("设置"))

        grp1 = QGroupBox("下载设置")
        g1 = QVBoxLayout(grp1)
        g1.setContentsMargins(16, 18, 16, 12)
        g1.setSpacing(12)

        r1 = QHBoxLayout()
        r1.addWidget(BodyLabel("保存目录:"))
        self.edit_dir = LineEdit()
        self.edit_dir.setText(td.default_download_dir())
        self.edit_dir.setMinimumWidth(260)
        r1.addWidget(self.edit_dir, 1)
        btn_browse = PushButton("浏览…")
        btn_browse.clicked.connect(self._pick_dir)
        r1.addWidget(btn_browse)
        btn_open = PrimaryPushButton("打开目录")
        btn_open.clicked.connect(self.open_dir)
        r1.addWidget(btn_open)
        g1.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(BodyLabel("清晰度:"))
        self.combo_quality = ComboBox()
        self.combo_quality.addItem("自动（优先 720P）", "auto")
        self.combo_quality.addItem("720P", "h720p")
        self.combo_quality.addItem("540P", "h540p")
        self.combo_quality.addItem("全部清晰度", "all")
        r2.addWidget(self.combo_quality)
        r2.addSpacing(24)
        r2.addWidget(BodyLabel("并发下载:"))
        self.spin_workers = SpinBox()
        self.spin_workers.setRange(1, 4)
        self.spin_workers.setValue(2)
        r2.addWidget(self.spin_workers)
        r2.addWidget(CaptionLabel("(糖豆 CDN 限流，建议 1-3)"))
        r2.addStretch(1)
        g1.addLayout(r2)

        r3 = QHBoxLayout()
        self.check_audio = SwitchButton("提取音频 (mp3)")
        self.check_audio.setOnText("开")
        self.check_audio.setOffText("关")
        self.check_audio.setChecked(True)
        r3.addWidget(self.check_audio)
        r3.addSpacing(24)
        self.btn_theme = SwitchButton("深色模式")
        self.btn_theme.setOnText("深色")
        self.btn_theme.setOffText("浅色")
        self.btn_theme.checkedChanged.connect(lambda c: self.set_dark(c))
        r3.addWidget(self.btn_theme)
        r3.addStretch(1)
        g1.addLayout(r3)
        v.addWidget(grp1)

        grp2 = QGroupBox("关于")
        g2 = QVBoxLayout(grp2)
        g2.setContentsMargins(16, 18, 16, 12)
        g2.setSpacing(10)
        self._ver_label = BodyLabel(f"糖豆广场舞下载器 v{VERSION}")
        g2.addWidget(self._ver_label)
        r4 = QHBoxLayout()
        self.btn_check_update = PrimaryPushButton("检查更新")
        self.btn_check_update.clicked.connect(self.check_update_now)
        r4.addWidget(self.btn_check_update)
        link = HyperlinkButton("https://github.com/hepengzhi/tangdou-downloader", "GitHub 主页 ↗")
        r4.addWidget(link)
        r4.addStretch(1)
        g2.addLayout(r4)
        v.addWidget(grp2)
        v.addStretch(1)
        return page

    # ---------------- 系统托盘 ----------------
    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QSystemTrayIcon(app_icon(), self)
        self._tray.setToolTip(f"糖豆广场舞下载器 v{VERSION}")
        menu = QMenu(self)
        act_show = QAction("显示主窗口", menu)
        act_show.triggered.connect(self._show_window)
        menu.addAction(act_show)
        menu.addSeparator()
        act_start = QAction("开始下载", menu)
        act_start.triggered.connect(self.start_download)
        menu.addAction(act_start)
        act_stop = QAction("停止", menu)
        act_stop.triggered.connect(self.stop_download)
        menu.addAction(act_stop)
        menu.addSeparator()
        act_quit = QAction("退出", menu)
        act_quit.triggered.connect(self.quit_app)
        menu.addAction(act_quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(
            lambda reason: self._show_window() if reason == QSystemTrayIcon.DoubleClick else None)
        self._tray.show()

    def _show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _notify(self, title, msg, icon=QSystemTrayIcon.Information):
        if self._tray:
            self._tray.showMessage(title, msg, icon, 5000)

    def quit_app(self):
        self._save_settings()
        self._wait_background_threads()
        QApplication.instance().quit()

    def _wait_background_threads(self):
        for w in (self._update_worker, self._search_worker, self._worker):
            if w is not None and w.isRunning():
                w.wait(3000)

    def closeEvent(self, event):
        """关闭窗口 = 最小化到托盘，下载继续后台运行；真正退出用托盘菜单「退出」。"""
        self._save_settings()
        if self._tray is not None:
            event.ignore()
            self.hide()
            self._notify("已最小化到托盘", "下载任务仍在后台继续，点击托盘图标可恢复窗口。",
                         QSystemTrayIcon.Information)
        else:
            self._wait_background_threads()
            super().closeEvent(event)

    # ---------------- 设置持久化与主题 ----------------
    def _load_settings(self):
        s = self.settings
        self.edit_dir.setText(s.value("save_dir", td.default_download_dir(), str))
        self.combo_quality.setCurrentIndex(int(s.value("quality_idx", 0)))
        self.check_audio.setChecked(s.value("audio", True, type=bool))
        self.spin_workers.setValue(int(s.value("workers", 2)))
        self._dark = s.value("dark_mode", "0") == "1"
        self.btn_theme.setChecked(self._dark)
        geo = s.value("geometry", b"", bytes)
        if geo:
            self.restoreGeometry(geo)
        self._apply_theme()

    def _save_settings(self):
        s = self.settings
        s.setValue("save_dir", self.edit_dir.text())
        s.setValue("quality_idx", self.combo_quality.currentIndex())
        s.setValue("audio", self.check_audio.isChecked())
        s.setValue("workers", self.spin_workers.value())
        s.setValue("dark_mode", "1" if self._dark else "0")
        s.setValue("geometry", self.saveGeometry())

    def set_dark(self, dark):
        self._dark = bool(dark)
        self._apply_theme()

    def toggle_theme(self):
        self._dark = not self._dark
        self.btn_theme.setChecked(self._dark)
        self._apply_theme()

    def _apply_theme(self):
        setTheme(Theme.DARK if self._dark else Theme.LIGHT)
        setThemeColor("#2f80ed")
        self.setStyleSheet(DATA_QSS_DARK if self._dark else DATA_QSS_LIGHT)
        self._apply_danger_style()

    def _apply_danger_style(self):
        """停止按钮危险色（fluent 会覆盖内联样式，需在主题应用后追加）。"""
        btn = getattr(self, "btn_stop", None)
        if btn is None:
            return
        btn.setStyleSheet(btn.styleSheet() + "\n"
                          "QPushButton { color: #eb5757; }\n"
                          "QPushButton:disabled { color: #8a8f98; }")

    # ---------------- 自动更新 ----------------
    def start_update_check(self):
        """启动后延迟自动检查更新（避免与窗口初始化竞争）。"""
        self._check_update()

    def _check_update(self, manual=False):
        if self._update_worker and self._update_worker.isRunning():
            return
        self._update_worker = UpdateChecker(REPO, VERSION, self)
        self._update_worker.signals.result.connect(
            lambda *a: self._on_update_result(*a, manual=manual))
        self._update_worker.start()

    @Slot()
    def check_update_now(self):
        if self._update_worker and self._update_worker.isRunning():
            return  # 防连点
        self.log("正在检查更新…")
        self.btn_check_update.setEnabled(False)
        self.btn_check_update.setText("检查中…")
        InfoBar.info("正在检查更新", "请稍候…", parent=self.setting_page,
                     position=InfoBarPosition.TOP_RIGHT, duration=2500)
        self._check_update(manual=True)

    def _refresh_title(self):
        """窗口标题：检测到新版本时在标题栏显著提示。"""
        if self._latest_tag:
            self.setWindowTitle(f"糖豆广场舞下载器 v{VERSION} ⬆ 有新版 {self._latest_tag}")
        else:
            self.setWindowTitle(f"糖豆广场舞下载器 v{VERSION}")
        tray = getattr(self, "_tray", None)
        if tray is not None:
            tip = f"糖豆广场舞下载器 v{VERSION}"
            if self._latest_tag:
                tip += f" ⬆ 有新版 {self._latest_tag}"
            tray.setToolTip(tip)

    @Slot(bool, str, str, int, str)
    def _on_update_result(self, is_newer, tag, url, size, body, manual=False):
        if hasattr(self, "btn_check_update"):
            self.btn_check_update.setEnabled(True)
            self.btn_check_update.setText("检查更新")
        if not is_newer:
            if manual:
                InfoBar.success("已是最新版本", f"当前 v{VERSION}", parent=self.setting_page,
                                position=InfoBarPosition.TOP_RIGHT, duration=3000)
            return
        self.log(f"发现新版本 {tag}（当前 {VERSION}）")
        self._latest_tag = tag
        self._refresh_title()  # 标题栏常驻提示
        self._notify("发现新版本", f"{tag}（当前 {VERSION}）", QSystemTrayIcon.Information)
        box = QMessageBox(self)
        box.setWindowTitle("发现新版本")
        box.setText(f"检测到新版本 <b>{tag}</b>（当前 {VERSION}）\n\n{body[:200]}")
        btn_up = box.addButton("立即更新", QMessageBox.AcceptRole)
        box.addButton("稍后再说", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is btn_up and url:
            self._start_update_download(url, size)

    # ---------------- 在线更新：下载 + 安装 ----------------
    def _start_update_download(self, url, size):
        from PySide6.QtWidgets import QDialog, QLabel, QDialogButtonBox
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        updir = os.path.join(base, "TangdouDownloader", "update")
        os.makedirs(updir, exist_ok=True)
        dest = os.path.join(updir, "TangdouDownloader.exe.new")

        dlg = QDialog(self)
        dlg.setWindowTitle("正在下载更新")
        dlg.setMinimumWidth(420)
        lay = QVBoxLayout(dlg)
        lbl = QLabel(f"正在下载新版本（约 {size/1048576:.1f} MB）…")
        lay.addWidget(lbl)
        bar = ProgressBar()
        bar.setRange(0, 100)
        lay.addWidget(bar)
        btns = QDialogButtonBox(QDialogButtonBox.Cancel)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)

        self._update_dl = UpdateDownloadWorker(url, dest, size, self)
        self._update_dl.progress.connect(lambda d, t: self._on_dl_progress(d, t, bar, lbl))
        self._update_dl.done.connect(lambda *a: self._on_dl_done(dlg, *a))
        self._update_dl.finished.connect(dlg.accept)
        self._update_dl.start()
        dlg.exec()

    def _on_dl_progress(self, done, total, bar, lbl):
        if total > 0:
            pct = int(done * 100 / total)
            bar.setValue(pct)
            lbl.setText(f"正在下载更新… {done/1048576:.1f}/{total/1048576:.1f} MB")
        else:
            bar.setValue(0)
            lbl.setText(f"正在下载更新… {done/1048576:.1f} MB")

    @Slot(str, bool, str)
    def _on_dl_done(self, dlg, dest, ok, err):
        if not ok:
            self.log(f"更新下载失败: {err}")
            InfoBar.error("更新失败", err or "未知错误", parent=self.link_page,
                          position=InfoBarPosition.TOP_RIGHT, duration=5000)
            dlg.reject()
            return
        self.log("更新下载完成，准备安装…")
        self._install_update(dest)

    def _install_update(self, new_exe):
        """替换当前程序。打包版(exe)：写 bat 自替换后重启；源码版：保存到 Downloads。"""
        if getattr(sys, "frozen", False) and os.path.exists(sys.executable):
            exe = sys.executable
            bat = os.path.join(os.path.dirname(exe), "update_tangdou.bat")
            try:
                with open(bat, "w", encoding="utf-8") as f:
                    f.write(
                        "@echo off\r\n"
                        "timeout /t 2 /nobreak >nul\r\n"
                        ":loop\r\n"
                        f'tasklist /fi "imagename eq {os.path.basename(exe)}" | find /i "{os.path.basename(exe)}" >nul\r\n'
                        "if %errorlevel%==0 ( timeout /t 1 /nobreak >nul & goto loop )\r\n"
                        f'move /y "{new_exe}" "{exe}" >nul\r\n'
                        f'start "" "{exe}"\r\n'
                        "del \"%~f0\"\r\n"
                    )
                subprocess.Popen(["cmd", "/c", "start", "", bat],
                                 creationflags=0x08000000)  # CREATE_NO_WINDOW
                self.log("已开始在线更新：程序将自动重启，请稍候…")
                QMessageBox.information(self, "更新完成",
                                        "新版本已下载，程序即将自动重启完成更新。")
                self._save_settings()
                QApplication.instance().quit()
                return
            except Exception as e:
                self.log(f"自动安装失败({e})，改为保存到下载目录")
        # 源码运行 / 兜底：保存到 Downloads
        try:
            dst = os.path.join(td.default_download_dir(), "TangdouDownloader.exe")
            import shutil
            shutil.move(new_exe, dst)
            os.startfile(os.path.dirname(dst))
            InfoBar.success("更新已下载", f"已保存到 {dst}\n（源码运行版无法自动替换，请手动替换后重启）",
                            parent=self.link_page, position=InfoBarPosition.TOP_RIGHT, duration=6000)
        except Exception as e:
            InfoBar.error("保存失败", str(e), parent=self.link_page,
                          position=InfoBarPosition.TOP_RIGHT, duration=5000)

    # ---------------- 工具方法 ----------------
    def log(self, text):
        self.log_view.appendPlainText(text)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())
        td.get_logger().info(text)

    def _set_status(self, msg):
        self._status_label.setText(msg)

    def _toast(self, kind, title, content=None):
        bar = getattr(InfoBar, kind, None)
        if bar:
            bar(title, content or "", isClosable=True, duration=3000,
                parent=self.link_page, position=InfoBarPosition.TOP_RIGHT)

    def _update_task_count(self):
        n = self.table.rowCount()
        self.grp_tasks.setTitle(f"任务列表（共 {n} 项）")
        # 空态引导随任务数显隐
        hint = getattr(self, "_empty_hint", None)
        if hint is not None:
            hint.setVisible(n == 0)
            if n == 0:
                hint.setGeometry(self.table.rect())
                hint.raise_()

    def _maybe_show_tutorial(self):
        """首次启动弹一次使用教程。"""
        if self.settings.value("tutorial_done", "0") == "1":
            return
        self.settings.setValue("tutorial_done", "1")
        box = QMessageBox(self)
        box.setWindowTitle("三步上手")
        box.setText(
            "三步使用：\n\n"
            "① 手机打开「糖豆」App → 搜索歌名 → 点开视频 → 分享 → 复制链接\n"
            "② 粘贴到「链接下载」页（可一次粘贴多个），或到「歌名搜索」页按歌名搜\n"
            "③ 点「加入任务」→「开始下载」，视频(mp4)和音频(mp3)自动保存到下载目录\n\n"
            "下载过程中最小化到托盘会继续后台运行，完成有系统通知。")
        box.addButton("知道了", QMessageBox.AcceptRole)
        box.exec()

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择保存目录", self.edit_dir.text())
        if d:
            self.edit_dir.setText(d)

    def _add_row(self, key, title, kind=K_VIDEO):
        if key in self._row_of_key:
            return self._row_of_key[key]
        r = self.table.rowCount()
        self.table.insertRow(r)
        item_status = QTableWidgetItem(STATUS_WAIT)
        item_status.setForeground(QBrush(STATUS_COLORS[STATUS_WAIT]))
        item_status.setTextAlignment(Qt.AlignCenter)
        item_title = QTableWidgetItem(title or key)
        item_title.setData(Qt.UserRole, key)      # 任务 key（vid 或 mp3url）
        item_title.setData(Qt.UserRole + 1, kind)  # 任务类型
        item_title.setData(Qt.UserRole + 2, "")    # 完成后的 mp4 路径
        item_title.setData(Qt.UserRole + 3, "")    # 完成后的 mp3 路径
        self.table.setItem(r, 0, item_status)
        self.table.setItem(r, 1, item_title)
        bar = ProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setFormat("等待")
        self.table.setCellWidget(r, 2, bar)
        self._row_of_key[key] = r
        self._update_task_count()
        return r

    def _set_row_status(self, r, status, bar_text=None, bar_value=None):
        item = self.table.item(r, 0)
        item.setText(status)
        item.setForeground(QBrush(STATUS_COLORS.get(status, QColor("#1f2937"))))
        bar = self.table.cellWidget(r, 2)
        if bar_text is not None:
            bar.setFormat(bar_text)
        if bar_value is not None:
            bar.setValue(bar_value)

    def _enqueue_links(self, text):
        added = 0
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            vid = td.extract_vid(line)
            if not vid:
                self.log(f"无法从「{line}」识别 vid，已跳过")
                continue
            self._add_row(vid, f"vid {vid}", K_VIDEO)
            added += 1
        if added:
            self._set_status(f"已加入 {added} 个任务")
            self._toast("success", f"已加入 {added} 个任务")
        else:
            self._set_status("没有识别到有效链接/vid")

    # ---------------- 按钮动作 ----------------
    @Slot()
    def add_links(self):
        self._enqueue_links(self.edit_links.toPlainText())
        if self.edit_links.toPlainText().strip():
            self.edit_links.clear()

    @Slot()
    def add_pasted_links(self):
        self._enqueue_links(self.edit_paste.toPlainText())
        if self.edit_paste.toPlainText().strip():
            self.edit_paste.clear()

    @Slot()
    def do_search(self):
        kw = self.edit_song.text().strip()
        if not kw:
            QMessageBox.information(self, "提示", "请先输入歌名")
            return
        self.btn_search.setEnabled(False)
        self.btn_search.setText("搜索中…")
        self.log(f"== 搜索歌名: {kw} ==")
        self._search_worker = SearchWorker(kw, self)
        self._search_worker.search_done.connect(self._on_search_done)
        self._search_worker.search_log.connect(self.log)
        self._search_worker.start()

    @Slot(list)
    def _on_search_done(self, results):
        self.btn_search.setEnabled(True)
        self.btn_search.setText("搜索")
        self.list_results.clear()
        td_n = sum(1 for r in results if r.get("source") == "tangdou")
        bili_n = sum(1 for r in results if r.get("source") == "bili")
        others_n = len(results) - td_n - bili_n
        if results:
            for r in results:
                li = QListWidgetItem()
                src = r.get("source")
                if src == "tangdou":
                    li.setText(f"🎬 糖豆 [{r['vid']}] {r['title']}")
                    li.setData(Qt.UserRole, r["vid"])
                    li.setData(Qt.UserRole + 1, K_VIDEO)
                elif src == "bili":
                    li.setText(f"📺 B站 [{r['bvid']}] {r['title']}")
                    li.setData(Qt.UserRole, r["bvid"])
                    li.setData(Qt.UserRole + 1, K_BILI)
                    li.setToolTip(f"UP主: {r.get('author','')} 播放: {r.get('play','')} 时长: {r.get('duration','')}")
                else:
                    li.setText(f"🔗 全网: {r['title']}")
                    li.setData(Qt.UserRole, None)
                    li.setFlags(li.flags() & ~Qt.ItemIsSelectable)
                    li.setToolTip(r.get("url") or "")
                self.list_results.addItem(li)
            msg = f"可下载：糖豆 {td_n} + B站 {bili_n}，全网参考 {others_n} 条"
            self._set_status(msg)
            self.log(f"搜索结果：糖豆 {td_n} + B站 {bili_n}（可下载），全网参考 {others_n} 条")
        else:
            self._set_status("未搜到结果，请在糖豆 App 搜索歌名后粘贴分享链接")
            self.log("未搜到结果。糖豆官网搜索已下线，请在糖豆 App 搜索歌名 → 分享 → 复制链接 → 粘贴到下方输入框。")

    @Slot()
    def add_selected_results(self):
        items = self.list_results.selectedItems()
        if not items:
            QMessageBox.information(self, "提示", "请先在搜索结果里选择可下载的视频（🎬 糖豆 / 📺 B站 项）")
            return
        added = 0
        for it in items:
            key = it.data(Qt.UserRole)
            kind = it.data(Qt.UserRole + 1)
            if not key or kind not in (K_VIDEO, K_BILI):
                continue
            text = it.text()
            title = text.split("] ", 1)[-1] if "] " in text else key
            self._add_row(key, title, kind)
            added += 1
        if added:
            self._set_status(f"已加入 {added} 个下载任务（糖豆/B站）")
        else:
            QMessageBox.information(self, "提示", "请选择 🎬 糖豆 或 📺 B站 开头的项（全网参考链接不支持自动下载）")

    @Slot()
    def add_related(self):
        vid = td.extract_vid(self.edit_base_vid.text())
        if not vid:
            QMessageBox.information(self, "提示", "请输入有效的基准视频 vid")
            return
        self.log(f"== 拉取 {vid} 的相关视频 ==")
        try:
            items = td.get_related(vid)
        except Exception as e:
            QMessageBox.warning(self, "出错", f"获取相关视频失败: {e}")
            return
        if not items:
            QMessageBox.information(self, "提示", "该视频没有相关推荐")
            return
        audio_only = self.check_audio_only.isChecked()
        limit = self.spin_limit.value()
        added = 0
        for it in items[:limit]:
            title = td.sanitize(it.get("title") or "")
            if audio_only:
                mp3url = it.get("mp3url")
                if mp3url:
                    self._add_row(mp3url, "🎵 " + title, K_MP3)
                    added += 1
            else:
                vid2 = str(it.get("vid") or "")
                if vid2:
                    self._add_row(vid2, title, K_VIDEO)
                    added += 1
        self.log(f"已加入 {added} 个相关任务" + ("（仅舞曲 mp3）" if audio_only else ""))
        self._set_status(f"已加入 {added} 个相关任务")

    @Slot()
    def start_download(self):
        if self._worker and self._worker.isRunning():
            return
        tasks = []
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).text() in (STATUS_OK, STATUS_RUN):
                continue
            item = self.table.item(r, 1)
            key = item.data(Qt.UserRole)
            kind = item.data(Qt.UserRole + 1) or K_VIDEO
            if not key:
                continue
            tasks.append((kind, key, item.text()))
        if not tasks:
            QMessageBox.information(self, "提示", "任务列表为空，请先添加任务")
            return
        outdir = self.edit_dir.text().strip() or "Download"
        os.makedirs(outdir, exist_ok=True)
        self._ok_count = 0
        self._worker = DownloadWorker(
            tasks, outdir,
            want_audio=self.check_audio.isChecked(),
            quality=self.combo_quality.currentData(),
            workers=self.spin_workers.value(),
            parent=self,
        )
        self._worker.task_started.connect(self._on_task_started)
        self._worker.task_progress.connect(self._on_task_progress)
        self._worker.task_done.connect(self._on_task_done)
        self._worker.log.connect(self.log)
        self._worker.all_done.connect(self._on_all_done)
        self._worker.start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._set_status(f"开始下载 {len(tasks)} 个任务（并发 {self.spin_workers.value()}）…")

    @Slot(str, str)
    def _on_task_started(self, key, title):
        r = self._row_of_key.get(key)
        if r is not None:
            self._set_row_status(r, STATUS_RUN, "准备中…", 0)

    @Slot(str, int, int)
    def _on_task_progress(self, key, done, total):
        r = self._row_of_key.get(key)
        if r is None:
            return
        bar = self.table.cellWidget(r, 2)
        if total > 0:
            pct = int(done * 100 / total)
            bar.setValue(pct)
            bar.setFormat(f"{done/1048576:.1f}/{total/1048576:.1f} MB")
        else:
            bar.setValue(0)
            bar.setFormat(f"{done/1048576:.1f} MB")

    @Slot(str, bool, str, str)
    def _on_task_done(self, key, ok, mp4, mp3):
        r = self._row_of_key.get(key)
        if r is not None:
            status = STATUS_OK if ok else STATUS_FAIL
            self._set_row_status(r, status, "100%" if ok else "失败", 100 if ok else 0)
            item = self.table.item(r, 1)
            item.setData(Qt.UserRole + 2, mp4)
            item.setData(Qt.UserRole + 3, mp3)
            if ok:
                self._ok_count += 1

    @Slot()
    def _on_all_done(self):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        done = self.table.rowCount() - self._fail_count()
        msg = f"全部任务结束：成功 {self._ok_count} / {done} 个"
        self._set_status(msg)
        self._notify("下载完成", msg, QSystemTrayIcon.Information)

    def _fail_count(self):
        n = 0
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).text() == STATUS_FAIL:
                n += 1
        return n

    @Slot()
    def stop_download(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self.btn_stop.setEnabled(False)
            self.log("正在停止（已开始的下载会尽快中止，已下载部分保留可续传）…")
            self._set_status("停止中…")

    @Slot()
    def retry_failed(self):
        changed = 0
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).text() in (STATUS_FAIL, STATUS_RUN, STATUS_WAIT):
                self._set_row_status(r, STATUS_WAIT, "等待", 0)
                changed += 1
        self._set_status(f"已重置 {changed} 个任务，可重新开始下载" if changed else "没有可重试的任务")

    @Slot()
    def open_dir(self):
        d = self.edit_dir.text().strip() or "Download"
        os.makedirs(d, exist_ok=True)
        os.startfile(os.path.abspath(d))

    @Slot()
    def clear_done(self):
        for r in range(self.table.rowCount() - 1, -1, -1):
            if self.table.item(r, 0).text() in (STATUS_OK, STATUS_FAIL):
                item = self.table.item(r, 1)
                key = item.data(Qt.UserRole)
                if key and key in self._row_of_key:
                    del self._row_of_key[key]
                self.table.removeRow(r)
        self._update_task_count()

    @Slot()
    def delete_selected_tasks(self):
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            QMessageBox.information(self, "提示", "请先选中要删除的任务行")
            return
        for r in rows:
            item = self.table.item(r, 1)
            key = item.data(Qt.UserRole)
            if key and key in self._row_of_key:
                del self._row_of_key[key]
            self.table.removeRow(r)
        self._update_task_count()

    # ---------------- 表格交互 ----------------
    def _on_table_menu(self, pos):
        r = self.table.rowAt(pos.y())
        if r < 0:
            return
        self.table.selectRow(r)
        menu = QMenu(self)
        act_open = menu.addAction("打开所在文件夹")
        act_del = menu.addAction("删除该任务")
        act = menu.exec(self.table.viewport().mapToGlobal(pos))
        if act == act_open:
            item = self.table.item(r, 1)
            mp4 = item.data(Qt.UserRole + 2) or ""
            mp3 = item.data(Qt.UserRole + 3) or ""
            path = mp4 or mp3
            if path and os.path.exists(path):
                os.startfile(os.path.dirname(os.path.abspath(path)))
            else:
                self.open_dir()
        elif act == act_del:
            item = self.table.item(r, 1)
            key = item.data(Qt.UserRole)
            if key and key in self._row_of_key:
                del self._row_of_key[key]
            self.table.removeRow(r)
            self._update_task_count()

    def _on_table_double_click(self, row, col):
        item = self.table.item(row, 1)
        if item is None:
            return
        mp4 = item.data(Qt.UserRole + 2) or ""
        mp3 = item.data(Qt.UserRole + 3) or ""
        path = mp4 or mp3
        if path and os.path.exists(path):
            os.startfile(os.path.dirname(os.path.abspath(path)))
        else:
            self.open_dir()


def main():
    import traceback as _tb
    td.setup_log_file()
    _log = td.get_logger()

    def _excepthook(exc_type, exc_value, exc_tb):
        """全局异常兜底：日志区展示、落盘，并弹友好提示，不裸奔崩溃。"""
        msg = "".join(_tb.format_exception(exc_type, exc_value, exc_tb))
        _log.error("未处理异常:\n%s", msg)
        app = QApplication.instance()
        if app is not None:
            for w in app.topLevelWidgets():
                if isinstance(w, MainWindow):
                    w.log_view.appendPlainText("【异常】\n" + msg)
            QMessageBox.critical(
                None, "出错了",
                f"程序遇到未处理的错误：\n{exc_type.__name__}: {exc_value}\n\n"
                "详情见日志区或日志文件。如果反复出现，请把日志反馈给开发者。")
        else:
            sys.stderr.write(msg)

    sys.excepthook = _excepthook
    app = QApplication(sys.argv)
    app.setApplicationName("糖豆广场舞下载器")
    app.setWindowIcon(app_icon())
    win = MainWindow()
    win.show()
    QTimer.singleShot(2500, win.start_update_check)  # 启动后延迟检查更新
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

