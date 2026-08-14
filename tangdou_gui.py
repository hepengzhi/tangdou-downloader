#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
糖豆广场舞下载器 - 图形界面 (tangdou_gui.py)
============================================
基于 PySide6 (Qt) 的 GUI：
  - 链接/vid 批量下载（视频 + 音频）
  - 歌名搜索（自动搜糖豆站内链接，搜不到引导粘贴 App 分享链接）
  - 相关视频批量下载（同歌其他版本，可仅下舞曲 mp3）
后台线程下载，界面不卡顿；任务表 + 进度条 + 日志。

运行：python tangdou_gui.py
依赖：pip install PySide6  (音频提取还需 ffmpeg 或 pip install imageio-ffmpeg)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tangdou_dl as td  # 复用命令行版的下载逻辑

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPlainTextEdit, QLineEdit, QPushButton, QLabel, QComboBox, QCheckBox,
    QSpinBox, QFileDialog, QTableWidget, QTableWidgetItem, QProgressBar,
    QListWidget, QAbstractItemView, QMessageBox, QGroupBox,
)

STATUS_WAIT, STATUS_RUN, STATUS_OK, STATUS_FAIL = "等待", "下载中", "完成", "失败"
K_VIDEO, K_MP3 = "video", "mp3"


class SearchWorker(QThread):
    """歌名搜索线程。"""
    search_done = Signal(list)          # [(vid, title)]
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


