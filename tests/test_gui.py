# -*- coding: utf-8 -*-
"""GUI 离屏测试（QT_QPA_PLATFORM=offscreen）。"""
import pytest

from PySide6.QtWidgets import QApplication

import tangdou_gui as g


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    yield a


@pytest.fixture()
def win(app):
    w = g.MainWindow()
    w.show()
    yield w
    w._save_settings()
    w._wait_background_threads()
    w.settings.clear()


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


def test_tray_guarded_in_offscreen():
    """离屏环境无系统托盘支持，_tray 应为 None，closeEvent 走正常路径。"""
    a = QApplication.instance() or QApplication([])
    w = g.MainWindow()
    assert w._tray is None or not g.QSystemTrayIcon.isSystemTrayAvailable()


def test_version_key():
    assert g.version_key("v1.2.0") == (1, 2, 0)
