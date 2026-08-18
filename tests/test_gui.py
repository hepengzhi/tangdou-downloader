# -*- coding: utf-8 -*-
"""GUI 离屏测试（QT_QPA_PLATFORM=offscreen）。"""
import gc

import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListView

import tangdou_gui as g


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    yield a


def _teardown_window(app, w):
    """干净销毁窗口：显式 close + deleteLater + 处理事件 + gc。
    （qfluentwidgets 全局状态在多窗口循环退出时可能崩溃，需逐步释放）
    注意：不再调用 settings.clear() —— 那会清掉用户真实注册表里的配置
    （sqlite_db 等），导致每次跑测试后应用都要重新配置。"""
    w._save_settings()
    w._wait_background_threads()
    w.close()
    w.deleteLater()
    app.processEvents()
    gc.collect()


@pytest.fixture()
def win(app):
    w = g.MainWindow()
    w.show()
    yield w
    _teardown_window(app, w)


def test_window_constructs(win):
    assert win.windowTitle().startswith("糖豆广场舞下载器 v")
    assert g.VERSION in win.windowTitle()


def test_default_save_dir(win):
    assert win.edit_dir.text()  # 非空


def test_add_and_clear_tasks(win):
    win.edit_links.setPlainText("20000002258422\nbadlink\n20000013474038")
    win.add_links()
    # badlink 被跳过 → 2 行
    assert win.table.rowCount() == 2
    assert win.grp_tasks.title() == "任务列表（共 2 项）"
    win.table.selectRow(0)
    win.delete_selected_tasks()
    assert win.table.rowCount() == 1


def test_status_colors(win):
    win._add_row("20000002258422", "测试任务")
    r = win.table.rowCount() - 1
    win._set_row_status(r, g.STATUS_OK, "100%", 100)
    assert win.table.item(r, 0).text() == g.STATUS_OK
    assert win.table.item(r, 0).foreground().color().name() == "#27ae60"
    win._set_row_status(r, g.STATUS_FAIL, "失败", 0)
    assert win.table.item(r, 0).foreground().color().name() == "#eb5757"


def test_theme_toggle_and_persist(win):
    before = win._dark
    win.toggle_theme()
    assert win._dark is not before
    win._save_settings()
    assert win.settings.value("dark_mode") == ("1" if win._dark else "0")
    win.toggle_theme()  # 还原


def test_button_enable_flow(win):
    assert not win.btn_stop.isEnabled()
    win.btn_start.setEnabled(False)
    win.btn_stop.setEnabled(True)
    win._on_all_done()
    assert win.btn_start.isEnabled()
    assert not win.btn_stop.isEnabled()


def test_retry_failed(win):
    win._add_row("20000002258422", "任务A")
    r = win.table.rowCount() - 1
    win._set_row_status(r, g.STATUS_FAIL, "失败", 0)
    win.retry_failed()
    assert win.table.item(r, 0).text() == g.STATUS_WAIT


def test_tray_guarded_in_offscreen(app):
    """离屏环境无系统托盘支持，_tray 应为 None，closeEvent 走正常路径。"""
    w = g.MainWindow()
    assert w._tray is None or not g.QSystemTrayIcon.isSystemTrayAvailable()
    _teardown_window(app, w)


def test_stop_button_danger_color(win):
    win._apply_danger_style()
    assert "#eb5757" in win.btn_stop.styleSheet()


def test_check_update_anti_double_click(win):
    """连点检查更新时第二次被忽略（worker 运行中直接返回）。"""
    assert hasattr(win, "btn_check_update")
    win.check_update_now()
    assert not win.btn_check_update.isEnabled()  # 检查期间禁用
    win.btn_check_update.setEnabled(True)        # 恢复（结果回调会做同样的事）
    win.btn_check_update.setText("检查更新")


def test_version_key():
    assert g.version_key("v1.2.0") == (1, 2, 0)


def test_nav_startup_expanded_slim(win):
    """启动即展开为窄导航（不遮挡右侧内容区）。"""
    QApplication.instance().processEvents()  # 让 hBoxLayout 完成重排
    nav = win.navigationInterface
    assert nav.panel.displayMode.name == "EXPAND"
    assert 180 <= nav.panel.width() <= 480
    # 内容区不被导航遮挡：导航宽 + 内容宽 ≈ 窗口宽
    assert win.stackedWidget.width() + nav.width() <= win.width() + 5


def test_nav_drag_resize_persists(win):
    """拖动调宽后写入 QSettings，供下次启动恢复。"""
    nav = win.navigationInterface
    nav._set_nav_width(340)
    win.settings.sync()
    assert nav.panel.width() == 340
    assert nav.panel.expandWidth == 340
    nav._save_width()
    win.settings.sync()
    assert int(win.settings.value("nav_width")) == 340


