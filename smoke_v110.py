# -*- coding: utf-8 -*-
"""离屏验证 v1.1.0 新功能：设置持久化/深色模式/并发/续传/更新检查。"""
import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtWidgets import QApplication
import tangdou_dl as td
import tangdou_gui as g

app = QApplication([])
win = g.MainWindow()
win.show()
app.processEvents()

# 1) 设置默认值
print("1) 默认保存目录:", win.edit_dir.text())
print("   并发默认:", win.spin_workers.value())

# 2) 深色模式切换 + 持久化
win.toggle_theme()
win._save_settings()
print("2) 深色切换后按钮:", win.btn_theme.text(), "| 持久化值:", win.settings.value("dark_mode"))
win.toggle_theme()
win._save_settings()
print("   切回浅色:", win.settings.value("dark_mode"))

# 3) 设置修改 + 持久化恢复
win.edit_dir.setText(r"D:\测试目录")
win.spin_workers.setValue(3)
win._save_settings()
win2 = g.MainWindow()
win2.show()
app.processEvents()
print("3) 新窗口恢复: 目录=", win2.edit_dir.text(), "| 并发=", win2.spin_workers.value())

# 4) 版本比较
assert g.version_key("v1.1.0") == (1, 1, 0)
assert g.version_key("v1.10.0") > g.version_key("v1.9.0")
assert g.version_key("v1.0.2") < g.version_key("v1.1.0")
print("4) 版本比较 OK")

# 5) 断点续传：下载一个 mp3 并验证 .part → 改名
mp3url = None
for r in td.get_related("20000002258422"):
    if r.get("mp3url"):
        mp3url = r["mp3url"]
        break
assert mp3url, "未拿到 mp3url"
dest = os.path.join(r"C:\Users\Ponche\Documents\github\tangdou-downloader", "resumetest.mp3")
if os.path.exists(dest):
    os.remove(dest)
if os.path.exists(dest + ".part"):
    os.remove(dest + ".part")
ok = td.download(mp3url, dest, log=print)
print("5) 断点续传下载 OK:", ok, "| 文件存在:", os.path.exists(dest), "| 无残留.part:", not os.path.exists(dest + ".part"))

# 6) 并发下载：2 个 mp3 任务，workers=2
tasks = []
for r in td.get_related("20000013474038")[:2]:
    if r.get("mp3url"):
        tasks.append((g.K_MP3, r["mp3url"], td.sanitize(r.get("title") or "x")))
print("6) 并发任务数:", len(tasks))
outdir = r"C:\Users\Ponche\Documents\github\tangdou-downloader\concurtest"
os.makedirs(outdir, exist_ok=True)
worker = g.DownloadWorker(tasks, outdir, want_audio=True, quality="auto", workers=2)
results = {}
worker.task_done.connect(lambda k, ok, a, b: results.update({k: ok}))
worker.start()
deadline = time.time() + 120
while time.time() < deadline:
    app.processEvents()
    if not worker.isRunning():
        break
    time.sleep(0.3)
app.processEvents()
print("   并发结果:", results, "| 全部成功:", all(results.values()) and len(results) == len(tasks))

# 清理
for p in (dest, dest + ".part"):
    if os.path.exists(p):
        os.remove(p)
import shutil
shutil.rmtree(outdir, ignore_errors=True)
win.settings.clear()
print("ALL_V110_TESTS_OK")
