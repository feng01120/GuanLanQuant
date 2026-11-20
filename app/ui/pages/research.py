"""研究台·个股综合结论页：六维评分、多空辩论、交易员与风控、因子依据。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QTextBrowser, QVBoxLayout, QWidget)

from ...util import esc, price
from ..theme import ACCENT, BORDER, DOWN, MUTED, TEXT, UP
from ..widgets.base import Badge, Card, KeyValue, ScoreBar
from ..widgets.table import make_table, prepare_rows, set_cell
from ..workers import FnWorker


class ResearchPage(QWidget):
    analysis_ready = Signal(dict)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.market = ctx.market
        self._data = None
        self._worker = None
        self._pending: tuple[str, bool] | None = None
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 2, 0, 0)
        outer.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(10)
        self.name = QLabel("个股研究")
        self.name.setStyleSheet(f"color:{TEXT}; font-size:20px; font-weight:700;")
        head.addWidget(self.name)
        self.code = QLabel("")
        self.code.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        head.addWidget(self.code)
        self.industry = Badge("", "gold")
        head.addWidget(self.industry)
        head.addSpacing(8)
        self.total = QLabel("--")
        self.total.setStyleSheet(f"color:{TEXT}; font-size:24px; font-weight:700;")
        head.addWidget(self.total)
        self.verdict = Badge("等待分析", "neutral")
        head.addWidget(self.verdict)
        self.conf = QLabel("置信 --")
        self.conf.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        head.addWidget(self.conf)
        head.addStretch(1)
        self.status = QLabel("在 K 线终端或总览选择标的后自动同步；本页不再重复 K 线。")
        self.status.setStyleSheet(f"color:{MUTED}; font-size:9px;")
        head.addWidget(self.status)
        outer.addLayout(head)

        self.summary = QLabel("等待分析结果。")
        self.summary.setWordWrap(True)
        self.summary.setObjectName("Panel")
        self.summary.setStyleSheet(
            f"background:#FFFDF7; border:1px solid #EADFC8; border-left:3px solid {ACCENT};"
            f" border-radius:6px; padding:9px 12px; color:{TEXT}; font-size:12px;")
        outer.addWidget(self.summary)

        mid = QHBoxLayout()
        mid.setSpacing(9)

        # 六维
        left_col = QWidget()
        left_lay = QVBoxLayout(left_col)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(9)
        dim_card = Card("六维评分", "技术 30% · 资金 15% · 估值 10% · 情绪 17% · 宏观 16% · 人文 12%")
        dim_card.setMinimumWidth(470)
        self.bars = {}
        self.notes = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        for row, key in enumerate(("technical", "fund", "valuation", "sentiment", "macro", "humanities")):
            bar = ScoreBar("")
            bar.setFixedHeight(26)
            self.bars[key] = bar
            grid.addWidget(bar, row, 0)
            note = QLabel("")
            note.setStyleSheet(f"color:{MUTED}; font-size:9px;")
            note.setWordWrap(True)
            self.notes[key] = note
            grid.addWidget(note, row, 1)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 4)
        dim_card.add_layout(grid, 0)
        self.dim_note = QLabel("")
        self.dim_note.setWordWrap(True)
        self.dim_note.setStyleSheet(
            f"color:{MUTED}; font-size:9px; border-top:1px solid {BORDER}; padding-top:5px;")
        dim_card.add(self.dim_note)
        dim_card.body.addStretch(1)
        left_lay.addWidget(dim_card, 3)

        read_card = Card("关键读数", "支撑压力 · 波动 · 位置")
        rg = QGridLayout()
        rg.setHorizontalSpacing(12)
        rg.setVerticalSpacing(1)
        self.read_kv = {}
        for i, key in enumerate(("支撑", "压力", "RSI(14)", "ATR", "52周分位", "量比")):
            kv = KeyValue(key, "--")
            self.read_kv[key] = kv
            rg.addWidget(kv, i // 2, i % 2)
        read_card.add_layout(rg, 0)
        read_card.body.addStretch(1)
        left_lay.addWidget(read_card, 2)
        mid.addWidget(left_col, 5)

        # 多空
        debate = Card("多空辩论", "研究员基于六维贡献与模型概率")
        debate.setMinimumWidth(430)
        bl = QLabel("多方论据")
        bl.setStyleSheet(f"color:{UP}; font-size:11px; font-weight:600;")
        debate.add(bl)
        self.bull = QTextBrowser()
        self.bull.setOpenExternalLinks(False)
        self.bull.setMinimumHeight(160)
        debate.add(self.bull, 1)
        br = QLabel("空方论据")
        br.setStyleSheet(f"color:{DOWN}; font-size:11px; font-weight:600;")
        debate.add(br)
        self.bear = QTextBrowser()
        self.bear.setMinimumHeight(160)
        debate.add(self.bear, 1)
        mid.addWidget(debate, 5)

        # 交易员/风控
        trade = Card("交易员与风控", "纪律优先，非投资建议")
        trade.setMinimumWidth(380)
        self.kv = {}
        for key in ("建议动作", "建议仓位", "建仓区间", "止损", "目标", "盈亏比", "风险等级"):
            kv = KeyValue(key, "--")
            self.kv[key] = kv
            trade.add(kv)
        rl = QLabel("风控清单")
        rl.setStyleSheet(f"color:{MUTED}; font-size:10px; padding-top:5px;")
        trade.add(rl)
        self.risks = QTextBrowser()
        self.risks.setMinimumHeight(150)
        trade.add(self.risks, 1)
        mid.addWidget(trade, 4)
        outer.addLayout(mid)

        factor = Card("因子依据", "分数与贡献已按权重折算")
        self.table = make_table(["维度", "得分", "权重", "贡献", "主要依据"], [70, 58, 56, 58, 760])
        self.table.setWordWrap(True)
        factor.add(self.table, 1)
        outer.addWidget(factor, 1)

    # ------------------------------------------------------------------
    def load(self, symbol: str | None, force: bool = True):
        if not symbol:
            return
        symbol = str(symbol)
        if self._worker is not None and self._worker.isRunning():
            # 快速连续切标的时不要丢掉最后一次点击；等当前分析结束后再补跑，
            # 否则用户会觉得“点了没反应”。
            self._pending = (symbol, force)
            self.status.setText(f"{symbol} 已排队，等待当前分析完成…")
            return
        self._start(symbol, force)

    def _start(self, symbol: str, force: bool):
        self.ctx.active_symbol = symbol
        if not force:
            cached = self.market._analysis_cache.get(symbol)
            if cached:
                self.apply(cached[1])
                self._drain()
                return
        self.status.setText(f"正在分析 {symbol}…")
        self._pending = None

        def task():
            return self.market.analyze(symbol, force=force, persist=False)

        w = FnWorker(task, f"research-{symbol}")
        w.done.connect(lambda r, ww=w: self._on_done(r, ww))
        w.failed.connect(lambda e, ww=w: self._on_failed(e, ww))
        w.start()
        self._worker = w

    def _on_done(self, r: dict, w):
        if self._worker is w:
            self._worker = None
        self._loaded(r)
        self._drain()

    def _on_failed(self, msg: str, w):
        if self._worker is w:
            self._worker = None
        self.status.setText(f"分析失败：{msg}")
        self._drain()

    def _drain(self):
        if self._pending is not None:
            sym, force = self._pending
            self._pending = None
            self._start(sym, force)

    def _loaded(self, r: dict):
        self.apply(r)
        self.analysis_ready.emit(r)

    def apply(self, r: dict):
        self._data = r
        self.name.setText(r["name"])
        self.code.setText(r["symbol"])
        self.industry.setText(r.get("industry", "") or "行业缺失")
        fused = r.get("fused", {})
        total = float(fused.get("total", 0))
        self.total.setText(f"{total:+.1f}")
        self.total.setStyleSheet(
            f"color:{UP if total > 0 else DOWN if total < 0 else TEXT}; font-size:24px; font-weight:700;")
        self.verdict.setText(fused.get("verdict", "中性"))
        self.verdict.set_tone("up" if total > 0 else "down" if total < 0 else "neutral")
        self.conf.setText(f"置信 {fused.get('confidence', 0):.0f} · 一致性 {fused.get('agreement', 0) * 100:.0f}%")
        self.status.setText(f"更新 {r['updated']} · {r['market_phase']} · 数据截至 {r['snapshot'].get('date', '')}")

        research = r.get("research", {})
        self.summary.setText(research.get("summary", "暂无研判摘要。"))

        dims = r.get("dimensions", {})
        radar = {d["key"]: d for d in fused.get("radar", [])}
        for key, bar in self.bars.items():
            d = radar.get(key, {})
            dim = dims.get(key, {})
            bar.set_value(d.get("score", 0), d.get("label", dim.get("label", key)))
            reasons = dim.get("reasons", [])
            self.notes[key].setText(
                f"贡献 {d.get('contribution', 0):+.1f} · 权重 {d.get('weight', 0) * 100:.0f}%"
                + (f" · {reasons[0]}" if reasons else ""))

        contribs = fused.get("contributions", {})
        labels = {d["key"]: d["label"] for d in fused.get("radar", [])}
        pos = max(contribs.items(), key=lambda x: x[1], default=("", 0))
        neg = min(contribs.items(), key=lambda x: x[1], default=("", 0))
        snap = r.get("snapshot", {})
        self.dim_note.setText(
            f"综合 {total:+.1f}；最大正贡献 {labels.get(pos[0], pos[0])} {pos[1]:+.1f}，"
            f"最大拖累 {labels.get(neg[0], neg[0])} {neg[1]:+.1f}。\n"
            f"支撑 {price(snap.get('support', 0))} / 压力 {price(snap.get('resistance', 0))}；"
            f"RSI {snap.get('rsi', 50):.1f} · ATR {snap.get('atr_pct', 0) * 100:.1f}% · "
            f"52周分位 {snap.get('pos_52w', 0) * 100:.0f}%")

        self.read_kv["支撑"].set(price(snap.get("support", 0)))
        self.read_kv["压力"].set(price(snap.get("resistance", 0)))
        self.read_kv["RSI(14)"].set(f"{snap.get('rsi', 50):.1f}")
        self.read_kv["ATR"].set(f"{snap.get('atr_pct', 0) * 100:.1f}%")
        self.read_kv["52周分位"].set(f"{snap.get('pos_52w', 0) * 100:.0f}%")
        self.read_kv["量比"].set(f"{snap.get('vol_ratio', 0):.2f}")

        self.bull.setHtml(_bullets(research.get("bull", []), UP))
        self.bear.setHtml(_bullets(research.get("bear", []), DOWN))

        dec = research.get("decision", {})
        self.kv["建议动作"].set(dec.get("action", "--"),
                               UP if "多" in str(dec.get("action", "")) else DOWN if "空" in str(dec.get("action", "")) else TEXT)
        self.kv["建议仓位"].set(f"{dec.get('position_pct', 0):.1f}%")
        self.kv["建仓区间"].set(f"{price(dec.get('entry_low', 0))} ~ {price(dec.get('entry_high', 0))}")
        self.kv["止损"].set(price(dec.get("stop", 0)), DOWN)
        self.kv["目标"].set(price(dec.get("target", 0)), UP)
        self.kv["盈亏比"].set(f"{dec.get('risk_reward', 0):.2f}")
        self.kv["风险等级"].set(research.get("risk_level", "--"),
                               DOWN if research.get("risk_level") == "高" else TEXT)
        self.risks.setHtml(_bullets(research.get("risks", []), ACCENT))

        rows = []
        for d in fused.get("radar", []):
            dim = dims.get(d["key"], {})
            rows.append((d["label"], d["score"], d["weight"], d["contribution"],
                         "；".join(dim.get("reasons", [])[:3])))
        prepare_rows(self.table, len(rows))
        for i, (label, score, weight, contrib, reason) in enumerate(rows):
            set_cell(self.table, i, 0, label, None, bold=True)
            set_cell(self.table, i, 1, f"{score:+.1f}",
                     UP if score > 0 else DOWN if score < 0 else MUTED, align_right=True)
            set_cell(self.table, i, 2, f"{weight * 100:.0f}%", MUTED, align_right=True)
            set_cell(self.table, i, 3, f"{contrib:+.1f}",
                     UP if contrib > 0 else DOWN if contrib < 0 else MUTED, align_right=True)
            set_cell(self.table, i, 4, reason)
            self.table.setRowHeight(i, 30)


def _bullets(items, color: str) -> str:
    if not items:
        return f'<div style="color:{MUTED}; font-size:10px;">暂无</div>'
    body = "".join(
        f'<li style="margin:0 0 6px 0; color:{TEXT}; font-size:10px; line-height:1.55;">{esc(x)}</li>'
        for x in items)
    return (f'<ul style="margin:2px 0 0 14px; padding:0; border-left:2px solid {color};">'
            f'{body}</ul>')
