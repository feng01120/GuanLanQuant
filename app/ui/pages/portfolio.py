"""组合：持仓、风险预算、再平衡建议与 DRY-RUN 委托。"""
from __future__ import annotations

import json
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QVBoxLayout,
                               QWidget)

from ...util import money, pct, price
from ..theme import ACCENT, BORDER, DOWN, MUTED, TEXT, UP
from ..widgets.base import Card, MetricCard
from ..widgets.charts import LineChart
from ..widgets.table import make_table, prepare_rows, set_cell
from ..workers import FnWorker


class PortfolioPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.market = ctx.market
        self.svc = ctx.portfolio
        self._worker = None
        self._pos = []
        self._rows = []
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 3, 0, 0)
        outer.setSpacing(9)
        head = QHBoxLayout()
        t = QLabel("模拟组合")
        t.setMinimumHeight(21)
        t.setStyleSheet(f"color:{TEXT}; font-size:14px; font-weight:600;")
        head.addWidget(t)
        self.updated = QLabel("纯本地模拟 · 不接实盘")
        self.updated.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        head.addWidget(self.updated)
        head.addStretch(1)
        refresh = QPushButton("刷新持仓")
        refresh.clicked.connect(lambda: self.refresh(True))
        head.addWidget(refresh)
        outer.addLayout(head)

        self.cards = {}
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, (key, label) in enumerate((("mv", "总市值"), ("pnl", "浮动盈亏"), ("day", "当日盈亏"),
                                          ("vol", "年化波动"), ("var", "VaR 95%（1日）"),
                                          ("dd", "最大回撤"), ("conc", "集中度"), ("sharpe", "Sharpe（近90日）"))):
            c = MetricCard(label)
            self.cards[key] = c
            grid.addWidget(c, i // 4, i % 4)
        outer.addLayout(grid)

        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        outer.addWidget(split, 1)
        top = QWidget()
        tl = QHBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(9)
        pos_card = Card("持仓明细", "成本价由手工录入，现价来自实时报价")
        self.table = make_table(["名称", "代码", "数量", "成本", "现价", "市值",
                                 "浮盈", "盈亏%", "日盈亏", "权重"],
                                [92, 68, 62, 66, 66, 88, 82, 62, 76, 54])
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._select)
        pos_card.add(self.table, 1)
        bar = QHBoxLayout()
        self.symbol = QLineEdit()
        self.symbol.setPlaceholderText("代码，如 600519")
        self.qty = QSpinBox()
        self.qty.setRange(1, 10_000_000)
        self.qty.setValue(100)
        self.qty.setPrefix("数量 ")
        self.cost = QDoubleSpinBox()
        self.cost.setRange(0.01, 1_000_000)
        self.cost.setDecimals(2)
        self.cost.setValue(100.0)
        self.cost.setPrefix("成本 ")
        add = QPushButton("添加持仓")
        add.clicked.connect(self._add)
        dele = QPushButton("删除选中")
        dele.clicked.connect(self._delete)
        bar.addWidget(self.symbol)
        bar.addWidget(self.qty)
        bar.addWidget(self.cost)
        bar.addWidget(add)
        bar.addWidget(dele)
        bar.addStretch(1)
        pos_card.add_layout(bar)
        self.risk = QLabel("")
        self.risk.setWordWrap(True)
        self.risk.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        pos_card.add(self.risk)
        tl.addWidget(pos_card, 1)

        side = QWidget()
        side.setFixedWidth(390)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(9)
        curve_card = Card("组合净值（近90日，等权历史模拟）")
        self.curve = LineChart()
        curve_card.add(self.curve, 1)
        sl.addWidget(curve_card, 2)
        reb_card = Card("再平衡建议", "按六维评分倾斜，100 股整手")
        self.reb = make_table(["标的", "当前%", "目标%", "差额", "股数", "动作"],
                              [86, 56, 56, 66, 56, 46])
        self.reb.horizontalHeader().setStretchLastSection(True)
        self.reb.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        for i, w in enumerate((80, 58, 58, 62, 50, 38)):
            self.reb.setColumnWidth(i, w)
        reb_card.add(self.reb, 1)
        sl.addWidget(reb_card, 3)
        tl.addWidget(side)
        split.addWidget(top)

        bottom = Card("DRY-RUN 委托清单", "仅生成清单，不发送、不落任何交易接口")
        self.approve = QCheckBox("我已核对持仓与再平衡建议，批准生成 DRY-RUN 清单")
        self.approve.stateChanged.connect(self._gate)
        bottom.add(self.approve)
        self.orders = QPlainTextEdit()
        self.orders.setReadOnly(True)
        self.orders.setPlaceholderText("勾选批准后生成。")
        self.orders.setStyleSheet("QPlainTextEdit{font-family:Consolas,monospace;font-size:11px;}")
        bottom.add(self.orders, 1)
        row = QHBoxLayout()
        self.btn_orders = QPushButton("生成 DRY-RUN 委托")
        self.btn_orders.setEnabled(False)
        self.btn_orders.clicked.connect(self._orders)
        row.addWidget(self.btn_orders)
        row.addStretch(1)
        note = QLabel("提示：高价股差额不足 1 手时股数为 0，属正常约束，可改为按金额记录。")
        note.setStyleSheet(f"color:{MUTED}; font-size:9px;")
        row.addWidget(note)
        bottom.add_layout(row)
        split.addWidget(bottom)
        split.setSizes([420, 220])

    # ------------------------------------------------------------------
    def refresh(self, force: bool = False):
        if self._worker is not None and self._worker.isRunning():
            return
        self.updated.setText("正在刷新…")
        self._worker = FnWorker(self._load_payload, "portfolio")
        self._worker.done.connect(self.apply)
        self._worker.failed.connect(self._failed)
        self._worker.start()

    def _load_payload(self):
        pos = self.svc.positions()
        ana = self.svc.analytics(pos)
        reb = self.svc.rebalance(pos)
        return pos, ana, reb

    def _failed(self, msg: str):
        self.updated.setText(f"失败：{msg}")

    def apply(self, payload):
        pos, ana, reb = payload
        self._pos = pos
        self._rows = pos
        self.updated.setText(f"{len(pos)} 只持仓 · 更新 {datetime.now().strftime('%H:%M:%S')}")
        self.cards["mv"].set(money(ana["market_value"]))
        p = ana["pnl"]
        self.cards["pnl"].set(money(p), UP if p > 0 else DOWN if p < 0 else MUTED,
                              f"{ana['pnl_pct']:+.2f}%")
        d = ana["day_pnl"]
        self.cards["day"].set(money(d), UP if d > 0 else DOWN if d < 0 else MUTED,
                              f"{ana['day_pct']:+.2f}%")
        self.cards["vol"].set(f"{ana['vol_annual']:.1f}%")
        self.cards["var"].set(money(-ana["var95"]), DOWN, "历史模拟，非保证")
        self.cards["dd"].set(f"{ana['max_dd']:.1f}%", DOWN)
        self.cards["conc"].set(f"{ana['concentration']:.1f}%",
                               ACCENT if ana["concentration"] > 35 else None, "风险指标")
        self.cards["sharpe"].set(f"{ana['sharpe']:.2f}")

        prepare_rows(self.table, len(pos))
        for i, x in enumerate(pos):
            set_cell(self.table, i, 0, x["name"], TEXT, bold=True)
            set_cell(self.table, i, 1, x["symbol"], MUTED)
            set_cell(self.table, i, 2, f"{x['qty']:.0f}", None, align_right=True)
            set_cell(self.table, i, 3, price(x["cost"]), MUTED, align_right=True)
            set_cell(self.table, i, 4, price(x["price"]), TEXT, align_right=True)
            set_cell(self.table, i, 5, money(x["market_value"]), None, align_right=True)
            set_cell(self.table, i, 6, money(x["pnl"]), UP if x["pnl"] > 0 else DOWN, align_right=True)
            set_cell(self.table, i, 7, pct(x["pnl_pct"]), UP if x["pnl_pct"] > 0 else DOWN,
                     align_right=True)
            set_cell(self.table, i, 8, money(x["day_pnl"]),
                     UP if x["day_pnl"] > 0 else DOWN if x["day_pnl"] < 0 else MUTED, align_right=True)
            set_cell(self.table, i, 9, f"{x['weight'] * 100:.1f}%", MUTED, align_right=True)
        self.risk.setText("风险提示：" + "；".join(ana["risk_flags"]))
        if ana.get("curve"):
            self.curve.set_series(ana["curve"], 1.0, ACCENT)
        self._apply_rebalance(reb)
        self.orders.clear()
        self.approve.setChecked(False)

    def _apply_rebalance(self, reb):
        prepare_rows(self.reb, len(reb))
        for i, x in enumerate(reb):
            set_cell(self.reb, i, 0, x["name"], TEXT, bold=True)
            set_cell(self.reb, i, 1, f"{x['current']:.1f}%", MUTED, align_right=True)
            set_cell(self.reb, i, 2, f"{x['target']:.1f}%", None, align_right=True)
            dv = x["delta_value"]
            set_cell(self.reb, i, 3, money(dv), UP if dv > 0 else DOWN if dv < 0 else MUTED,
                     align_right=True)
            ds = x["delta_shares"]
            set_cell(self.reb, i, 4, f"{ds:+d}", UP if ds > 0 else DOWN if ds < 0 else MUTED,
                     align_right=True)
            set_cell(self.reb, i, 5, x["action"], UP if x["action"] == "买入" else DOWN
                     if x["action"] == "卖出" else MUTED, bold=True)
        self._reb = reb

    def _select(self):
        pass

    def _add(self):
        s = self.symbol.text().strip()
        if not s or not s.isdigit() or len(s) != 6:
            QMessageBox.warning(self, "代码无效", "请输入 6 位 A 股代码。")
            return
        qty = int(self.qty.value())
        cost = float(self.cost.value())
        try:
            self.svc.add(s, qty, cost)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "添加失败", str(e))
            return
        self.symbol.clear()
        self.refresh(True)

    def _delete(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._pos):
            QMessageBox.information(self, "未选择", "请先在持仓表中选择一行。")
            return
        x = self._pos[row]
        ok = QMessageBox.question(self, "删除持仓", f"删除 {x['name']}（{x['symbol']}）？")
        if ok != QMessageBox.StandardButton.Yes:
            return
        self.svc.delete(x["id"])
        self.refresh(True)

    def _gate(self):
        self.btn_orders.setEnabled(self.approve.isChecked())

    def _orders(self):
        if not self.approve.isChecked():
            return
        orders = self.svc.dry_run_orders(getattr(self, "_reb", []))
        if not orders:
            self.orders.setPlainText("没有达到 1 手阈值的差额，未生成委托。\n"
                                     "这是 100 股整手约束的结果，不代表再平衡方向错误。")
            return
        self.orders.setPlainText(json.dumps(orders, ensure_ascii=False, indent=2))
        self.orders.appendPlainText("\n以上为 DRY-RUN 清单，未发送至任何券商或交易接口。")
