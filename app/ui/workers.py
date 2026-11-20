"""后台任务线程。"""
from __future__ import annotations

import time
import threading

from PySide6.QtCore import QThread, Signal

from ..util import log


class FnWorker(QThread):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, fn, name: str = "", parent=None):
        super().__init__(parent)
        self.fn = fn
        self.name = name

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as e:  # noqa: BLE001
            log.exception(f"后台任务失败 {self.name}")
            self.failed.emit(str(e))


class WarmupWorker(QThread):
    """启动时逐只预热自选池，边算边推送，避免界面长时间空白。"""

    one_done = Signal(dict)
    progress = Signal(str)
    finished_all = Signal(dict)
    failed = Signal(str)

    def __init__(self, market, parent=None):
        super().__init__(parent)
        self.market = market
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        t0 = time.time()
        symbols = self.market.settings.watchlist
        results, errors = [], []
        try:
            self.market.refresh_quotes(symbols)
            for i, s in enumerate(symbols, 1):
                if self._stop.is_set():
                    break
                self.progress.emit(f"预热 {i}/{len(symbols)}：{s}")
                try:
                    r = self.market.analyze(s, force=True, persist=True)
                    results.append(r)
                    self.one_done.emit(r)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{s}: {e}")
                    log.warning(f"预热失败 {s}: {e}")
            ev = self.market.evaluate_forecasts()
            elapsed = round(time.time() - t0, 1)
            stats = {"n": len(results), "errors": len(errors), "elapsed": elapsed,
                     "evaluated": ev,
                     "avg_score": round(sum(r["fused"]["total"] for r in results) / max(1, len(results)), 1)}
            self.market.store.add_cycle("ok" if not errors else "partial",
                                        f"启动预热完成 {len(results)} 只，{elapsed}s", stats)
            self.finished_all.emit({"stats": stats, "errors": errors, "results": results})
        except Exception as e:  # noqa: BLE001
            log.exception("预热任务失败")
            self.failed.emit(str(e))
