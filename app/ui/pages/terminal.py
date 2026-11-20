"""专业终端：高密度 K 线工作区（折线/蜡烛 + 筹码 + 量能 + MACD）。"""
from __future__ import annotations

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QSplitter, QVBoxLayout, QWidget)

from ...features import technical
from ...features.chips import chip_distribution
from ...util import money, pct, price
from ..theme import ACCENT, BORDER, DOWN, MUTED, TEXT, UP
from ..widgets.base import Badge, Card, KeyValue
from ..widgets.charts import ChipChart, KlineWidget
from ..workers import FnWorker


WINDOWS = [("近 60 根", 60), ("近 120 根", 120), ("近 250 根", 250), ("全部", 0)]


def resample(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """把日 K 聚合为周/月 K；返回带技术指标的 DataFrame。"""
    if df is None or len(df) < 5 or period == "日线":
        return df
    d = df.copy()
    d["_dt"] = pd.to_datetime(d["date"], errors="coerce")
    d = d.dropna(subset=["_dt"])
    if period == "周线":
        d["_bucket"] = d["_dt"].dt.to_period("W")
    elif period == "月线":
        d["_bucket"] = d["_dt"].dt.to_period("M")
    else:
        return df
    rows = []
    for _, g in d.groupby("_bucket", sort=True):
        rows.append({
            "date": str(g["date"].iloc[-1])[:10],
            "open": float(g["open"].iloc[0]),
            "high": float(g["high"].max()),
            "low": float(g["low"].min()),
            "close": float(g["close"].iloc[-1]),
            "volume": float(g["volume"].sum()),
            "amount": float(g["amount"].sum()),
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return df
    out["pct"] = out["close"].pct_change().fillna(0) * 100
    out["turnover"] = 0.0
    return technical.enrich(out)


class TerminalPage(QWidget):
    analysis_ready = Signal(dict)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.market = ctx.market
        self.store = ctx.store
        self._worker = None
        self._search_worker = None
        self._pending: tuple[str, bool] | None = None
        self._pending_search: str | None = None
        self._symbol = None
        self._data = None
        self._daily = None
        self._period = "日线"
        self._build()

    # ------------------------------------------------------------------ UI
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 2, 0, 0)
        outer.setSpacing(8)

        # 报价条
        quote = QFrame()
        quote.setObjectName("Card")
        quote.setAttribute(Qt.WA_StyledBackground, True)
        ql = QVBoxLayout(quote)
        ql.setContentsMargins(15, 10, 15, 10)
        ql.setSpacing(5)

        row = QHBoxLayout()
        row.setSpacing(9)
        self.name = QLabel("--")
        self.name.setStyleSheet(f"color:{TEXT}; font-size:20px; font-weight:700;")
        row.addWidget(self.name)
        self.code = QLabel("")
        self.code.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        row.addWidget(self.code)
        self.industry = Badge("", "gold")
        row.addWidget(self.industry)
        row.addSpacing(6)
        self.price = QLabel("--")
        self.price.setStyleSheet(f"color:{TEXT}; font-size:22px; font-weight:700;")
        row.addWidget(self.price)
        self.chg = Badge("--", "neutral")
        row.addWidget(self.chg)
        row.addStretch(1)

        self.search = QLineEdit()
        self.search.setPlaceholderText("代码 / 名称")
        self.search.setFixedWidth(158)
        self.search.returnPressed.connect(self._do_search)
        row.addWidget(self.search)
        self.btn_search = QPushButton("搜索")
        self.btn_search.setObjectName("Ghost")
        self.btn_search.clicked.connect(self._do_search)
        row.addWidget(self.btn_search)

        self.watch = QComboBox()
        self.watch.setFixedWidth(184)
        self.watch.currentIndexChanged.connect(self._combo_changed)
        row.addWidget(self.watch)

        self.btn = QPushButton("重算")
        self.btn.setObjectName("Primary")
        self.btn.clicked.connect(lambda: self.load(self._symbol, force=True))
        row.addWidget(self.btn)
        ql.addLayout(row)

        metrics = QHBoxLayout()
        metrics.setSpacing(18)
        self.kv = {}
        for key in ("开盘", "最高", "最低", "成交额", "换手", "市值", "市盈率", "综合"):
            kv = KeyValue(key, "--")
            kv.setMinimumWidth(118)
            self.kv[key] = kv
            metrics.addWidget(kv)
        metrics.addStretch(1)
        self.status = QLabel("等待加载")
        self.status.setStyleSheet(f"color:{MUTED}; font-size:9px;")
        metrics.addWidget(self.status)
        ql.addLayout(metrics)
        outer.addWidget(quote)

        # 主区：K 线 + 筹码
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        chart_card = Card("价格与量能", "前复权 · 折线/蜡烛可切换")
        ctl = QHBoxLayout()
        ctl.setSpacing(4)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.b_line = QPushButton("折线")
        self.b_candle = QPushButton("蜡烛")
        for i, b in enumerate((self.b_line, self.b_candle)):
            b.setObjectName("Segment")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.mode_group.addButton(b, i)
            ctl.addWidget(b)
        self.b_line.setChecked(True)
        self.mode_group.idClicked.connect(self._mode_changed)
        chart_card.header.addLayout(ctl)

        self.period = QComboBox()
        self.period.addItems(["日线", "周线", "月线"])
        self.period.setFixedWidth(70)
        self.period.currentTextChanged.connect(self._period_changed)
        chart_card.header.addWidget(self.period)

        self.rng = QComboBox()
        for label, _ in WINDOWS:
            self.rng.addItem(label)
        self.rng.setCurrentIndex(1)
        self.rng.setFixedWidth(86)
        self.rng.currentIndexChanged.connect(self._range_changed)
        chart_card.header.addWidget(self.rng)

        self.kline = KlineWidget()
        chart_card.add(self.kline, 1)
        split.addWidget(chart_card)

        chip_card = Card("筹码分布", "日 K 成交量分箱估算")
        chip_card.setMinimumWidth(286)
        chip_card.setMaximumWidth(340)
        self.chip_chart = ChipChart()
        chip_card.add(self.chip_chart, 1)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(3)
        self.ck = {}
        for i, key in enumerate(("收盘获利", "平均成本", "90% 区间", "集中度")):
            kv = KeyValue(key, "--")
            self.ck[key] = kv
            grid.addWidget(kv, i // 2, i % 2)
        chip_card.add_layout(grid)
        note = QLabel("公开接口无逐笔筹码，本图用近 420 根日 K 的成交量按价格分箱、"
                      "半衰期 120 日加权估算；“主力筹码”不可还原。")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{MUTED}; font-size:9px; border-top:1px solid {BORDER}; padding-top:6px;")
        chip_card.add(note)
        split.addWidget(chip_card)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([1030, 310])
        outer.addWidget(split, 1)

        self.reload_watch_combo()

    # ------------------------------------------------------------------ 自选
    def reload_watch_combo(self):
        names = self.market.settings.watchlist_names
        self.watch.blockSignals(True)
        self.watch.clear()
        for s in self.market.settings.watchlist:
            self.watch.addItem(f"{names.get(s, s)}  {s}", s)
        self.watch.blockSignals(False)

    def _combo_changed(self, idx):
        s = self.watch.itemData(idx)
        if s and s != self._symbol:
            self.load(s, force=True)

    def _do_search(self):
        if self._search_worker is not None and self._search_worker.isRunning():
            return
        text = self.search.text().strip()
        if not text:
            return
        if text.isdigit() and len(text) == 6:
            self.load(text, force=True)
            return
        self.status.setText(f"搜索「{text}」…")

        def task():
            return self.market.search(text)

        w = FnWorker(task, "search")
        w.done.connect(self._search_done)
        w.failed.connect(lambda e: self.status.setText(f"搜索失败：{e}"))
        w.start()
        self._search_worker = w

    def _search_done(self, rows):
        if not rows:
            self.status.setText("未找到匹配标的")
            return
        first = rows[0]
        # 搜索接口同时返回 secid 和六位代码；优先用六位代码，避免把
        # 1.600519 这种内部 secid 写进自选/研报的 symbol 字段。
        sym = first.get("symbol") or first.get("secid")
        self.status.setText(f"匹配 {len(rows)} 个，已选 {first.get('name')}（{sym}）")
        self.load(sym, force=True)

    # ------------------------------------------------------------------ 数据
    def load(self, symbol: str | None, force: bool = True):
        if not symbol:
            return
        symbol = str(symbol)
        if self._worker is not None and self._worker.isRunning():
            self._pending = (symbol, force)
            self.status.setText(f"{symbol} 已排队，等待当前标的加载完成…")
            return
        self._start(symbol, force)

    def _start(self, symbol: str, force: bool):
        self._symbol = symbol
        self.ctx.active_symbol = symbol
        if not force:
            cached = self.market._analysis_cache.get(symbol)
            if cached:
                self.apply(cached[1])
                self._drain()
                return
        self.status.setText(f"正在拉取 {symbol} 的 K 线与筹码…")
        self.btn.setEnabled(False)
        self._pending = None

        def task():
            return self.market.analyze(symbol, force=force, persist=False)

        w = FnWorker(task, f"terminal-{symbol}")
        w.done.connect(lambda r, ww=w: self._on_loaded(r, ww))
        w.failed.connect(lambda e, ww=w: self._on_failed(e, ww))
        w.start()
        self._worker = w

    def _on_loaded(self, r: dict, w):
        if self._worker is w:
            self._worker = None
        self.btn.setEnabled(True)
        self.apply(r)
        self.analysis_ready.emit(r)
        self._drain()

    def _on_failed(self, err: str, w):
        if self._worker is w:
            self._worker = None
        self.btn.setEnabled(True)
        self.status.setText(f"加载失败：{err}")
        self._drain()

    def _drain(self):
        if self._pending is not None:
            sym, force = self._pending
            self._pending = None
            self._start(sym, force)

    def apply(self, r: dict):
        self._data = r
        self._symbol = r["symbol"]
        self.ctx.active_symbol = r["symbol"]
        self._daily = r.get("df")
        q = r.get("quote")
        close = float(getattr(q, "price", 0) or 0) if q else float(r["snapshot"].get("close", 0))
        change = float(getattr(q, "pct", 0) or 0) if q else 0.0

        self.name.setText(r["name"])
        self.code.setText(f"{r['symbol']} · {r.get('industry', '') or '行业缺失'}")
        self.industry.setText(r.get("industry", "") or "行业缺失")
        self.price.setText(price(close))
        color = UP if change > 0 else DOWN if change < 0 else TEXT
        self.price.setStyleSheet(f"color:{color}; font-size:22px; font-weight:700;")
        self.chg.setText(pct(change))
        self.chg.set_tone("up" if change > 0 else "down" if change < 0 else "neutral")

        self.kv["开盘"].set(price(getattr(q, "open", 0)) if q else "--")
        self.kv["最高"].set(price(getattr(q, "high", 0)) if q else "--")
        self.kv["最低"].set(price(getattr(q, "low", 0)) if q else "--")
        self.kv["成交额"].set(money(getattr(q, "amount", 0)) if q else "--")
        self.kv["换手"].set(f"{getattr(q, 'turnover', 0):.2f}%" if q else "--")
        self.kv["市值"].set(money(getattr(q, "market_cap", 0)) if q else "--")
        self.kv["市盈率"].set(f"{getattr(q, 'pe', 0):.1f}" if q else "--")
        total = r.get("fused", {}).get("total")
        self.kv["综合"].set(f"{total:+.1f}" if total is not None else "--",
                            UP if (total or 0) > 0 else DOWN if (total or 0) < 0 else TEXT)
        self.status.setText(f"{r['updated'][11:16]} 更新 · {r['market_phase']} · "
                            f"截至 {r['snapshot'].get('date', '')}")

        self._render_chart()
        self._render_chips(close)

    # ------------------------------------------------------------------ 图表
    def _mode_changed(self, idx: int):
        self.kline.set_mode("line" if idx == 0 else "candle")

    def _window(self) -> int:
        return WINDOWS[max(0, self.rng.currentIndex())][1]

    def _range_changed(self, _idx):
        self.kline.set_window(self._window())

    def _period_changed(self, text: str):
        self._period = text or "日线"
        self._render_chart()
        close = self._daily["close"].iloc[-1] if self._daily is not None and len(self._daily) else 0
        self._render_chips(float(close))

    def _render_chart(self):
        if self._daily is None or len(self._daily) < 5:
            return
        d = resample(self._daily, self._period)
        if d is None or len(d) < 5:
            d = self._daily
        self.kline.set_data(d)
        self.kline.set_mode("line" if self.b_line.isChecked() else "candle")
        self.kline.set_window(self._window())

    def _render_chips(self, close: float):
        if self._daily is None or len(self._daily) < 20:
            self.chip_chart.set_data(None)
            return
        chips = chip_distribution(self._daily, close, bins=40, lookback=420, half_life=120)
        self.chip_chart.set_data(chips)
        if not chips:
            for kv in self.ck.values():
                kv.set("--")
            return
        self.ck["收盘获利"].set(f"{chips['profit_ratio'] * 100:.1f}%", UP)
        self.ck["平均成本"].set(price(chips["avg_cost"]))
        self.ck["90% 区间"].set(f"{price(chips['p5'])} ~ {price(chips['p95'])}")
        self.ck["集中度"].set(f"{chips['concentration']:.1f}%")
