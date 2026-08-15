#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
糖豆广场舞下载器 - 图形界面 (tangdou_gui.py)
============================================
基于 PySide6 (Qt) 的 GUI：
  - 链接/vid 批量下载（视频 + 音频）
  - 歌名搜索（自动搜糖豆站内链接，搜不到引导粘贴 App 分享链接）
  - 相关视频批量下载（同歌其他版本，可仅下舞曲 mp3）
  - 多任务并发下载、断点续传、失败重试
  - 设置持久化（QSettings）、深色模式、自动更新检查
后台线程下载，界面不卡顿；任务表 + 进度条 + 日志。

运行：python tangdou_gui.py
依赖：pip install PySide6  (音频提取还需 ffmpeg 或 pip install imageio-ffmpeg)
"""
import concurrent.futures
import json
import os
import sys
import threading
import webbrowser
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tdcore as td  # 核心逻辑包（api/download/search/log）

from PySide6.QtCore import Qt, QThread, QSettings, Signal, Slot
from PySide6.QtGui import QFont, QColor, QBrush, QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPlainTextEdit, QLineEdit, QPushButton, QLabel, QComboBox, QCheckBox,
    QSpinBox, QFileDialog, QTableWidget, QTableWidgetItem, QProgressBar,
    QListWidget, QAbstractItemView, QMessageBox, QGroupBox, QSplitter,
    QMenu, QHeaderView, QSystemTrayIcon,
)

VERSION = "1.2.0"
REPO = "hepengzhi/tangdou-downloader"


def app_icon():
    """应用图标：打包后从 _MEIPASS/assets 读取，源码运行从项目 assets 读取。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(base, "assets", "icon.ico")
    return QIcon(p) if os.path.exists(p) else QIcon()

STATUS_WAIT, STATUS_RUN, STATUS_OK, STATUS_FAIL = "等待", "下载中", "完成", "失败"
K_VIDEO, K_MP3 = "video", "mp3"

# 状态列配色
STATUS_COLORS = {
    STATUS_WAIT: QColor("#8a8f98"),
    STATUS_RUN: QColor("#2f80ed"),
    STATUS_OK: QColor("#27ae60"),
    STATUS_FAIL: QColor("#eb5757"),
}

STYLE_LIGHT = """
QMainWindow, QWidget { font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif; font-size: 10pt; }
QGroupBox {
    border: 1px solid #d9dee5; border-radius: 8px; margin-top: 10px;
    background: #fbfcfe; font-weight: bold;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #344054; }
QPushButton {
    background: #ffffff; border: 1px solid #c9d1db; border-radius: 6px;
    padding: 5px 14px; color: #1f2937;
}
QPushButton:hover { background: #f2f6fc; border-color: #2f80ed; color: #2f80ed; }
QPushButton:disabled { color: #b0b8c4; background: #f5f6f8; border-color: #e0e4ea; }
QPushButton#primary {
    background: #2f80ed; border: 1px solid #2f80ed; color: #ffffff; font-weight: bold;
}
QPushButton#primary:hover { background: #1f6fd9; border-color: #1f6fd9; color: #ffffff; }
QPushButton#primary:disabled { background: #a9c6f0; border-color: #a9c6f0; color: #ffffff; }
QPushButton#danger { color: #eb5757; }
QPushButton#danger:hover { border-color: #eb5757; background: #fdf1f1; }
QPushButton#flat { border: none; background: transparent; color: #4b5563; padding: 4px 8px; }
QPushButton#flat:hover { background: #eef2f7; color: #2f80ed; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QListWidget {
    border: 1px solid #d0d7e2; border-radius: 6px; padding: 4px 8px; background: #ffffff;
    selection-background-color: #2f80ed; color: #1f2937;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QListWidget:focus {
    border-color: #2f80ed;
}
QTableWidget {
    border: 1px solid #d0d7e2; border-radius: 6px; background: #ffffff;
    gridline-color: #eef1f5; color: #1f2937;
}
QTableWidget::item { padding: 4px; }
QHeaderView::section {
    background: #f2f5f9; border: none; border-bottom: 1px solid #d0d7e2;
    padding: 6px 8px; color: #344054; font-weight: bold;
}
QProgressBar {
    border: none; border-radius: 5px; background: #e9eef5; height: 12px; text-align: center;
    font-size: 8pt; color: #1f2937;
}
QProgressBar::chunk { border-radius: 5px; background: #2f80ed; }
QTabWidget::pane { border: 1px solid #d9dee5; border-radius: 8px; background: #ffffff; top: -1px; }
QTabBar::tab {
    background: #f2f5f9; border: 1px solid #d9dee5; padding: 7px 18px; margin-right: 2px;
    border-top-left-radius: 6px; border-top-right-radius: 6px; color: #4b5563;
}
QTabBar::tab:selected { background: #ffffff; color: #2f80ed; font-weight: bold; border-bottom-color: #ffffff; }
QTabBar::tab:hover { color: #2f80ed; }
QStatusBar { background: #f2f5f9; color: #4b5563; }
QPlainTextEdit#log { font-family: Consolas, monospace; font-size: 9pt; background: #ffffff; color: #1f2937; }
QLabel { color: #1f2937; }
QMenu { background: #ffffff; border: 1px solid #d9dee5; border-radius: 6px; color: #1f2937; }
QMenu::item:selected { background: #e8f1fd; color: #2f80ed; }
"""

