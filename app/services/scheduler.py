"""每小时校准引擎：拉取行情 → 重算因子 → 重估模型/权重 → 落库 → 通知界面。"""
from __future__ import annotations

import threading
import time
from datetime import datetime

from PySide6.QtCore import QThread, Signal

from ..util import log, market_phase


class HourlyEngine(QThread):
    cycle_started = Signal(str)
    cycle_log = Signal(str)
    cycle_done = Signal(dict)
    cycle_failed = Signal(str)

    def __init__(self, market, settings, parent=None):
        super().__init__(parent)
        self.market = market
        self.settings = settings
        self._stop = threading.Event()
        self._manual = threading.Event()
        self.last_run: float = 0.0
        self.next_run: float = 0.0

    def request_cycle(self) -> None:
        self._manual.set()

    def stop(self) -> None:
        self._stop.set()
        self._manual.set()

    def run(self) -> None:
        interval = max(60, int(self.settings.get("hourly_interval_sec", 3600)))
        self.next_run = time.time() + interval
        while not self._stop.is_set():
            triggered = self._manual.wait(timeout=max(1.0, self.next_run - time.time()))
            if self._stop.is_set():
                break
            if triggered:
                self._manual.clear()
            self._run_once()
            interval = max(60, int(self.settings.get("hourly_interval_sec", 3600)))
            self.next_run = time.time() + interval

    def _run_once(self) -> None:
        phase = market_phase()[0]
        stamp = datetime.now().strftime("%H:%M:%S")
        self.cycle_started.emit(f"{stamp} · 开始校准（{phase}）")
        try:
            self.cycle_log.emit("刷新自选池行情与 K 线…")
            out = self.market.refresh_watchlist(force=True, persist=True)
            self.last_run = time.time()
            stats = out["stats"]
            msg = (f"{datetime.now().strftime('%H:%M:%S')} · 校准完成：{stats['n']} 只标的，"
                   f"耗时 {stats['elapsed']}s，平均六维分 {stats['avg_score']:+.1f}")
            self.cycle_log.emit(msg)
            self.cycle_done.emit({"stats": stats, "results": out["results"],
                                  "errors": out["errors"], "message": msg,
                                  "ts": self.last_run})
        except Exception as e:  # noqa: BLE001
            log.exception("每小时校准失败")
            self.cycle_log.emit(f"校准失败：{e}")
            self.cycle_failed.emit(str(e))
