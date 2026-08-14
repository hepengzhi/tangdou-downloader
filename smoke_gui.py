# -*- coding: utf-8 -*-
"""离屏冒烟测试：验证 GUI 全流程（加任务->下载->进度->完成->文件落盘）。"""
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
import tangdou_gui as g

app = QApplication([])
win = g.MainWindow()
win.show()
app.processEvents()

# 1) 链接页加任务
win.edit_links.setPlainText("https://www.tangdoucdn.com/h5/play?vid=20000013474038&utm_source=test")
win.add_links()
win.edit_links.setPlainText("badlink")
win.add_links()
print("rows after add:", win.table.rowCount())

# 2) 相关批量（仅 mp3）加 2 个任务
win.edit_base_vid.setText("20000013474038")
win.check_audio_only.setChecked(True)
win.spin_limit.setValue(2)
win.add_related()
print("rows after related:", win.table.rowCount())

# 3) 启动下载
win.start_download()

# 4) 轮询直到 worker 结束
deadline = time.time() + 300
while time.time() < deadline:
    app.processEvents()
    if win._worker is not None and not win._worker.isRunning():
        break
    time.sleep(0.5)
app.processEvents()

print("worker running:", win._worker.isRunning() if win._worker else None)
print("row statuses:", [win.table.item(r, 0).text() for r in range(win.table.rowCount())])
log = win.log_view.toPlainText()
print("--- log tail ---")
print(log[-1200:])
outdir = win.edit_dir.text()
files = [f for f in os.listdir(outdir) if not f.endswith(".part")]
print("--- files ---")
for f in files:
    print(f, round(os.path.getsize(os.path.join(outdir, f)) / 1048576, 1), "MB")
print("SMOKE_OK")
