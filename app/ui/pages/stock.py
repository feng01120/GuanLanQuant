"""个股页：K线 + 六维雷达 + 预测卡 + 因子/公告/研判/验证。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSplitter, QTabWidget, QTextBrowser,
                               QVBoxLayout, QWidget)

from ...util import money, pct, price
from ..theme import ACCENT, BORDER, DOWN, MUTED, TEXT, UP
from ..widgets.base import Badge, Card, ScoreBar
from ..widgets.charts import KlineWidget, RadarChart
from ..widgets.table import make_table, prepare_rows, set_cell
from ..workers import FnWorker


class ForecastTile(QFrame):
    def __init__(self, horizon: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 8)
        lay.setSpacing(1)
        self.h = QLabel(horizon)
        self.h.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        self.p = QLabel("--")
        self.p.setStyleSheet(f"color:{TEXT}; font-size:17px; font-weight:700;")
        self.e = QLabel("期望 --")
        self.e.setStyleSheet(f"color:{MUTED}; font-size:8px;")
        self.r = QLabel("区间 --")
        self.r.setStyleSheet(f"color:{MUTED}; font-size:8px;")
        lay.addWidget(self.h)
        lay.addWidget(self.p)
        lay.addWidget(self.e)
        lay.addWidget(self.r)

    def set(self, prob, exp, low, high):
        pv = float(prob) * 100
        color = UP if pv >= 52 else DOWN if pv <= 48 else TEXT
        self.p.setText(f"{pv:.0f}%")
        self.p.setStyleSheet(f"color:{color}; font-size:17px; font-weight:700;")
        self.e.setText(f"期望 {exp:+.2f}%")
        self.r.setText(f"{low:+.1f}~{high:+.1f}%")


class StockPage(QWidget):
    analysis_ready = Signal(dict)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.market = ctx.market
        self.store = ctx.store
        self._worker = None
        self._symbol = None
        self._data = None
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 3, 0, 0)
        outer.setSpacing(9)

        # 头部
        header = QHBoxLayout()
        header.setSpacing(10)
        self.name = QLabel("--")
        self.name.setStyleSheet(f"color:{TEXT}; font-size:22px; font-weight:700;")
        self.name.setMinimumHeight(34)
        self.code = QLabel("")
        self.code.setStyleSheet(f"color:{MUTED}; font-size:12px;")
        self.industry = Badge("", "gold")
        self.price = QLabel("--")
        self.price.setStyleSheet(f"color:{TEXT}; font-size:24px; font-weight:700;")
        self.price.setMinimumHeight(34)
        self.chg = Badge("--", "neutral")
        header.addWidget(self.name)
        header.addWidget(self.code)
        header.addWidget(self.industry)
        header.addSpacing(12)
        header.addWidget(self.price)
        header.addWidget(self.chg)
        header.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("输入代码或名称，回车搜索…")
        self.search.setFixedWidth(190)
        self.search.returnPressed.connect(self._do_search)
        header.addWidget(self.search)
        self.watch = QComboBox()
        self.watch.setMinimumWidth(150)
        self.watch.currentIndexChanged.connect(self._combo_changed)
        header.addWidget(self.watch)
        self.btn = QPushButton("分析")
        self.btn.setObjectName("Primary")
        self.btn.clicked.connect(lambda: self.load(self._symbol, force=True))
        header.addWidget(self.btn)
        outer.addLayout(header)
        self.status = QLabel("等待数据")
        self.status.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        outer.addWidget(self.status)

        # 主区
        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        outer.addWidget(split, 1)

        top = QWidget()
        tl = QHBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(9)
        chart_card = Card("K 线 · 均线 · 量能 · MACD", "前复权日线")
        ranges = QHBoxLayout()
        ranges.addStretch(1)
        for label, days in (("60日", 60), ("120日", 120), ("250日", 250), ("全部", 0)):
            b = QPushButton(label)
            b.setObjectName("Ghost")
            b.setFixedHeight(24)
            b.clicked.connect(lambda _=False, d=days: self.kline.set_window(d))
            ranges.addWidget(b)
        chart_card.add_layout(ranges)
        self.kline = KlineWidget()
        chart_card.add(self.kline, 1)
        tl.addWidget(chart_card, 1)

        side = QWidget()
        side.setFixedWidth(330)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(9)
        radar_card = Card("六维雷达", "技术/资金/估值/情绪/宏观/人文")
        self.radar = RadarChart()
        radar_card.add(self.radar, 1)
        sl.addWidget(radar_card, 2)

        score_card = Card("维度评分", "")
        self.bars = {}
        for key, label in (("technical", "技术"), ("fund", "资金"), ("valuation", "估值"),
                           ("sentiment", "情绪"), ("macro", "宏观"), ("humanities", "人文")):
            bar = ScoreBar(label, 0)
            self.bars[key] = bar
            score_card.add(bar)
        sl.addWidget(score_card, 2)

        forecast_card = Card("预测面板", "概率与期望收益")
        grid = QGridLayout()
        grid.setSpacing(5)
        self.tiles = {}
        for i, (key, label) in enumerate((("1", "T+1"), ("2", "T+2"), ("5", "5日"),
                                          ("10", "10日"), ("20", "20日"))):
            t = ForecastTile(label)
            self.tiles[key] = t
            grid.addWidget(t, i // 3, i % 3)
        forecast_card.add_layout(grid)
        self.forecast_note = QLabel("模型输出为统计倾向，不是承诺。")
        self.forecast_note.setWordWrap(True)
        self.forecast_note.setStyleSheet(f"color:{MUTED}; font-size:9px;")
        forecast_card.add(self.forecast_note)
        sl.addWidget(forecast_card, 3)
        tl.addWidget(side)
        split.addWidget(top)

        tabs = QTabWidget()
        # 因子
        factor = QWidget()
        fl = QVBoxLayout(factor)
        fl.setContentsMargins(8, 8, 8, 8)
        self.factor_table = make_table(["维度", "得分", "权重", "贡献", "依据"], [66, 56, 54, 58, 600])
        self.factor_table.setWordWrap(True)
        fl.addWidget(self.factor_table, 1)
        self.factor_note = QLabel("")
        self.factor_note.setWordWrap(True)
        self.factor_note.setStyleSheet(f"color:{MUTED}; font-size:10px; border-top:1px solid {BORDER}; padding-top:6px;")
        fl.addWidget(self.factor_note)
        tabs.addTab(factor, "因子明细")

        # 公告与资讯
        info = QWidget()
        il = QHBoxLayout(info)
        il.setContentsMargins(8, 8, 8, 8)
        self.ann_table = make_table(["日期", "公告标题"], [78, 400])
        self.ann_table.cellDoubleClicked.connect(self._open_ann)
        il.addWidget(self.ann_table, 1)
        self.news_table = make_table(["时间", "资讯"], [70, 340])
        il.addWidget(self.news_table, 1)
        tabs.addTab(info, "公告与资讯")

        # 研判
        self.research = QTextBrowser()
        self.research.setOpenExternalLinks(True)
        tabs.addTab(self.research, "智能研判")

        # 验证
        valid = QWidget()
        vl = QVBoxLayout(valid)
        vl.setContentsMargins(8, 8, 8, 8)
        self.val_table = make_table(["周期", "方向命中", "IC", "MAE", "样本", "权重/说明"], [60, 80, 64, 70, 60, 420])
        vl.addWidget(self.val_table, 1)
        self.val_note = QLabel("")
        self.val_note.setWordWrap(True)
        self.val_note.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        vl.addWidget(self.val_note)
        tabs.addTab(valid, "模型验证")
        split.addWidget(tabs)
        split.setSizes([520, 270])

        self.reload_watch_combo()

    # ------------------------------------------------------------------
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
        sym = first.get("secid") or first.get("symbol")
        self.status.setText(f"匹配 {len(rows)} 个，已选择 {first.get('name')}（{sym}）")
        self.load(sym, force=True)

    # ------------------------------------------------------------------
    def load(self, symbol: str | None, force: bool = True):
        if not symbol:
            return
        symbol = str(symbol)
        self._symbol = symbol
        if not force:
            cached = self.market._analysis_cache.get(symbol)
            if cached:
                self.apply(cached[1])
                return
        self.status.setText(f"正在分析 {symbol}…（首次需拉取历史 K 线，约 5 秒）")
        self.btn.setEnabled(False)

        def task():
            return self.market.analyze(symbol, force=force, persist=False)

        w = FnWorker(task, f"analyze-{symbol}")
        w.done.connect(self._on_loaded)
        w.failed.connect(self._on_failed)
        w.start()
        self._worker = w

    def _on_loaded(self, r: dict):
        self.btn.setEnabled(True)
        self.apply(r)

    def _on_failed(self, err: str):
        self.btn.setEnabled(True)
        self.status.setText(f"分析失败：{err}")

    # ------------------------------------------------------------------
    def apply(self, r: dict):
        self._data = r
        self._symbol = r["symbol"]
        q = r.get("quote")
        self.name.setText(r["name"])
        self.code.setText(r["symbol"])
        self.industry.setText(r.get("industry", "") or "行业缺失")
        close = float(getattr(q, "price", 0) or r["snapshot"].get("close", 0)) if q else float(r["snapshot"].get("close", 0))
        self.price.setText(price(close))
        p = float(getattr(q, "pct", 0) or 0) if q else 0.0
        self.chg.setText(pct(p))
        self.chg.set_tone("up" if p > 0 else "down" if p < 0 else "neutral")
        self.price.setStyleSheet(f"color:{UP if p > 0 else DOWN if p < 0 else TEXT}; font-size:24px; font-weight:700;")
        self.status.setText(
            f"更新 {r['updated']} · 数据截至 {r['snapshot'].get('date', '')} · "
            f"{'⚠ 数据可能陈旧' if r.get('stale') else '数据新鲜'} · "
            f"综合 {r['fused']['total']:+.1f}（{r['fused']['verdict']}） · {r['market_phase']}")

        self.kline.set_data(r["df"])
        self.radar.set_data(r["fused"]["radar"])
        for d in r["fused"]["radar"]:
            if d["key"] in self.bars:
                self.bars[d["key"]].set_value(d["score"], d["label"])
        for x in (1, 2):
            if x in r["short"]:
                s = r["short"][x]
                self.tiles[str(x)].set(s["prob_up"], s["exp_ret"], s["low"], s["high"])
        for x in (5, 10, 20):
            l = r["long"]["horizons"].get(x)
            if l:
                self.tiles[str(x)].set(l["prob_up"], l["median_ret"], l["low"], l["high"])
        self.forecast_note.setText(
            f"20日区间来自蒙特卡洛 {r['long']['paths']} 条路径；短周期置信度 "
            f"T+1 {r['short'].get(1, {}).get('confidence', 0):.0f}/100。非投资建议。")

        # 因子表
        rows = []
        for d in r["fused"]["radar"]:
            dim = r["dimensions"].get(d["key"], {})
            rows.append((d["label"], d["score"], d["weight"], d["contribution"],
                         "；".join(dim.get("reasons", [])[:3])))
        prepare_rows(self.factor_table, len(rows))
        for i, (label, score, weight, contrib, reason) in enumerate(rows):
            set_cell(self.factor_table, i, 0, label, None, bold=True)
            set_cell(self.factor_table, i, 1, f"{score:+.1f}", UP if score > 0 else DOWN if score < 0 else MUTED,
                     align_right=True)
            set_cell(self.factor_table, i, 2, f"{weight * 100:.0f}%", MUTED, align_right=True)
            set_cell(self.factor_table, i, 3, f"{contrib:+.1f}", UP if contrib > 0 else DOWN if contrib < 0 else MUTED,
                     align_right=True)
            set_cell(self.factor_table, i, 4, reason)
            self.factor_table.setRowHeight(i, 38)
        snap = r["snapshot"]
        self.factor_note.setText(
            f"支撑 {price(snap.get('support', 0))} · 压力 {price(snap.get('resistance', 0))} · "
            f"RSI {snap.get('rsi', 50):.1f} · ATR {snap.get('atr_pct', 0) * 100:.1f}% · "
            f"52周分位 {snap.get('pos_52w', 0) * 100:.0f}% · 趋势分 {snap.get('trend_score', 0):+.0f}")

        # 公告
        anns = r.get("announcements", [])
        prepare_rows(self.ann_table, len(anns))
        for i, a in enumerate(anns):
            set_cell(self.ann_table, i, 0, a.time, MUTED)
            set_cell(self.ann_table, i, 1, a.title)
            self.ann_table.item(i, 1).setData(Qt.UserRole, a.url)
        # 资讯
        news = r.get("news", [])[:12]
        prepare_rows(self.news_table, len(news))
        for i, n in enumerate(news):
            set_cell(self.news_table, i, 0, n.get("time", "")[5:16], MUTED)
            set_cell(self.news_table, i, 1, n.get("title", ""))
            score = n.get("score", 0)
            self.news_table.item(i, 1).setForeground(
                QColor(UP if score > 10 else DOWN if score < -10 else TEXT))
            self.news_table.item(i, 1).setToolTip(f"情绪 {score:+.0f}｜{', '.join(n.get('tags', []))}")

        self.research.setHtml(r["html"])

        # 验证表
        v = r["short_validation"]["horizons"]
        rows = []
        for h in (1, 2):
            x = v.get(h, {})
            w = x.get("weights", {})
            rows.append((f"T+{h}", x.get("hit", 0.5), x.get("ic", 0), x.get("mae", 0), x.get("n", 0),
                         "Ridge {ridge:.2f} / Logit {logit:.2f} / 类比 {knn:.2f}".format(**w) if w else "样本不足"))
        for h in (5, 10, 20):
            x = r["long"].get("validations", {}).get(h, r["long"]["validation"])
            rows.append((f"{h}日", x.get("hit", 0.5), x.get("ic", 0), 0, x.get("n", 0),
                         "六维评分+蒙特卡洛；验证仅含趋势因子"))
        prepare_rows(self.val_table, len(rows))
        for i, (label, hit, ic, mae, n, note) in enumerate(rows):
            set_cell(self.val_table, i, 0, label, None, bold=True)
            set_cell(self.val_table, i, 1, f"{hit * 100:.1f}%",
                     UP if hit >= 0.55 else DOWN if hit < 0.5 else MUTED, align_right=True)
            set_cell(self.val_table, i, 2, f"{ic:+.3f}", MUTED, align_right=True)
            set_cell(self.val_table, i, 3, f"{mae * 100:.2f}%" if mae else "--", MUTED, align_right=True)
            set_cell(self.val_table, i, 4, str(n), MUTED, align_right=True)
            set_cell(self.val_table, i, 5, note)
        self.val_note.setText(
            "命中率为滚动样本外方向准确率；IC 为预测收益与实际收益的秩相关。"
            "短周期权重用前 70% 样本外确定、后 30% 评估；长周期历史验证不含实时情绪/宏观。"
            "样本量小或命中率接近 50% 时，应把输出视为弱信号。")

        # 同步下拉
        idx = self.watch.findData(r["symbol"])
        if idx >= 0:
            self.watch.blockSignals(True)
            self.watch.setCurrentIndex(idx)
            self.watch.blockSignals(False)
        self.analysis_ready.emit(r)

    def _open_ann(self, row, col):
        item = self.ann_table.item(row, 1)
        if item:
            url = item.data(Qt.UserRole)
            if url:
                QDesktopServices.openUrl(QUrl(str(url)))