STYLE_DARK = """
QMainWindow, QWidget { font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif; font-size: 10pt; }
QMainWindow, QDialog, QMessageBox { background: #1e2228; }
QGroupBox {
    border: 1px solid #333a44; border-radius: 8px; margin-top: 10px;
    background: #242a32; font-weight: bold;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #aeb7c3; }
QPushButton {
    background: #2a313b; border: 1px solid #3a434f; border-radius: 6px;
    padding: 5px 14px; color: #d5dbe3;
}
QPushButton:hover { background: #323c49; border-color: #5b9cf5; color: #5b9cf5; }
QPushButton:disabled { color: #5a636e; background: #262c34; border-color: #2f363f; }
QPushButton#primary {
    background: #2f80ed; border: 1px solid #2f80ed; color: #ffffff; font-weight: bold;
}
QPushButton#primary:hover { background: #4a93f0; border-color: #4a93f0; color: #ffffff; }
QPushButton#primary:disabled { background: #3a5a85; border-color: #3a5a85; color: #9db4d4; }
QPushButton#danger { color: #ef6a6a; }
QPushButton#danger:hover { border-color: #ef6a6a; background: #3a2a2e; }
QPushButton#flat { border: none; background: transparent; color: #aeb7c3; padding: 4px 8px; }
QPushButton#flat:hover { background: #2c333d; color: #5b9cf5; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QListWidget {
    border: 1px solid #3a434f; border-radius: 6px; padding: 4px 8px; background: #1b1f25;
    selection-background-color: #2f80ed; color: #d5dbe3;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QListWidget:focus {
    border-color: #5b9cf5;
}
QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button { background: #2a313b; }
QTableWidget {
    border: 1px solid #3a434f; border-radius: 6px; background: #1b1f25;
    gridline-color: #2b323b; color: #d5dbe3;
}
QTableWidget::item { padding: 4px; }
QHeaderView::section {
    background: #242a32; border: none; border-bottom: 1px solid #3a434f;
    padding: 6px 8px; color: #aeb7c3; font-weight: bold;
}
QProgressBar {
    border: none; border-radius: 5px; background: #2b323b; height: 12px; text-align: center;
    font-size: 8pt; color: #d5dbe3;
}
QProgressBar::chunk { border-radius: 5px; background: #5b9cf5; }
QTabWidget::pane { border: 1px solid #3a434f; border-radius: 8px; background: #1e2228; top: -1px; }
QTabBar::tab {
    background: #242a32; border: 1px solid #3a434f; padding: 7px 18px; margin-right: 2px;
    border-top-left-radius: 6px; border-top-right-radius: 6px; color: #8a93a0;
}
QTabBar::tab:selected { background: #1e2228; color: #5b9cf5; font-weight: bold; border-bottom-color: #1e2228; }
QTabBar::tab:hover { color: #5b9cf5; }
QStatusBar { background: #242a32; color: #aeb7c3; }
QPlainTextEdit#log { font-family: Consolas, monospace; font-size: 9pt; background: #16191e; color: #c9d1da; }
QLabel { color: #d5dbe3; }
QMenu { background: #242a32; border: 1px solid #3a434f; border-radius: 6px; color: #d5dbe3; }
QMenu::item:selected { background: #2f3a48; color: #5b9cf5; }
QToolTip { background: #242a32; color: #d5dbe3; border: 1px solid #3a434f; }
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


class SearchWorker(QThread):
    """歌名搜索线程。"""
    search_done = Signal(list)          # [{vid,title,url}]
    search_log = Signal(str)

    def __init__(self, keyword, parent=None):
        super().__init__(parent)
        self.keyword = keyword

    def run(self):
        try:
            results = td.sogou_search(self.keyword)
        except Exception as e:
            self.search_log.emit(f"搜索出错: {e}")
            results = []
        self.search_done.emit(results)


class UpdateChecker(QThread):
    """GitHub Release 自动更新检查。"""
    found = Signal(str, str, str)       # tag, download_url, body

    def __init__(self, repo, current, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.current = current

    def run(self):
        try:
            url = f"https://api.github.com/repos/{self.repo}/releases/latest"
            req = urllib.request.Request(url, headers={"User-Agent": "tangdou-downloader"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                j = json.loads(resp.read().decode("utf-8"))
            tag = j.get("tag_name") or ""
            if tag and version_key(tag) > version_key(self.current):
                assets = j.get("assets") or []
                dl = assets[0]["browser_download_url"] if assets else (j.get("html_url") or "")
                self.found.emit(tag, dl, (j.get("body") or "")[:500])
        except Exception:
            pass  # 网络失败/无新版：静默


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
        ok_count = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as ex:
            futures = [ex.submit(self._do_task, *t) for t in self.tasks]
            for f in concurrent.futures.as_completed(futures):
                try:
                    f.result()
                except Exception as e:
                    self.log.emit(f"    ! 线程异常: {e}")
        self.log.emit(f"全部结束：共 {len(self.tasks)} 个任务。")
        self.all_done.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"糖豆广场舞下载器 v{VERSION}")
        self.setWindowIcon(app_icon())
        self.resize(980, 760)
        self.setMinimumSize(760, 560)
        self._worker = None
        self._search_worker = None
        self._update_worker = None
        self._row_of_key = {}
        self._ok_count = 0
        self._tray = None
        self.settings = QSettings("TangdouDownloader", "TangdouDownloader")

        self._build_ui()
        self._load_settings()
        self._setup_tray()
        self._update_task_count()
        self.statusBar().showMessage("就绪")
        self._check_update()

    # ---------------- 系统托盘 ----------------
    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QSystemTrayIcon(app_icon(), self)
        self._tray.setToolTip(f"糖豆广场舞下载器 v{VERSION}")
        menu = QMenu(self)
        act_show = menu.addAction("显示主窗口")
        act_show.triggered.connect(self._show_window)
        menu.addSeparator()
        act_start = menu.addAction("开始下载")
        act_start.triggered.connect(self.start_download)
        act_stop = menu.addAction("停止")
        act_stop.triggered.connect(self.stop_download)
        menu.addSeparator()
        act_quit = menu.addAction("退出")
        act_quit.triggered.connect(self.quit_app)
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
        """退出前等待后台线程结束，避免 QThread 被销毁时仍在运行。"""
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

    # ---------------- UI ----------------
    def _build_ui(self):
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 8)
        root.setSpacing(8)

        # ---- 设置区 ----
        cfg_grp = QGroupBox("下载设置")
        cfg = QHBoxLayout(cfg_grp)
        cfg.setContentsMargins(12, 14, 12, 10)
        cfg.setSpacing(8)
        cfg.addWidget(QLabel("清晰度:"))
        self.combo_quality = QComboBox()
        self.combo_quality.addItem("自动（优先 720P）", "auto")
        self.combo_quality.addItem("720P", "h720p")
        self.combo_quality.addItem("540P", "h540p")
        self.combo_quality.addItem("全部清晰度", "all")
        cfg.addWidget(self.combo_quality)
        self.check_audio = QCheckBox("提取音频 (mp3)")
        self.check_audio.setChecked(True)
        cfg.addWidget(self.check_audio)
        cfg.addWidget(QLabel("并发:"))
        self.spin_workers = QSpinBox()
        self.spin_workers.setRange(1, 4)
        self.spin_workers.setValue(2)
        self.spin_workers.setToolTip("同时下载的任务数（糖豆 CDN 限流，建议 1-3）")
        cfg.addWidget(self.spin_workers)
        cfg.addSpacing(10)
        cfg.addWidget(QLabel("保存到:"))
        self.edit_dir = QLineEdit(td.default_download_dir())
        self.edit_dir.setMinimumWidth(240)
        cfg.addWidget(self.edit_dir, 1)
        btn_dir = QPushButton("浏览…")
        btn_dir.clicked.connect(self._pick_dir)
        cfg.addWidget(btn_dir)
        btn_open = QPushButton("打开目录")
        btn_open.setObjectName("primary")
        btn_open.clicked.connect(self.open_dir)
        cfg.addWidget(btn_open)
        self.btn_theme = QPushButton("🌙")
        self.btn_theme.setObjectName("flat")
        self.btn_theme.setToolTip("切换深色/浅色主题")
        self.btn_theme.setFixedWidth(36)
        self.btn_theme.clicked.connect(self.toggle_theme)
        cfg.addWidget(self.btn_theme)
        root.addWidget(cfg_grp)

        # ---- 页签 ----
        tabs = QTabWidget()
        tabs.addTab(self._tab_links(), "链接下载")
        tabs.addTab(self._tab_song(), "歌名搜索")
        tabs.addTab(self._tab_related(), "相关批量")
        root.addWidget(tabs)

        # ---- 任务列表 + 日志（可拖拽分隔）----
        splitter = QSplitter(Qt.Vertical)

        grp = QGroupBox()
        self.grp_tasks = grp
        v = QVBoxLayout(grp)
        v.setContentsMargins(10, 14, 10, 10)
        v.setSpacing(6)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["状态", "标题", "进度"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 76)
        self.table.setColumnWidth(2, 190)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_menu)
        self.table.cellDoubleClicked.connect(self._on_table_double_click)
        v.addWidget(self.table)

        row_btns = QHBoxLayout()
        row_btns.setSpacing(8)
        self.btn_start = QPushButton("▶ 开始下载")
        self.btn_start.setObjectName("primary")
        self.btn_start.clicked.connect(self.start_download)
        self.btn_stop = QPushButton("■ 停止")
        self.btn_stop.setObjectName("danger")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_download)
        btn_retry = QPushButton("重试失败")
        btn_retry.clicked.connect(self.retry_failed)
        btn_del = QPushButton("删除选中")
        btn_del.clicked.connect(self.delete_selected_tasks)
        btn_clear = QPushButton("清空完成项")
        btn_clear.clicked.connect(self.clear_done)
        for b in (self.btn_start, self.btn_stop, btn_retry, btn_del, btn_clear):
            row_btns.addWidget(b)
        row_btns.addStretch(1)
        v.addLayout(row_btns)
        splitter.addWidget(grp)

        grp2 = QGroupBox("日志")
        v2 = QVBoxLayout(grp2)
        v2.setContentsMargins(10, 14, 10, 8)
        v2.setSpacing(6)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("log")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        v2.addWidget(self.log_view)
        log_btns = QHBoxLayout()
        btn_clear_log = QPushButton("清空日志")
        btn_clear_log.clicked.connect(lambda: self.log_view.clear())
        log_btns.addStretch(1)
        log_btns.addWidget(btn_clear_log)
        v2.addLayout(log_btns)
        splitter.addWidget(grp2)

        splitter.setSizes([420, 260])
        root.addWidget(splitter, 1)

        self.setCentralWidget(central)

    def _tab_links(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        v.addWidget(QLabel("粘贴糖豆分享链接或 vid 编号（每行一个，可多行）："))
        self.edit_links = QPlainTextEdit()
        self.edit_links.setPlaceholderText(
            "https://www.tangdoucdn.com/h5/play?vid=20000002258422&...\n20000002258422\n\n"
            "提示：糖豆 App 中 视频 → 分享 → 复制链接")
        self.edit_links.setMinimumHeight(120)
        v.addWidget(self.edit_links, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        btn_clear = QPushButton("清空")
        btn_clear.clicked.connect(lambda: self.edit_links.clear())
        row.addWidget(btn_clear)
        btn_add = QPushButton("＋ 加入任务")
        btn_add.setObjectName("primary")
        btn_add.clicked.connect(self.add_links)
        row.addWidget(btn_add)
        v.addLayout(row)
        return w

    def _tab_song(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        row = QHBoxLayout()
        row.addWidget(QLabel("歌名:"))
        self.edit_song = QLineEdit()
        self.edit_song.setPlaceholderText("例如：最炫民族风")
        self.edit_song.returnPressed.connect(self.do_search)
        row.addWidget(self.edit_song, 1)
        self.btn_search = QPushButton("搜索")
        self.btn_search.setObjectName("primary")
        self.btn_search.setMinimumWidth(90)
        self.btn_search.clicked.connect(self.do_search)
        row.addWidget(self.btn_search)
        v.addLayout(row)

        v.addWidget(QLabel("搜索结果（🎬 糖豆站内 = 可自动下载；🔗 全网 = 参考链接）："))
        self.list_results = QListWidget()
        self.list_results.setSelectionMode(QAbstractItemView.ExtendedSelection)
        v.addWidget(self.list_results, 1)
        row2 = QHBoxLayout()
        row2.addStretch(1)
        btn_add = QPushButton("＋ 将选中结果加入任务")
        btn_add.setObjectName("primary")
        btn_add.clicked.connect(self.add_selected_results)
        row2.addWidget(btn_add)
        v.addLayout(row2)

        v.addSpacing(4)
        v.addWidget(QLabel("自动搜索无结果时：在糖豆 App 搜索歌名 → 点开视频 → 分享 → 复制链接，粘贴到下面："))
        self.edit_paste = QPlainTextEdit()
        self.edit_paste.setPlaceholderText("粘贴 App 分享链接，每行一个")
        self.edit_paste.setMaximumHeight(80)
        v.addWidget(self.edit_paste)
        row3 = QHBoxLayout()
        row3.addStretch(1)
        btn_paste = QPushButton("＋ 将粘贴的链接加入任务")
        btn_paste.setObjectName("primary")
        btn_paste.clicked.connect(self.add_pasted_links)
        row3.addWidget(btn_paste)
        v.addLayout(row3)
        return w

    def _tab_related(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        row = QHBoxLayout()
        row.addWidget(QLabel("基准视频 vid:"))
        self.edit_base_vid = QLineEdit()
        self.edit_base_vid.setPlaceholderText("20000002258422")
        row.addWidget(self.edit_base_vid, 1)
        self.check_audio_only = QCheckBox("仅下载舞曲 mp3")
        row.addWidget(self.check_audio_only)
        row.addWidget(QLabel("数量:"))
        self.spin_limit = QSpinBox()
        self.spin_limit.setRange(1, 20)
        self.spin_limit.setValue(20)
        row.addWidget(self.spin_limit)
        btn = QPushButton("＋ 加入任务")
        btn.setObjectName("primary")
        btn.clicked.connect(self.add_related)
        row.addWidget(btn)
        v.addLayout(row)
        hint = QLabel("说明：拉取该视频的 20 个相关推荐（通常是同一首歌的其他版本）逐个加入任务；\n"
                      "勾选「仅下载舞曲 mp3」则直接下载糖豆舞曲原音频，无需安装 ffmpeg。")
        hint.setStyleSheet("color: #6b7280;")
        v.addWidget(hint)
        v.addStretch(1)
        return w

    # ---------------- 设置持久化 ----------------
    def _load_settings(self):
        s = self.settings
        self.edit_dir.setText(s.value("save_dir", td.default_download_dir(), str))
        self.combo_quality.setCurrentIndex(int(s.value("quality_idx", 0)))
        self.check_audio.setChecked(s.value("audio", True, type=bool))
        self.spin_workers.setValue(int(s.value("workers", 2)))
        self._dark = s.value("dark_mode", "0") == "1"
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

    def closeEvent(self, event):
        self._save_settings()
        super().closeEvent(event)

    def toggle_theme(self):
        self._dark = not self._dark
        self._apply_theme()

    def _apply_theme(self):
        self.setStyleSheet(STYLE_DARK if self._dark else STYLE_LIGHT)
        self.btn_theme.setText("☀️" if self._dark else "🌙")

    # ---------------- 自动更新 ----------------
    def _check_update(self):
        self._update_worker = UpdateChecker(REPO, VERSION, self)
        self._update_worker.found.connect(self._on_update_found)
        self._update_worker.start()

    @Slot(str, str, str)
    def _on_update_found(self, tag, url, body):
        self.log(f"发现新版本 {tag}（当前 {VERSION}）")
        box = QMessageBox(self)
        box.setWindowTitle("发现新版本")
        box.setText(f"检测到新版本 <b>{tag}</b>（当前 {VERSION}）\n\n{body[:200]}")
        btn_dl = box.addButton("去下载", QMessageBox.AcceptRole)
        box.addButton("稍后再说", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is btn_dl and url:
            webbrowser.open(url)

    # ---------------- 工具方法 ----------------
    def log(self, text):
        self.log_view.appendPlainText(text)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())
        td.get_logger().info(text)

    def _update_task_count(self):
        n = self.table.rowCount()
        self.grp_tasks.setTitle(f"任务列表（共 {n} 项）")

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
        bar = QProgressBar()
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
        self.statusBar().showMessage(f"已加入 {added} 个任务" if added else "没有识别到有效链接/vid")

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
        tangdou_n = sum(1 for r in results if r.get("vid"))
        others_n = len(results) - tangdou_n
        if results:
            for r in results:
                item = QListWidgetItem()
                if r.get("vid"):
                    item.setText(f"🎬 糖豆 [{r['vid']}] {r['title']}")
                    item.setData(Qt.UserRole, r["vid"])
                else:
                    item.setText(f"🔗 全网: {r['title']}")
                    item.setData(Qt.UserRole, None)
                    item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
                    item.setToolTip(r.get("url") or "")
                self.list_results.addItem(item)
            msg = f"糖豆站内 {tangdou_n} 个（可下载）+ 全网参考 {others_n} 条"
            self.statusBar().showMessage(msg)
            self.log(f"搜索结果：糖豆 {tangdou_n} 条（自动下载），全网参考 {others_n} 条")
        else:
            self.statusBar().showMessage("全网未搜到该歌名的广场舞视频，请在糖豆 App 搜索后粘贴分享链接")
            self.log("未搜到结果。糖豆官网搜索已下线，请在糖豆 App 搜索歌名 → 分享 → 复制链接 → 粘贴到下方输入框。")

    @Slot()
    def add_selected_results(self):
        items = self.list_results.selectedItems()
        if not items:
            QMessageBox.information(self, "提示", "请先在搜索结果里选择要下载的糖豆视频（🎬 项）")
            return
        added = 0
        for it in items:
            vid = it.data(Qt.UserRole)
            if not vid:
                continue
            text = it.text()
            title = text.split("] ", 1)[-1] if "] " in text else vid
            self._add_row(vid, title, K_VIDEO)
            added += 1
        if added:
            self.statusBar().showMessage(f"已加入 {added} 个糖豆下载任务")
        else:
            QMessageBox.information(self, "提示", "请选择 🎬 糖豆 开头的项（全网参考链接不支持自动下载）")

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
        self.statusBar().showMessage(f"已加入 {added} 个相关任务")

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
        self.statusBar().showMessage(f"开始下载 {len(tasks)} 个任务（并发 {self.spin_workers.value()}）…")

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
        self.statusBar().showMessage(msg)
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
            self.statusBar().showMessage("停止中…")

    @Slot()
    def retry_failed(self):
        """把失败/等待/下载中（已停止）的任务重置为等待，重新可下载。"""
        changed = 0
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).text() in (STATUS_FAIL, STATUS_RUN, STATUS_WAIT):
                self._set_row_status(r, STATUS_WAIT, "等待", 0)
                changed += 1
        self.statusBar().showMessage(f"已重置 {changed} 个任务，可重新开始下载" if changed else "没有可重试的任务")

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
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
