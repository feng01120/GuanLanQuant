"""宏观与人文：经济指标、汇率利率、行业板块、情绪历史、事件日历。"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QSplitter, QVBoxLayout, QWidget)

from ...util import calendar_events, esc, money, pct
from ..theme import ACCENT, ACCENT2, DOWN, MUTED, TEXT, UP
from ..widgets.base import Card, MetricCard
from ..widgets.charts import Gauge, LineChart
from ..widgets.table import make_table, prepare_rows, set_cell
from ..workers import FnWorker


class MacroPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.market = ctx.market
        self._worker = None
        self._data = None
        self._boards = []
        self._hist = []
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 3, 0, 0)
        outer.setSpacing(9)
        head = QHBoxLayout()
        t = QLabel("宏观与人文")
        t.setMinimumHeight(21)
        t.setStyleSheet(f"color:{TEXT}; font-size:14px; font-weight:600;")
        head.addWidget(t)
        self.updated = QLabel("等待刷新")
        self.updated.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        head.addWidget(self.updated)
        head.addStretch(1)
        note = QLabel("官方数据 + 市场温度 + 人文日历，均为背景因子，不构成因果结论")
        note.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        head.addWidget(note)
        outer.addLayout(head)

        self.cards: dict[str, MetricCard] = {}
        grid = QGridLayout()
        grid.setSpacing(8)
        defs = [("pmi", "制造业 PMI"), ("cpi", "CPI 同比"), ("ppi", "PPI 同比"),
                ("gdp", "GDP 同比"), ("m2", "M2 同比"), ("fx", "USD/CNY"),
                ("bond", "国债ETF（利率代理）"), ("gold", "黄金当日"), ("oil", "原油当日"),
                ("amount", "两市成交额（估）")]
        for i, (key, label) in enumerate(defs):
            c = MetricCard(label)
            self.cards[key] = c
            grid.addWidget(c, i // 5, i % 5)
        outer.addLayout(grid)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        outer.addWidget(split, 1)

        left = Card("宏观评分", "增长 / 通胀 / 流动性 / 汇率 / 利率")
        left.setMinimumWidth(330)
        left.setMaximumWidth(400)
        self.gauge = Gauge(0, "宏观温度")
        left.add(self.gauge)
        self.reasons = QLabel("等待数据…")
        self.reasons.setWordWrap(True)
        self.reasons.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        self.reasons.setAlignment(Qt.AlignTop)
        left.add(self.reasons, 1)
        split.addWidget(left)

        mid = Card("汇率与利率", "近 30 个交易日；国债 ETF 价格上行≈收益率下行")
        self.fx_chart = LineChart()
        self.fx_chart.setMinimumHeight(120)
        self.bond_chart = LineChart()
        self.bond_chart.setMinimumHeight(120)
        fx_lab = QLabel("USD/CNY")
        fx_lab.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        bond_lab = QLabel("511010 国债ETF")
        bond_lab.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        mid.add(fx_lab)
        mid.add(self.fx_chart, 1)
        mid.add(bond_lab)
        mid.add(self.bond_chart, 1)
        split.addWidget(mid)

        right = Card("行业板块", "涨跌幅与成交额")
        right.setMinimumWidth(360)
        self.board_table = make_table(["板块", "涨跌", "成交额", "领涨"], [108, 74, 100, 92])
        self.board_table.verticalHeader().setDefaultSectionSize(20)
        right.add(self.board_table, 1)
        split.addWidget(right)
        split.setSizes([350, 480, 380])

        bottom = QSplitter(Qt.Horizontal)
        bottom.setChildrenCollapsible(False)
        outer.addWidget(bottom, 1)
        sent_card = Card("情绪历史", "每次刷新写入一次，观察极值与修复")
        self.sent_chart = LineChart()
        sent_card.add(self.sent_chart, 1)
        self.sent_note = QLabel("")
        self.sent_note.setStyleSheet(f"color:{MUTED}; font-size:9px;")
        sent_card.add(self.sent_note)
        bottom.addWidget(sent_card)

        cal_card = Card("人文与制度日历", "节庆消费、财报季、交割与考核")
        self.cal = QListWidget()
        self.cal.setStyleSheet("QListWidget{background:transparent;border:none;}")
        cal_card.add(self.cal, 1)
        bottom.addWidget(cal_card)
        bottom.setSizes([640, 460])

    # ------------------------------------------------------------------
    def refresh(self, force: bool = True):
        if self._worker is not None and self._worker.isRunning():
            return
        self.updated.setText("正在拉取官方数据…")

        def task():
            ctx = self.market.market_context(force=force)
            boards = []
            em = self.market.registry.get("datasource.eastmoney")
            if em is not None:
                try:
                    boards = em.boards(60)
                except Exception:
                    boards = []
            if not boards:
                sina = self.market.registry.get("datasource.sina")
                if sina is not None:
                    try:
                        boards = sina.boards(90)
                    except Exception:
                        boards = []
            hist = self.market.store.sentiment_history(120)
            return ctx, boards, hist

        w = FnWorker(task, "macro-page")
        w.done.connect(self._done)
        w.failed.connect(lambda e: self.updated.setText(f"失败：{e}"))
        w.start()
        self._worker = w

    def _done(self, payload):
        ctx, boards, hist = payload
        self._data = ctx
        self.apply(ctx)
        self.apply_boards(boards)
        self.apply_history(hist)

    def apply(self, ctx: dict):
        self._data = ctx
        macro = ctx.get("macro")
        if macro is not None:
            for key, label, unit in (("pmi", "制造业 PMI", ""), ("cpi", "CPI 同比", "%"),
                                     ("ppi", "PPI 同比", "%"), ("gdp", "GDP 同比", "%"),
                                     ("m2", "M2 同比", "%")):
                p = macro.by_key(key) if hasattr(macro, "by_key") else {}
                if p:
                    v = float(p.get("value", 0))
                    self.cards[key].set(f"{v:.1f}{unit}", None,
                                        f"{p.get('date', '')[:7]} · {p.get('source', '')[:8]}")
            self.gauge.set_value(macro.score)
            reasons = "".join(f"<div style='margin:2px 0'>· {esc(r)}</div>" for r in macro.reasons[:8])
            self.reasons.setText(reasons or "—")

        fx = ctx.get("macro").fx if ctx.get("macro") is not None else []
        if fx:
            latest = float(fx[-1]["value"])
            base = float(fx[max(0, len(fx) - 21)]["value"])
            chg = (latest / base - 1) * 100 if base else 0
            self.cards["fx"].set(f"{latest:.4f}", UP if chg > 0 else DOWN,
                                 f"20日 {chg:+.2f}%")
            self.fx_chart.set_series([float(x["value"]) for x in fx[-30:]], None, ACCENT)
        bond = ctx.get("macro").bond_close if ctx.get("macro") is not None else []
        if bond:
            latest = float(bond[-1])
            base = float(bond[max(0, len(bond) - 21)])
            chg = (latest / base - 1) * 100 if base else 0
            self.cards["bond"].set(f"{latest:.3f}", None, f"20日 {chg:+.2f}%")
            self.bond_chart.set_series(bond[-30:], None, ACCENT2)

        g = float(ctx.get("gold_pct", 0) or 0)
        o = float(ctx.get("oil_pct", 0) or 0)
        if ctx.get("gold_available", True):
            self.cards["gold"].set(pct(g), UP if g > 0 else DOWN if g < 0 else MUTED, "避险温度")
        else:
            self.cards["gold"].set("--", MUTED, "数据缺失")
        if ctx.get("oil_available", True):
            self.cards["oil"].set(pct(o), UP if o > 0 else DOWN if o < 0 else MUTED, "成本与通胀")
        else:
            self.cards["oil"].set("--", MUTED, "数据缺失")
        amount = float(ctx.get("amount_est", 0) or 0)
        self.cards["amount"].set(money(amount), None,
                                 f"分时进度 {ctx.get('progress', 0) * 100:.0f}%")
        self.updated.setText(f"更新 {ctx.get('updated', '')} · 宏观 {macro.score:+.1f}"
                             if macro is not None else "更新完成")

        # 人文日历
        self.cal.clear()
        for ev in calendar_events(date.today(), 21):
            d = ev.get("days", 0)
            prefix = "今天" if d == 0 else f"{d:+d}天"
            text = f"[{prefix}] {ev.get('title', '')}"
            item = QListWidgetItem(text)
            item.setToolTip(ev.get("impact", ""))
            if d <= 2:
                item.setForeground(QColor(ACCENT))
            self.cal.addItem(item)

    def apply_boards(self, boards):
        self._boards = boards or []
        rows = sorted(self._boards, key=lambda b: float(getattr(b, "pct", 0) or 0), reverse=True)[:8]
        prepare_rows(self.board_table, len(rows))
        for i, b in enumerate(rows):
            v = float(getattr(b, "pct", 0) or 0)
            set_cell(self.board_table, i, 0, str(getattr(b, "name", "")), TEXT)
            set_cell(self.board_table, i, 1, pct(v), UP if v > 0 else DOWN if v < 0 else MUTED,
                     align_right=True, bold=True)
            amount = float(getattr(b, "amount", 0) or 0)
            set_cell(self.board_table, i, 2, money(amount), MUTED, align_right=True)
            set_cell(self.board_table, i, 3, str(getattr(b, "leader", ""))[:8], MUTED)

    def apply_history(self, hist):
        self._hist = hist or []
        vals = [float(h.get("score", 0)) for h in hist]
        if vals:
            self.sent_chart.set_series(vals, 0.0, ACCENT)
            self.sent_note.setText(f"共 {len(vals)} 次快照；当前情绪 {vals[-1]:+.1f}。"
                                   "情绪是反向指标的必要非充分条件，需结合宽度与量能。")
        else:
            self.sent_note.setText("尚无情绪快照，校准一次后开始积累。")

    def update_context(self, ctx: dict):
        self.apply(ctx)
