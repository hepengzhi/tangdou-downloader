# -*- coding: utf-8 -*-
"""离屏测试 GUI 歌名搜索流程。"""
import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtWidgets import QApplication
import tangdou_gui as g

app = QApplication([])
win = g.MainWindow()
win.show()
app.processEvents()

# 触发搜索
win.edit_song.setText("最炫民族风")
win.do_search()
deadline = time.time() + 60
while time.time() < deadline:
    app.processEvents()
    if win._search_worker is not None and not win._search_worker.isRunning():
        break
    time.sleep(0.3)
app.processEvents()

print("search worker done:", win._search_worker is not None and not win._search_worker.isRunning())
print("result items:", win.list_results.count())
for i in range(win.list_results.count()):
    it = win.list_results.item(i)
    flags = "selectable" if (it.flags() & it.ItemIsSelectable) else "NOT-selectable"
    print(f"  [{flags}] {it.text()[:70]}")
print("status:", win.statusBar().currentMessage())
print("SEARCH_TEST_DONE")
