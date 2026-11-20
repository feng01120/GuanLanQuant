"""真实启动抓图：不抑制 _boot，验证总览页在正常启动后能填充。"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "reports" / "ui-win" / "audit" / "dashboard-real.png"

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.context import build_context
from app.ui.main_window import MainWindow
from app.ui.theme import apply_theme

app = QApplication(sys.argv)
apply_theme(app)
ctx = build_context()
win = MainWindow(ctx)
win.show()


def capture():
    win.grab().save(str(OUT))
    print(f"CAPTURED {OUT}", flush=True)
    win.close()
    QTimer.singleShot(1000, app.quit)


QTimer.singleShot(18000, capture)
QTimer.singleShot(22000, app.quit)
app.exec()
try:
    win.shutdown()
finally:
    os._exit(0)
