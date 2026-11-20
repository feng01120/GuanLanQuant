"""切页 + 启动荐股刷新 + 立即关窗的压力冒烟，验证关闭时不会因后台 QThread 崩溃。"""
import os
import sys
import time
from pathlib import Path

os.environ["GUANLAN_SKIP_WARMUP"] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.context import build_context
from app.ui.main_window import MainWindow
from app.util import hard_exit
from app.ui.theme import apply_theme

app = QApplication(sys.argv)
apply_theme(app)
ctx = build_context()
MainWindow._boot = lambda self: None
win = MainWindow(ctx)
win._engine.stop()
win._engine.wait(1000)
win.show()
for key in ("dashboard", "research", "recommend", "forecast", "macro", "portfolio",
            "report", "terminal", "events", "plugins", "settings"):
    win._go(key)
    for _ in range(8):
        app.processEvents()
        time.sleep(0.05)
win._go("recommend")
win.recommend.refresh()          # 故意留下正在跑的网络 worker
for _ in range(20):
    app.processEvents()
    time.sleep(0.05)
print("FLOW OK; closing with worker running", flush=True)
# 在真实事件循环里关窗，再安排兜底 quit；避免无事件循环的 Qt 平台卡住。
QTimer.singleShot(0, win.close)
QTimer.singleShot(300, app.quit)
app.exec()
print("CLOSE OK", flush=True)
hard_exit(0)
