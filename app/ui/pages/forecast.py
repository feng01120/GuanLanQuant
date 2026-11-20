"""预测中心：多周期概率、蒙特卡洛、样本外验证、校准与权重。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QProgressBar, QPushButton, QSplitter, QVBoxLayout, QWidget)

from ...util import pct
from ..theme import ACCENT, ACCENT2, BORDER, DOWN, MUTED, TEXT, UP
from ..widgets.base import Card
from ..widgets.charts import CalibrationChart, FanChart, LineChart
from ..widgets.table import make_table, prepare_rows, set_cell
from ..workers import FnWorker


class PredictionCard(QFrame):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 10)
        lay.setSpacing(1)
        self.label = QLabel(label)
        self.label.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        self.prob = QLabel("--")
        self.prob.setStyleSheet(f"color:{TEXT}; font-size:29px; font-weight:700;")
        self.exp = QLabel("期望 --")
        self.exp.setStyleSheet(f"color:{TEXT}; font-size:11px;")
        self.rng = QLabel("区间 --")
        self.rng.setStyleSheet(f"color:{MUTED}; font-size:9px;")
        lay.addWidget(self.label)
        lay.addWidget(self.prob)
        lay.addWidget(self.exp)
        lay.addWidget(self.rng)

    def set(self, prob, exp, low, high, suffix=""):
        pv = float(prob) * 100
        color = UP if pv >= 55 else DOWN if pv <= 45 else (UP if pv >= 50 else DOWN)
        self.prob.setText(f"{pv:.0f}%")
        self.prob.setStyleSheet(f"color:{color}; font-size:29px; font-weight:700;")
        self.exp.setText(f"期望 {exp:+.2f}%{suffix}")
        self.rng.setText(f"80%区间 {low:+.1f}% ~ {high:+.1f}%")


class ForecastPage(QWidget):
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
        outer.setContentsMargins(0, 3, 0, 0)
        outer.setSpacing(9)
        header = QHBoxLayout()
        title = QLabel("预测中心")
        title.setMinimumHeight(21)
        title.setStyleSheet(f"color:{TEXT}; font-size:14px; font-weight:600;")
        header.addWidget(title)
        self.watch = QComboBox()
        self.watch.setMinimumWidth(180)
        self.watch.currentIndexChanged.connect(self._combo)
        header.addWidget(self.watch)
        self.btn = QPushButton("重新校准")
        self.btn.setObjectName("Primary")
        self.btn.clicked.connect(lambda: self.load(self._symbol, force=True))
        header.addWidget(self.btn)
        header.addStretch(1)
        self.note = QLabel("短周期 T+1/T+2 · 长周期 5/10/20 交易日 · 每小时重估")
        self.note.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        header.addWidget(self.note)
        outer.addLayout(header)

        self.cards = {}
        row = QHBoxLayout()
        row.setSpacing(8)
        for key, label in (("1", "T+1 方向"), ("2", "T+2 方向"), ("5", "5 交易日"),
                           ("10", "10 交易日"), ("20", "20 交易日")):
            c = PredictionCard(label)
            self.cards[key] = c
            row.addWidget(c, 1)
        outer.addLayout(row)

        vsplit = QSplitter(Qt.Vertical)
        vsplit.setChildrenCollapsible(False)
        outer.addWidget(vsplit, 1)

        top = QWidget()
        tl = QHBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(9)
        fan_card = Card("价格分布 · 蒙特卡洛", "25 个交易日 · 5/25/50/75/95 分位")
        self.fan = FanChart()
        fan_card.add(self.fan, 1)
        tl.addWidget(fan_card, 1)

        right = QWidget()
        right.setFixedWidth(380)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(9)
        val_card = Card("样本外验证", "滚动窗口 · 后段评估")
        self.val_table = make_table(["周期", "方向命中", "IC", "样本"], [58, 76, 62, 52])
        val_card.add(self.val_table, 1)
        self.val_note = QLabel("")
        self.val_note.setWordWrap(True)
        self.val_note.setStyleSheet(f"color:{MUTED}; font-size:9px;")
        val_card.add(self.val_note)
        rl.addWidget(val_card, 3)
        weight_card = Card("集成权重", "每小时按近端表现重估")
        self.weight_bars = {}
        self.weight_labs = {}
        for key, label in (("ridge", "Ridge 回归"), ("logit", "Logistic 分类"), ("knn", "历史类比")):
            row2 = QHBoxLayout()
            lab = QLabel(label)
            lab.setStyleSheet(f"color:{MUTED}; font-size:10px;")
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setFixedHeight(12)
            bar.setTextVisible(False)
            val = QLabel("0%")
            val.setFixedWidth(34)
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            val.setStyleSheet(f"color:{MUTED}; font-size:10px;")
            self.weight_bars[key] = bar
            self.weight_labs[key] = val
            row2.addWidget(lab, 2)
            row2.addWidget(bar, 3)
            row2.addWidget(val)
            weight_card.add_layout(row2)
        rl.addWidget(weight_card, 2)
        tl.addWidget(right)
        vsplit.addWidget(top)

        bottom = QWidget()
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(9)
        eq_card = Card("T+1 策略净值（研究口径）", "概率 > 56% 持仓，含 0.06% 切换成本")
        self.equity = LineChart()
        eq_card.add(self.equity, 1)
        self.eq_note = QLabel("")
        self.eq_note.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        eq_card.add(self.eq_note)
        bl.addWidget(eq_card, 1)
        cal_card = Card("概率校准", "预测概率 vs 实际上涨频率")
        self.cal = CalibrationChart()
        cal_card.add(self.cal, 1)
        hint = QLabel("点越靠近对角线，概率越可信；点的大小表示分箱样本数。")
        hint.setStyleSheet(f"color:{MUTED}; font-size:9px;")
        cal_card.add(hint)
        bl.addWidget(cal_card, 1)
        vsplit.addWidget(bottom)
        vsplit.setSizes([420, 220])

    # ------------------------------------------------------------------
    def reload_combo(self):
        names = self.market.settings.watchlist_names
        self.watch.blockSignals(True)
        self.watch.clear()
        for s in self.market.settings.watchlist:
            self.watch.addItem(f"{names.get(s, s)}  {s}", s)
        self.watch.blockSignals(False)

    def _combo(self, idx):
        s = self.watch.itemData(idx)
        if s and s != self._symbol:
            self.load(s, force=True)

    def load(self, symbol: str | None, force: bool = True):
        if not symbol:
            return
        symbol = str(symbol)
        if self._worker is not None and self._worker.isRunning():
            self._pending = (symbol, force)
            self.note.setText(f"{symbol} 已排队，等待当前校准完成…")
            return
        self._start(symbol, force)

    def _start(self, symbol: str, force: bool):
        self._symbol = symbol
        self._pending = None
        cached = self.market._analysis_cache.get(symbol)
        if cached and not force:
            self.apply(cached[1])
            self._drain()
            return
        self.note.setText("正在计算…首次需拉取历史数据")
        self.btn.setEnabled(False)

        def task():
            return self.market.analyze(symbol, force=force, persist=True)

        w = FnWorker(task, f"forecast-{symbol}")
        w.done.connect(lambda r, ww=w: self._on_done(r, ww))
        w.failed.connect(lambda e, ww=w: self._on_fail(e, ww))
        w.start()
        self._worker = w

    def _on_done(self, r, w):
        if self._worker is w:
            self._worker = None
        self.btn.setEnabled(True)
        self.note.setText("短周期 T+1/T+2 · 长周期 5/10/20 交易日 · 每小时重估")
        self.apply(r)
        self._drain()

    def _on_fail(self, e, w):
        if self._worker is w:
            self._worker = None
        self.btn.setEnabled(True)
        self.note.setText(f"失败：{e}")
        self._drain()

    def _drain(self):
        if self._pending is not None:
            sym, force = self._pending
            self._pending = None
            self._start(sym, force)

    # ------------------------------------------------------------------
    def apply(self, r: dict):
        self._data = r
        self._symbol = r["symbol"]
        if self.watch.count() == 0:
            self.reload_combo()
        idx = self.watch.findData(r["symbol"])
        if idx >= 0:
            self.watch.blockSignals(True)
            self.watch.setCurrentIndex(idx)
            self.watch.blockSignals(False)
        for h in (1, 2):
            s = r["short"].get(h)
            if s:
                self.cards[str(h)].set(s["prob_up"], s["exp_ret"], s["low"], s["high"])
        for h in (5, 10, 20):
            l = r["long"]["horizons"].get(h)
            if l:
                self.cards[str(h)].set(l["prob_up"], l["median_ret"], l["low"], l["high"])
        self.fan.set_data(r["long"]["fan"], r["long"]["last_close"],
                          f"{r['name']}  ·  波动 {r['long']['vol_annual']:.1f}%  ·  "
                          f"漂移 {r['long']['drift_daily']:+.2f}%/日")

        # 验证表
        rows = []
        for h in (1, 2):
            x = r["short_validation"]["horizons"].get(h, {})
            rows.append((f"T+{h}", x.get("hit", 0.5), x.get("ic", 0), x.get("n", 0)))
        for h in (5, 10, 20):
            x = r["long"].get("validations", {}).get(h, r["long"]["validation"])
            rows.append((f"{h}日", x.get("hit", 0.5), x.get("ic", 0), x.get("n", 0)))
        prepare_rows(self.val_table, len(rows))
        for i, (label, hit, ic, n) in enumerate(rows):
            set_cell(self.val_table, i, 0, label, None, bold=True)
            set_cell(self.val_table, i, 1, f"{hit * 100:.1f}%",
                     UP if hit >= 0.55 else DOWN if hit < 0.5 else MUTED, align_right=True)
            set_cell(self.val_table, i, 2, f"{ic:+.3f}", MUTED, align_right=True)
            set_cell(self.val_table, i, 3, str(n), MUTED, align_right=True)
        self.val_note.setText(
            f"短周期后段样本外 {r['short'].get(1, {}).get('n_eval', 0)} 个；"
            f"长周期仅用趋势因子验证，不含实时情绪/宏观。命中率接近 50% 时应视为弱信号。")

        w = r["short_validation"]["horizons"].get(1, {}).get("weights", {})
        for k, bar in self.weight_bars.items():
            v = int(round(float(w.get(k, 0)) * 100))
            bar.setValue(v)
            self.weight_labs[k].setText(f"{v}%")

        equity = r["short_validation"]["horizons"].get(1, {}).get("equity", [])
        if equity:
            self.equity.set_series(equity, 1.0, ACCENT)
            ret = (equity[-1] - 1) * 100
            dd = r["short_validation"]["horizons"].get(1, {}).get("max_dd", 0) * 100
            trades = int(r["short_validation"]["horizons"].get(1, {}).get("n_trades", 0))
            note = f"区间收益 {ret:+.1f}% · 最大回撤 {dd:.1f}% · 样本 {len(equity)} 日"
            if trades == 0:
                note += " · 阈值 56% 下未触发交易，净值保持 1.0"
            else:
                note += f" · 切换 {trades} 次（含 0.06% 成本）"
            self.eq_note.setText(note)
        else:
            self.eq_note.setText("样本不足，未生成策略净值。")
        cal = r["short_validation"]["horizons"].get(1, {}).get("calibration", [])
        self.cal.set_data(cal)

    def update_analysis(self, r: dict):
        if r["symbol"] == self._symbol:
            self.apply(r)
