"""真实启动后进入宏观页，等待数据落地再抓图，验证行业板块表完整显示。"""
import os
import sys
import time
from pathlib import Path

os.environ["GUANLAN_QUIET"] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "reports" / "ui-win" / "audit"
OUT.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication

from app.context import build_context
from app.ui.main_window import MainWindow
from app.ui.theme import apply_theme
from app.util import hard_exit

app = QApplication(sys.argv)
apply_theme(app)
ctx = build_context()
win = MainWindow(ctx)
win.show()
deadline = time.time() + 16
while time.time() < deadline:
    app.processEvents()
    time.sleep(0.05)
win._go("macro")
deadline = time.time() + 10
while time.time() < deadline:
    app.processEvents()
    time.sleep(0.05)
p = OUT / "macro-live.png"
win.grab().save(str(p))
print(f"MACRO_LIVE {p.stat().st_size} bytes", flush=True)
win.shutdown()
sys.stdout.flush()
hard_exit(0)
