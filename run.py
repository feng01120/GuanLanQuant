"""观澜 QuantDesk 启动入口。"""
from __future__ import annotations

import sys
import os
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen

from app.config import BUNDLE_DIR
from app.context import build_context
from app.ui.main_window import MainWindow
from app.ui.theme import ACCENT, BG, TEXT, apply_theme
from app.util import hard_exit, log


def _icon(size: int = 128) -> QIcon:
    ico = BUNDLE_DIR / "assets" / "guanlan.ico"
    if ico.exists():
        return QIcon(str(ico))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor("#1B2C47"))
    g.setColorAt(1, QColor("#0A1220"))
    p.setBrush(g)
    p.setPen(QColor(ACCENT))
    p.drawRoundedRect(2, 2, size - 4, size - 4, size * 0.18, size * 0.18)
    p.setPen(QColor(ACCENT))
    p.setFont(QFont("Microsoft YaHei UI", int(size * 0.42), QFont.Bold))
    p.drawText(pm.rect(), Qt.AlignCenter, "观")
    p.end()
    return QIcon(pm)


def _splash() -> QSplashScreen:
    pm = QPixmap(460, 240)
    pm.fill(QColor(BG))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QColor(ACCENT))
    p.setFont(QFont("Microsoft YaHei UI", 30, QFont.Bold))
    p.drawText(pm.rect().adjusted(0, 52, 0, 0), Qt.AlignHCenter, "观 澜")
    p.setPen(QColor(TEXT))
    p.setFont(QFont("Microsoft YaHei UI", 12))
    p.drawText(pm.rect().adjusted(0, 108, 0, 0), Qt.AlignHCenter, "QuantDesk · A股多维研判终端")
    p.setPen(QColor("#8CA0BE"))
    p.setFont(QFont("Microsoft YaHei UI", 9))
    p.drawText(pm.rect().adjusted(0, 140, 0, 0), Qt.AlignHCenter,
               "技术 / 资金 / 估值 / 情绪 / 宏观 / 人文")
    p.drawText(pm.rect().adjusted(0, 186, 0, 0), Qt.AlignHCenter,
               "正在装配数据源、因子与模型…")
    p.end()
    sp = QSplashScreen(pm)
    sp.setWindowFlag(Qt.WindowStaysOnTopHint)
    return sp


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("观澜 QuantDesk")
    app.setOrganizationName("GuanLan")
    app.setWindowIcon(_icon())
    apply_theme(app)

    def hook(exc_type, exc, tb):
        log.error("未捕获异常:\n" + "".join(traceback.format_exception(exc_type, exc, tb)))
        QMessageBox.critical(None, "观澜发生异常",
                             f"{exc_type.__name__}: {exc}\n\n详情见 logs/guanlan.log")
    sys.excepthook = hook

    splash = _splash()
    splash.show()
    app.processEvents()
    try:
        ctx = build_context()
    except Exception as e:  # noqa: BLE001
        log.exception("初始化失败")
        splash.close()
        QMessageBox.critical(None, "初始化失败", f"{e}\n\n请检查 logs/guanlan.log")
        hard_exit(1)

    win = MainWindow(ctx)
    win.setWindowIcon(_icon())
    win.show()
    splash.finish(win)
    app.aboutToQuit.connect(win.shutdown)
    secs = os.environ.get("GUANLAN_EXIT_AFTER")
    if secs:
        QTimer.singleShot(int(float(secs) * 1000), app.quit)
    rc = app.exec()
    # Qt 的 QThread 在进程退出阶段被 Python 析构时容易触发 0xc0000409；
    # 先停任务并刷新日志，再直接结束进程，绕开不安全的 Qt 析构顺序。
    try:
        win.shutdown()
        sys.stdout.flush()
        sys.stderr.flush()
    finally:
        hard_exit(int(rc))


if __name__ == "__main__":
    raise SystemExit(main())