def test_nav_pages_after_merge(win):
    """合并后导航只剩「歌名搜索 + 设置」两页。"""
    keys = set(win.navigationInterface.panel.items.keys())
    assert keys == {"songPage", "settingPage"}


def test_db_setting_persist(win):
    win.edit_db.setText(r"C:\tmp\videos.db")
    win._save_settings()
    win.settings.sync()
    assert win.settings.value("sqlite_db") == r"C:\tmp\videos.db"
    win.settings.remove("sqlite_db")   # 还原，避免污染真实配置
    win.settings.sync()


def test_search_db_result_marker(win):
    """数据库结果显示为网格条目且可下载。"""
    win._on_search_done([
        {"title": "最炫民族风", "vid": "2000001", "url": "", "source": "db"},
    ])
    assert win.list_results.count() == 1
    it = win.list_results.item(0)
    assert it.text() == "最炫民族风"
    assert it.data(Qt.UserRole) == "2000001"
    assert it.data(Qt.UserRole + 1) == g.K_VIDEO
    assert win.list_results.viewMode() == QListView.IconMode  # 封面网格布局


def test_search_worker_db_only(app, monkeypatch):
    """搜索只查本地数据库（不再走全网/糖豆/B站）。"""
    called = []

    def fake_find_vids(db, kw):
        called.append((db, kw))
        return [(1500669307167, "火火的姑娘")]

    monkeypatch.setattr(g.td, "find_vids", fake_find_vids)
    out = []
    w = g.SearchWorker("火火的姑娘", "C:/v.db")
    w.search_done.connect(lambda r: out.append(r))
    w.run()
    assert called == [("C:/v.db", "火火的姑娘")]
    assert out[0][0]["source"] == "db"
    assert out[0][0]["vid"] == "1500669307167"

    # 未配置路径 → 直接空结果
    out2 = []
    w2 = g.SearchWorker("火火的姑娘", "")
    w2.search_done.connect(lambda r: out2.append(r))
    w2.run()
    assert out2 == [[]]


def test_result_double_click_adds_task(win):
    """双击搜索结果自动加入任务列表。"""
    win._on_search_done([
        {"title": "火火的姑娘", "vid": "1500669307167", "url": "", "source": "db"},
    ])
    win._on_result_double_clicked(win.list_results.item(0))
    assert win.table.rowCount() == 1
    assert win.table.item(0, 1).text() == "火火的姑娘"


def test_search_uses_live_db_path(win, monkeypatch):
    """回归：设置里刚填的路径（未关窗保存）搜索时必须立即生效。"""
    captured = {}

    class FakeWorker:
        def __init__(self, kw, db_path, parent=None):
            captured["kw"] = kw
            captured["db_path"] = db_path
            self.search_done = type("S", (), {"connect": lambda self, f: None})()
            self.search_log = type("S", (), {"connect": lambda self, f: None})()

        def isRunning(self):
            return False

        def start(self):
            captured["started"] = True

    monkeypatch.setattr(g, "SearchWorker", FakeWorker)
    win.edit_db.setText(r"C:\tmp\videos.db")   # 只填输入框，不保存
    win.edit_song.setText("火火的姑娘")
    win.do_search()
    assert captured["db_path"] == r"C:\tmp\videos.db"
    assert captured["kw"] == "火火的姑娘"


def test_fmt_combo_persist(win):
    """下载格式选择持久化。"""
    win.combo_fmt.setCurrentIndex(1)   # 仅 MP3
    win._save_settings()
    win.settings.sync()
    assert win.settings.value("fmt") == "mp3"
    win.settings.remove("fmt")         # 还原
    win.settings.sync()


def test_fmt_migration_old_audio(win):
    """旧版 audio 开关迁移：audio=True→both，audio=False→mp4。"""
    win.settings.setValue("audio", False)
    win.settings.remove("fmt")
    win._load_settings()
    assert win.combo_fmt.currentData() == "mp4"
    win.settings.setValue("audio", True)
    win.settings.remove("fmt")
    win._load_settings()
    assert win.combo_fmt.currentData() == "both"
    win.settings.remove("audio")       # 还原
    win.settings.sync()


def test_task_panel_toggle(win):
    """任务区默认隐藏，点按钮后显示，加入任务自动展开。"""
    assert not win._task_panel.isVisible()
    win._toggle_task_panel(True)
    assert win._task_panel.isVisible()
    assert win.btn_toggle_tasks.text().startswith("🕶")
    win._toggle_task_panel(False)
    assert not win._task_panel.isVisible()
    # 加入任务自动展开
    win._add_row("20000002258422", "任务A")
    assert win._task_panel.isVisible()


def test_clear_all(win):
    win._add_row("20000002258422", "任务A")
    win._add_row("20000013474038", "任务B")
    win._set_row_status(0, g.STATUS_OK, "100%", 100)
    win.clear_all()
    assert win.table.rowCount() == 0
    assert win.grp_tasks.title() == "任务列表（共 0 项）"
