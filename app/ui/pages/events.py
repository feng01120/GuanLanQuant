"""公告事件页：公告、资讯与情绪标签，单独成页避免 K 线页拥挤。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QPushButton, QSplitter,
                               QVBoxLayout, QWidget)

from ...util import pct
from ..theme import ACCENT, DOWN, MUTED, TEXT, UP
from ..widgets.base import Badge
from ..widgets.table import make_table, prepare_rows, set_cell
from ..workers import FnWorker


class EventsPage(QWidget):
    """公告 / 资讯双栏。数据来自分析结果，不重复请求。"""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.market = ctx.market
        self._worker = None
        self._pending: tuple[str, bool] | None = None
        self._symbol = None
        self._data = None
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 2, 0, 0)
        outer.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(9)
        self.name = QLabel("公告事件")
        self.name.setStyleSheet(f"color:{TEXT}; font-size:20px; font-weight:700;")
        head.addWidget(self.name)
        self.code = QLabel("")
        self.code.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        head.addWidget(self.code)
        self.badge = Badge("等待标的", "neutral")
        head.addWidget(self.badge)
        head.addStretch(1)
        self.status = QLabel("从 K 线终端或个股研究页选择标的后自动同步")
        self.status.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        head.addWidget(self.status)
        self.btn = QPushButton("刷新")
        self.btn.setObjectName("Ghost")
        self.btn.clicked.connect(lambda: self.load(self._symbol, force=True))
        head.addWidget(self.btn)
        outer.addLayout(head)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        ll.setSpacing(6)
        t1 = QLabel("交易所公告")
        t1.setStyleSheet(f"color:{TEXT}; font-size:12px; font-weight:600;")
        ll.addWidget(t1)
        self.ann_table = make_table(["日期", "公告标题"], [104, 480])
        self.ann_table.setWordWrap(True)
        ah = self.ann_table.horizontalHeader()
        ah.setSectionResizeMode(0, QHeaderView.Fixed)
        ah.setSectionResizeMode(1, QHeaderView.Stretch)
        self.ann_table.setColumnWidth(0, 104)
        self.ann_table.cellDoubleClicked.connect(self._open_ann)
        ll.addWidget(self.ann_table, 1)
        self.ann_note = QLabel("来源：东方财富公告 / 巨潮资讯；双击标题打开原文。")
        self.ann_note.setStyleSheet(f"color:{MUTED}; font-size:9px;")
        ll.addWidget(self.ann_note)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        rl.setSpacing(6)
        t2 = QLabel("市场资讯与情绪")
        t2.setStyleSheet(f"color:{TEXT}; font-size:12px; font-weight:600;")
        rl.addWidget(t2)
        self.news_table = make_table(["时间", "资讯", "情绪"], [90, 420, 54])
        self.news_table.setWordWrap(True)
        nh = self.news_table.horizontalHeader()
        nh.setStretchLastSection(False)
        nh.setSectionResizeMode(0, QHeaderView.Fixed)
        nh.setSectionResizeMode(1, QHeaderView.Stretch)
        nh.setSectionResizeMode(2, QHeaderView.Fixed)
        self.news_table.setColumnWidth(0, 90)
        self.news_table.setColumnWidth(2, 54)
        rl.addWidget(self.news_table, 1)
        self.news_note = QLabel("全市场资讯，非个股专属；情绪为本地词典打分，仅作事件强弱的辅助参考。")
        self.news_note.setStyleSheet(f"color:{MUTED}; font-size:9px;")
        rl.addWidget(self.news_note)
        split.addWidget(right)
        split.setSizes([600, 640])
        outer.addWidget(split, 1)

    # ------------------------------------------------------------------
    def ensure_loaded(self):
        if self._data:
            return
        sym = getattr(self.ctx, "active_symbol", "") or (
            self.market.settings.watchlist[0] if self.market.settings.watchlist else ""
        )
        if sym:
            self.load(sym, force=False)

    def load(self, symbol: str | None, force: bool = False):
        if not symbol:
            self.status.setText("请先在 K 线终端选择标的")
            return
        symbol = str(symbol)
        if self._worker is not None and self._worker.isRunning():
            self._pending = (symbol, force)
            self.status.setText(f"{symbol} 已排队，等待当前公告加载完成…")
            return
        self._start(symbol, force)

    def _start(self, symbol: str, force: bool):
        self._symbol = symbol
        self._pending = None
        if not force:
            cached = self.market._analysis_cache.get(symbol)
            if cached:
                self.apply(cached[1])
                self._drain()
                return
        self.status.setText(f"正在加载 {symbol} 的公告与资讯…")
        self.btn.setEnabled(False)

        def task():
            return self.market.analyze(symbol, force=force, persist=False)

        w = FnWorker(task, f"events-{symbol}")
        w.done.connect(lambda r, ww=w: self._on_done(r, ww))
        w.failed.connect(lambda e, ww=w: self._on_failed(e, ww))
        w.start()
        self._worker = w

    def _on_done(self, r: dict, w):
        if self._worker is w:
            self._worker = None
        self.apply(r)
        self._drain()

    def _on_failed(self, err: str, w):
        if self._worker is w:
            self._worker = None
        self._failed(err)
        self._drain()

    def _drain(self):
        if self._pending is not None:
            sym, force = self._pending
            self._pending = None
            self._start(sym, force)

    def _failed(self, err: str):
        self.btn.setEnabled(True)
        self.status.setText(f"加载失败：{err}")

    def apply(self, r: dict):
        self.btn.setEnabled(True)
        self._data = r
        self._symbol = r["symbol"]
        self.name.setText(r["name"])
        self.code.setText(r["symbol"])
        self.badge.setText(r.get("industry", "") or "行业缺失")
        self.badge.set_tone("gold")
        anns = r.get("announcements", [])
        news = r.get("news", [])
        self.status.setText(f"{r['name']} · 公告 {len(anns)} 条 · 资讯 {len(news)} 条 · 更新 {r['updated']}")

        prepare_rows(self.ann_table, len(anns))
        for i, a in enumerate(anns):
            set_cell(self.ann_table, i, 0, a.time[:10], MUTED)
            set_cell(self.ann_table, i, 1, a.title)
            self.ann_table.item(i, 1).setData(Qt.UserRole, a.url)
            self.ann_table.setRowHeight(i, 36)

        prepare_rows(self.news_table, len(news))
        for i, n in enumerate(news):
            set_cell(self.news_table, i, 0, n.get("time", "")[5:16], MUTED)
            set_cell(self.news_table, i, 1, n.get("title", ""))
            score = float(n.get("score", 0))
            set_cell(self.news_table, i, 2, f"{score:+.0f}",
                     UP if score > 10 else DOWN if score < -10 else MUTED, align_right=True)
            self.news_table.item(i, 1).setToolTip(
                f"情绪 {score:+.0f}｜{', '.join(n.get('tags', []))}")
            self.news_table.setRowHeight(i, 36)

    def _open_ann(self, row: int, _col: int):
        item = self.ann_table.item(row, 1)
        if not item:
            return
        url = item.data(Qt.UserRole)
        if url:
            QDesktopServices.openUrl(QUrl(str(url)))
