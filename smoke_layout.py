# -*- coding: utf-8 -*-
"""离屏验证新版 GUI 布局与交互。"""
import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtWidgets import QApplication
import tangdou_gui as g

app = QApplication([])
win = g.MainWindow()
win.show()
app.processEvents()

# 1) 设置区默认值
print("默认保存目录:", win.edit_dir.text())
print("清晰度项:", [win.combo_quality.itemText(i) for i in range(win.combo_quality.count())])
print("停止按钮初始禁用:", not win.btn_stop.isEnabled())

# 2) 加任务
win.edit_links.setPlainText("20000002258422\nbadlink\n20000013474038")
win.add_links()
print("任务行数:", win.table.rowCount())
print("组标题:", win.grp_tasks.title())
st = win.table.item(0, 0)
print("状态项:", st.text(), "颜色:", st.foreground().color().name())

# 3) 模拟完成状态
win._set_row_status(0, g.STATUS_OK, "100%", 100)
print("模拟完成后状态:", win.table.item(0, 0).text(), "颜色:", win.table.item(0, 0).foreground().color().name())

# 4) 开始/停止按钮联动（不真正下载：直接模拟 all_done）
win.btn_start.setEnabled(False)
win.btn_stop.setEnabled(True)
win._on_all_done()
print("all_done 后 start 启用:", win.btn_start.isEnabled(), "| stop 禁用:", not win.btn_stop.isEnabled())

# 5) 清空完成项
win.clear_done()
print("清空完成后行数:", win.table.rowCount(), "| 组标题:", win.grp_tasks.title())

# 6) 删除选中
win.edit_paste.setPlainText("20000002258422")
win.add_pasted_links()
win.table.selectRow(0)
win.delete_selected_tasks()
print("删除选中后行数:", win.table.rowCount())

print("LAYOUT_TEST_OK")
