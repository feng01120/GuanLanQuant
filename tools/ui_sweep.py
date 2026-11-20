"""逐个页面真实渲染并抓图，捕获槽函数异常。"""
import os
import sys
import time
import traceback
from pathlib import Path

os.environ["GUANLAN_SKIP_WARMUP"] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "reports" / "ui-win" / "audit"
OUT.mkdir(parents=True, exist_ok=True)
ERRORS = OUT / "errors.log"

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.context import build_context
from app.ui.main_window import MainWindow, PAGE_ORDER
from app.ui.theme import apply_theme
from app.util import hard_exit


def hook(exc_type, exc, tb):
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    with open(ERRORS, "a", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text, flush=True)


sys.excepthook = hook
app = QApplication(sys.argv)
apply_theme(app)
ctx = build_context()
MainWindow._boot = lambda self: None
win = MainWindow(ctx)
win._engine.stop()
win._engine.wait(1000)
win.show()
for _ in range(10):
    app.processEvents()
    time.sleep(0.05)

start = time.time()
for key in PAGE_ORDER:
    t0 = time.time()
    win._go(key)
    # 给同步渲染和轻量缓存读取留时间，不等待完整网络刷新
    deadline = time.time() + 2.5
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    p = OUT / f"{key}.png"
    win.grab().save(str(p))
    print(f"{key}: {time.time()-t0:.1f}s -> {p.name} {p.stat().st_size if p.exists() else 0}", flush=True)
print("TOTAL", round(time.time() - start, 1), "errors", ERRORS.stat().st_size if ERRORS.exists() else 0, flush=True)
sys.stdout.flush()
hard_exit(0)
