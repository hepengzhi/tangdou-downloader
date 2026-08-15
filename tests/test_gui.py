# -*- coding: utf-8 -*-
"""GUI 离屏测试（QT_QPA_PLATFORM=offscreen）。"""
import gc

import pytest

from PySide6.QtWidgets import QApplication

import tangdou_gui as g


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    yield a


def _teardown_window(app, w):
    """干净销毁窗口：显式 close + deleteLater + 处理事件 + gc。
    （qfluentwidgets 全局状态在多窗口循环退出时可能崩溃，需逐步释放）"""
    w._save_settings()
    w._wait_background_threads()
    w.close()
    w.deleteLater()
    app.processEvents()
    gc.collect()
    w.settings.clear()


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


def test_empty_hint_toggle(win):
    """空态引导随任务数显隐。"""
    app = QApplication.instance()
    app.processEvents()
    assert win._empty_hint.isVisible()
    win._add_row("20000002258422", "任务A")
    win._update_task_count()
    app.processEvents()
    assert not win._empty_hint.isVisible()
    # 删除该行（clear_done 只删完成/失败行）
    win.table.selectRow(0)
    win.delete_selected_tasks()
    app.processEvents()
    assert win.table.rowCount() == 0
    assert win._empty_hint.isVisible()


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