class DownloadWorker(QThread):
    """下载任务队列线程。tasks: [(kind, key, title)]，kind ∈ {video, mp3}。"""
    task_started = Signal(str, str)         # key, title
    task_progress = Signal(str, int, int)   # key, done, total
    task_done = Signal(str, bool, str, str)  # key, ok, mp4, mp3
    log = Signal(str)
    all_done = Signal()

    def __init__(self, tasks, outdir, want_audio, quality, parent=None):
        super().__init__(parent)
        self.tasks = tasks
        self.outdir = outdir
        self.want_audio = want_audio
        self.quality = quality

    def run(self):
        ok_count = 0
        for kind, key, title in self.tasks:
            if self.isInterruptionRequested():
                break
            self._cur_key = key
            self.task_started.emit(key, title)
            try:
                if kind == K_VIDEO:
                    ok, mp4, mp3 = td.download_video(
                        key, self.outdir,
                        want_audio=self.want_audio,
                        quality=self.quality,
                        log=self.log.emit,
                        progress=self._progress,
                    )
                else:
                    fname = td.sanitize(title.replace("🎵 ", ""))
                    dest = os.path.join(self.outdir, fname + ".mp3")
                    self.log.emit(f"    下载舞曲 mp3 -> {os.path.basename(dest)}")
                    ok = td.download(key, dest, log=self.log.emit, progress=self._progress)
                    mp4, mp3 = ("", dest) if ok else ("", "")
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.log.emit(f"    ! 任务异常: {e}")
                ok, mp4, mp3 = False, "", ""
            if ok:
                ok_count += 1
            self.task_done.emit(key, ok, mp4, mp3)
        self.log.emit(f"全部结束：成功 {ok_count} / {len(self.tasks)} 个任务。")
        self.all_done.emit()

    def _progress(self, done, total):
        if self.isInterruptionRequested():
            raise KeyboardInterrupt
        self.task_progress.emit(getattr(self, "_cur_key", ""), done, total)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("糖豆广场舞下载器")
        self.resize(920, 700)
        self._current_key = None   # 正在下载的任务 key（供进度回调关联）
        self._worker = None
        self._search_worker = None
        self._row_of_key = {}

        self._build_ui()
        self.statusBar().showMessage("就绪")

    # ---------------- UI ----------------
    def _build_ui(self):
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)

        cfg = QHBoxLayout()
        cfg.addWidget(QLabel("清晰度:"))
        self.combo_quality = QComboBox()
        self.combo_quality.addItem("自动(优先720P)", "auto")
        self.combo_quality.addItem("720P", "h720p")
        self.combo_quality.addItem("540P", "h540p")
        self.combo_quality.addItem("全部清晰度", "all")
        cfg.addWidget(self.combo_quality)
        self.check_audio = QCheckBox("提取音频(mp3)")
        self.check_audio.setChecked(True)
        cfg.addWidget(self.check_audio)
        cfg.addSpacing(12)
        cfg.addWidget(QLabel("保存到:"))
        self.edit_dir = QLineEdit(os.path.abspath("Download"))
        cfg.addWidget(self.edit_dir, 1)
        btn_dir = QPushButton("浏览…")
        btn_dir.clicked.connect(self._pick_dir)
        cfg.addWidget(btn_dir)
        root.addLayout(cfg)

        tabs = QTabWidget()
        tabs.addTab(self._tab_links(), "链接下载")
        tabs.addTab(self._tab_song(), "歌名搜索")
        tabs.addTab(self._tab_related(), "相关批量")
        root.addWidget(tabs)

        grp = QGroupBox("任务列表")
        v = QVBoxLayout(grp)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["状态", "标题", "进度"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 70)
        self.table.setColumnWidth(2, 200)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        v.addWidget(self.table)
        row_btns = QHBoxLayout()
        btn_start = QPushButton("▶ 开始下载")
        btn_start.clicked.connect(self.start_download)
        btn_stop = QPushButton("■ 停止")
        btn_stop.clicked.connect(self.stop_download)
        btn_open = QPushButton("打开保存目录")
        btn_open.clicked.connect(self.open_dir)
        btn_clear = QPushButton("清空完成项")
        btn_clear.clicked.connect(self.clear_done)
        for b in (btn_start, btn_stop, btn_open, btn_clear):
            row_btns.addWidget(b)
        row_btns.addStretch(1)
        v.addLayout(row_btns)
        root.addWidget(grp, 2)

        grp2 = QGroupBox("日志")
        v2 = QVBoxLayout(grp2)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setFont(QFont("Consolas", 9))
        v2.addWidget(self.log_view)
        root.addWidget(grp2, 1)

        self.setCentralWidget(central)

    def _tab_links(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("粘贴糖豆分享链接或 vid 编号（每行一个，可多行）："))
        self.edit_links = QPlainTextEdit()
        self.edit_links.setPlaceholderText(
            "https://www.tangdoucdn.com/h5/play?vid=20000002258422&...\n20000002258422")
        v.addWidget(self.edit_links)
        b = QPushButton("＋ 加入任务")
        b.clicked.connect(self.add_links)
        v.addWidget(b, 0, Qt.AlignRight)
        return w

    def _tab_song(self):
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(QLabel("歌名:"))
        self.edit_song = QLineEdit()
        self.edit_song.setPlaceholderText("例如：最炫民族风")
        self.edit_song.returnPressed.connect(self.do_search)
        row.addWidget(self.edit_song, 1)
        self.btn_search = QPushButton("搜索")
        self.btn_search.clicked.connect(self.do_search)
        row.addWidget(self.btn_search)
        v.addLayout(row)

        v.addWidget(QLabel("搜索结果（🎬 糖豆站内 = 可自动下载；🔗 全网 = 参考链接）："))
        self.list_results = QListWidget()
        self.list_results.setSelectionMode(QAbstractItemView.ExtendedSelection)
        v.addWidget(self.list_results, 1)
        b1 = QPushButton("＋ 将选中结果加入任务")
        b1.clicked.connect(self.add_selected_results)
        v.addWidget(b1, 0, Qt.AlignRight)

        v.addSpacing(8)
        v.addWidget(QLabel("若自动搜索无结果（糖豆网页搜索已下线）：在糖豆 App 里搜索歌名 → "
                          "点开视频 → 分享 → 复制链接，粘贴到下面："))
        self.edit_paste = QPlainTextEdit()
        self.edit_paste.setPlaceholderText("粘贴 App 分享链接，每行一个")
        self.edit_paste.setMaximumHeight(90)
        v.addWidget(self.edit_paste)
        b2 = QPushButton("＋ 将粘贴的链接加入任务")
        b2.clicked.connect(self.add_pasted_links)
        v.addWidget(b2, 0, Qt.AlignRight)
        return w

    def _tab_related(self):
        w = QWidget()
        v = QVBoxLayout(w)
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
        b = QPushButton("＋ 加入任务")
        b.clicked.connect(self.add_related)
        row.addWidget(b)
        v.addLayout(row)
        v.addWidget(QLabel("说明：拉取该视频的 20 个相关推荐（通常是同一首歌的其他版本），"
                          "逐个解析加入任务；勾选“仅下载舞曲 mp3”则直接下载糖豆舞曲音频。"))
        v.addStretch(1)
        return w

    # ---------------- 工具方法 ----------------
    def log(self, text):
        self.log_view.appendPlainText(text)

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
        item_title = QTableWidgetItem(title or key)
        item_title.setData(Qt.UserRole, key)      # 任务 key（vid 或 mp3url）
        item_title.setData(Qt.UserRole + 1, kind)  # 任务类型
        self.table.setItem(r, 0, item_status)
        self.table.setItem(r, 1, item_title)
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setFormat("等待")
        self.table.setCellWidget(r, 2, bar)
        self._row_of_key[key] = r
        return r

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

    @Slot()
    def add_pasted_links(self):
        self._enqueue_links(self.edit_paste.toPlainText())

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
        self._worker = DownloadWorker(
            tasks, outdir,
            want_audio=self.check_audio.isChecked(),
            quality=self.combo_quality.currentData(),
            parent=self,
        )
        self._worker.task_started.connect(self._on_task_started)
        self._worker.task_progress.connect(self._on_task_progress)
        self._worker.task_done.connect(self._on_task_done)
        self._worker.log.connect(self.log)
        self._worker.all_done.connect(self._on_all_done)
        self._worker.start()
        self.statusBar().showMessage("开始下载…")

    @Slot(str, str)
    def _on_task_started(self, key, title):
        self._current_key = key
        r = self._row_of_key.get(key)
        if r is not None:
            self.table.item(r, 0).setText(STATUS_RUN)
            bar = self.table.cellWidget(r, 2)
            bar.setValue(0)
            bar.setFormat("准备中…")

    @Slot(str, int, int)
    def _on_task_progress(self, key, done, total):
        r = self._row_of_key.get(self._current_key)
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
            self.table.item(r, 0).setText(STATUS_OK if ok else STATUS_FAIL)
            bar = self.table.cellWidget(r, 2)
            bar.setValue(100 if ok else 0)
            bar.setFormat("100%" if ok else "失败")

    @Slot()
    def _on_all_done(self):
        self.statusBar().showMessage("全部任务结束")
        self._current_key = None

    @Slot()
    def stop_download(self):
        if self._worker and self._worker.isRunning():
            self._worker.requestInterruption()
            self.log("正在停止（当前文件下完即停）…")
            self.statusBar().showMessage("停止中…")

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


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("糖豆广场舞下载器")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
