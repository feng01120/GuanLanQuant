"""每日荐股：收盘复盘、热门板块与 3 日概率候选。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QSplitter, QTextBrowser, QVBoxLayout, QWidget)

from ...util import esc, pct, price
from ..theme import ACCENT, BORDER, DOWN, MUTED, TEXT, UP
from ..widgets.base import Badge, Card, MetricCard
from ..widgets.table import make_table, prepare_rows, set_cell
from ..workers import FnWorker


class RecommendPage(QWidget):
    symbol_selected = Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.svc = ctx.recommend
        self._data = None
        self._worker = None
        self._build()

    # ------------------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("每日荐股")
        title.setObjectName("PageTitle")
        head.addWidget(title)
        self.phase = Badge("等待数据", "neutral")
        head.addWidget(self.phase)
        self.date_lbl = QLabel("数据截至 --")
        self.date_lbl.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        head.addWidget(self.date_lbl)
        head.addStretch(1)
        self.status = QLabel("收盘后生成市场复盘与 3 日概率候选")
        self.status.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        head.addWidget(self.status)
        self.refresh_btn = QPushButton("生成 / 刷新")
        self.refresh_btn.setObjectName("Primary")
        self.refresh_btn.clicked.connect(lambda: self.refresh(force=True))
        head.addWidget(self.refresh_btn)
        root.addLayout(head)

        self.summary = QLabel("正在读取收盘数据…")
        self.summary.setWordWrap(True)
        self.summary.setObjectName("Panel")
        self.summary.setStyleSheet(
            f"background:#FFFFFF; border:1px solid {BORDER}; border-left:3px solid {ACCENT};"
            f" border-radius:8px; padding:9px 12px; color:{TEXT}; font-size:10.5px;")
        root.addWidget(self.summary)

        metrics = QHBoxLayout()
        metrics.setSpacing(10)
        self.m_index = MetricCard("上证指数", "--", "等待数据")
        self.m_breadth = MetricCard("涨跌家数", "--", "上涨 / 下跌")
        self.m_amount = MetricCard("两市成交额", "--", "亿元")
        self.m_limit = MetricCard("涨停 / 跌停", "--", "家")
        for m in (self.m_index, self.m_breadth, self.m_amount, self.m_limit):
            m.setMinimumHeight(64)
            m.setMaximumHeight(74)
            metrics.addWidget(m, 1)
        root.addLayout(metrics)

        split = QSplitter(Qt.Horizontal)
        split.setObjectName("MainSplitter")
        split.setChildrenCollapsible(False)
        split.setHandleWidth(8)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(10)

        self.pick_card = Card("3 日涨幅 ≥3% 候选",
                              "45 个历史相似形态 + 板块/市场微调")
        self.pick_note = QLabel("")
        self.pick_note.setWordWrap(True)
        self.pick_note.setStyleSheet(
            f"background:#FFF8E8; border-left:3px solid {ACCENT}; color:{TEXT};"
            " padding:6px 9px; font-size:10px;")
        self.pick_note.setVisible(False)
        self.pick_card.add(self.pick_note)
        self.pick_table = make_table(
            ["代码", "名称", "行业", "现价", "3日概率", "类比中位", "类比区间", "等级"],
            [72, 88, 82, 66, 68, 68, 110, 0])
        self.pick_table.verticalHeader().setDefaultSectionSize(30)
        self.pick_table.setMinimumHeight(220)
        self.pick_table.doubleClicked.connect(self._open_row)
        self.pick_card.add(self.pick_table, 1)
        self.stats_lbl = QLabel("等待生成")
        self.stats_lbl.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        self.pick_card.add(self.stats_lbl)
        ll.addWidget(self.pick_card, 1)

        self.sector_card = Card("热门板块", "涨幅 + 板块宽度 + 相对强度")
        self.sector_table = make_table(
            ["#", "板块", "涨幅", "涨跌家数", "研判"],
            [28, 130, 82, 82, 0])
        self.sector_table.verticalHeader().setDefaultSectionSize(30)
        self.sector_table.setMinimumHeight(210)
        self.sector_card.add(self.sector_table, 1)
        self.sector_note = QLabel("热门板块用于解释当日资金方向，不直接等同于荐股方向。")
        self.sector_note.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        self.sector_card.add(self.sector_note)
        ll.addWidget(self.sector_card, 1)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)
        self.recap_card = Card("收盘复盘", "生成后自动更新")
        self.recap = QTextBrowser()
        self.recap.setOpenLinks(False)
        self.recap.setMinimumHeight(250)
        self.recap_card.add(self.recap, 1)
        rl.addWidget(self.recap_card, 3)

        self.method_card = Card("模型口径与风险", "概率不是收益承诺")
        self.method = QTextBrowser()
        self.method.setOpenLinks(False)
        self.method.setMinimumHeight(230)
        self.method_card.add(self.method, 1)
        self.method_card.add(QLabel("仅供研究，不构成投资建议；不接入实盘。"))
        rl.addWidget(self.method_card, 2)
        split.addWidget(right)
        split.setSizes([860, 470])
        root.addWidget(split, 1)

        self._set_loading_text()

    # ------------------------------------------------------------------
    def _set_loading_text(self):
        self.recap.setHtml(
            f"<div style='color:{MUTED}; font-size:10pt; line-height:1.7'>"
            "正在生成收盘复盘。<br>首次加载会读取指数、板块、全市场成交额榜与候选股 K 线，"
            "通常需要 20–60 秒；完整结果缓存 30 分钟，接口异常时使用 5 分钟短缓存。</div>")
        self.method.setHtml(
            f"<div style='color:{MUTED}; font-size:10pt; line-height:1.7'>"
            "等待模型结果。<br>页面会显示候选股的 3 日估算概率、历史类比区间与风险标签。</div>")

    # ------------------------------------------------------------------
    def ensure_loaded(self):
        if self._data is None and (self._worker is None or not self._worker.isRunning()):
            self.refresh(force=False)

    def refresh(self, force: bool = False):
        if self._worker is not None and self._worker.isRunning():
            return
        self.refresh_btn.setEnabled(False)
        self.status.setText("读取指数 / 板块 / 全市场列表…")
        self._set_loading_text()

        def task():
            return self.svc.daily(force=force)

        w = FnWorker(task, "recommend")
        w.done.connect(self.apply)
        w.failed.connect(self._failed)
        w.start()
        self._worker = w

    def _failed(self, msg: str):
        self.refresh_btn.setEnabled(True)
        self.status.setText(f"生成失败：{msg}")
        self.summary.setText(f"生成失败：{msg}")
        self.summary.setStyleSheet(
            f"background:#FFFFFF; border:1px solid {BORDER}; border-left:3px solid {DOWN};"
            f" border-radius:8px; padding:9px 12px; color:{TEXT}; font-size:10.5px;")

    # ------------------------------------------------------------------
    def apply(self, data: dict):
        self._data = data
        self.refresh_btn.setEnabled(True)
        market = data.get("market") or {}
        stats = data.get("stats") or {}
        self.phase.setText(data.get("title_phase", "收盘复盘"))
        self.phase.set_tone("gold" if data.get("is_final") else "neutral")
        self.date_lbl.setText(f"数据截至 {data.get('date', '--')} · 生成 {data.get('updated', '--')}")
        self.status.setText(
            f"扫描 {stats.get('analyzed', 0)} 只 · 达门槛 {stats.get('qualified', 0)} 只"
            f" · 失败 {stats.get('errors', 0)} 只 · 耗时 {data.get('elapsed', '--')}s")
        notes = [str(x) for x in (data.get("data_notes") or []) if x]
        if data.get("data_quality") != "ok":
            self.status.setText(self.status.text() + " · 数据不完整")
        self.summary.setText(market.get("summary", "暂无市场摘要") +
                             (("　" + "；".join(notes)) if notes else
                              ("　（部分数据接口暂缺，本次使用 5 分钟短缓存）"
                               if data.get("data_quality") != "ok" else "")))
        if market.get("weak"):
            self.summary.setStyleSheet(
                f"background:#FFF7F7; border:1px solid #F0C9C9; border-left:3px solid {DOWN};"
                f" border-radius:8px; padding:9px 12px; color:{TEXT}; font-size:10.5px;")
        else:
            self.summary.setStyleSheet(
                f"background:#FFFFFF; border:1px solid {BORDER}; border-left:3px solid {ACCENT};"
                f" border-radius:8px; padding:9px 12px; color:{TEXT}; font-size:10.5px;")

        idx = (market.get("indices") or [{}])[0]
        self.m_index.set(
            pct(idx.get("pct", 0.0)),
            UP if idx.get("pct", 0) > 0 else DOWN if idx.get("pct", 0) < 0 else MUTED,
            idx.get("name", "上证指数"))
        if market.get("breadth_missing"):
            self.m_breadth.set("—", MUTED, "涨跌家数接口暂缺")
        else:
            self.m_breadth.set(f"{market.get('up', 0)} / {market.get('down', 0)}",
                               TEXT, "上涨 / 下跌")
        amount = float(market.get("amount") or 0)
        if amount <= 0:
            self.m_amount.set("—", MUTED, "成交额接口暂缺")
        else:
            self.m_amount.set(f"{amount / 10000:.2f} 万亿" if amount >= 10000 else f"{amount:.0f} 亿",
                              TEXT, f"20日均量 {market.get('amount_ratio', 0) * 100:.0f}%"
                              if market.get("amount_ratio") else "20日均量暂缺")
        self.m_limit.set(f"{market.get('limit_up', 0)} / {market.get('limit_down', 0)}",
                         UP if market.get("limit_up", 0) > market.get("limit_down", 0)
                         else DOWN if market.get("limit_down", 0) > market.get("limit_up", 0)
                         else MUTED, "涨停 / 跌停")

        self._render_picks(data.get("picks") or [], stats)
        self._render_sectors(data.get("sectors") or [])
        self._render_recap(data)

    # ------------------------------------------------------------------
    def _render_picks(self, picks: list[dict], stats: dict):
        prepare_rows(self.pick_table, len(picks))
        for row, x in enumerate(picks):
            tip = "理由：\n- " + "\n- ".join(x.get("reasons") or []) + \
                  "\n\n风险：\n- " + "\n- ".join(x.get("risks") or [])
            set_cell(self.pick_table, row, 0, x["symbol"], MUTED, tooltip=tip)
            set_cell(self.pick_table, row, 1, x["name"], TEXT, bold=True, tooltip=tip)
            set_cell(self.pick_table, row, 2, x.get("industry") or "行业缺失", MUTED)
            set_cell(self.pick_table, row, 3, price(x.get("price", 0)), TEXT, align_right=True)
            prob = float(x.get("prob3") or 0)
            color = ACCENT if prob >= 0.45 else TEXT if prob >= 0.35 else MUTED
            set_cell(self.pick_table, row, 4, f"{prob * 100:.1f}%", color, bold=True,
                     align_right=True, tooltip=tip)
            set_cell(self.pick_table, row, 5, f"{x.get('med3', 0) * 100:+.2f}%",
                     UP if x.get("med3", 0) > 0 else DOWN if x.get("med3", 0) < 0 else MUTED,
                     align_right=True)
            set_cell(self.pick_table, row, 6,
                     f"{x.get('q25', 0) * 100:+.1f}% ~ {x.get('q75', 0) * 100:+.1f}%",
                     MUTED, align_right=True)
            grade = x.get("grade") or "观察"
            set_cell(self.pick_table, row, 7, grade,
                     ACCENT if grade == "重点关注" else MUTED, bold=grade != "弱信号",
                     tooltip=tip)
            self.pick_table.setRowHeight(row, 30)
        note = stats.get("note") or ""
        if not picks:
            note = "今日没有生成候选：可能是数据接口暂缺或交易样本不足，请稍后刷新。"
        self.pick_note.setText(note)
        self.pick_note.setVisible(bool(note))
        source_label = {"sina": "新浪行业", "eastmoney": "东方财富"}.get(
            stats.get("board_source"), stats.get("board_source") or "")
        self.stats_lbl.setText(
            f"候选池 {stats.get('pool', 0)} · 基础过滤 {stats.get('basic', 0)}"
            f" · 深度分析 {stats.get('analyzed', 0)} · 达 35% 门槛 {stats.get('qualified', 0)}"
            f" · 展示 {len(picks)} 只"
            + (f" · 失败 {stats.get('errors')} 只" if stats.get("errors") else "")
            + (f" · 板块源 {source_label}" if source_label else "")
            + (f" · {stats.get('fallback')}兜底" if stats.get("fallback") else ""))

    def _render_sectors(self, sectors: list[dict]):
        prepare_rows(self.sector_table, len(sectors))
        source = next((s.get("source") for s in sectors if s.get("source")), "")
        note = ("热门板块用于解释当日相对强弱，不直接等同于荐股方向。"
                if sectors else "板块接口暂缺，本次未生成热门板块研判；可稍后重新刷新。")
        if source == "sina":
            note += " 当前板块来自新浪行业口径，暂缺板块涨跌家数。"
        self.sector_note.setText(note)
        for row, s in enumerate(sectors):
            tip = f"龙头：{s.get('leader', '--')}\n研判：{s.get('comment', '')}"
            set_cell(self.sector_table, row, 0, str(s.get("rank", row + 1)), MUTED)
            set_cell(self.sector_table, row, 1, s.get("name", ""), TEXT, bold=True, tooltip=tip)
            p = float(s.get("pct") or 0)
            set_cell(self.sector_table, row, 2, pct(p), UP if p > 0 else DOWN if p < 0 else MUTED,
                     bold=True, align_right=True)
            set_cell(self.sector_table, row, 3,
                     str(s.get("updown_text") or f"{s.get('up', 0)}/{s.get('down', 0)}"),
                     MUTED, align_right=True)
            set_cell(self.sector_table, row, 4, s.get("comment", ""), MUTED, tooltip=tip)
            self.sector_table.setRowHeight(row, 30)

    def _render_recap(self, data: dict):
        market = data.get("market") or {}
        rows = []
        for item in data.get("recap") or []:
            rows.append(
                f"<div style='margin:0 0 7px 0'>"
                f"<span style='color:{MUTED}; font-size:9.5pt'>{esc(item.get('label', ''))}</span><br>"
                f"<span style='color:{TEXT}; font-size:10pt'>{esc(item.get('text', ''))}</span></div>")
        risk = esc(market.get("risk_text", ""))
        risk_color = DOWN if market.get("weak") else ACCENT
        html = "".join(rows) + (
            f"<div style='margin-top:8px; padding-top:8px; border-top:1px solid {BORDER};"
            f" color:{risk_color}; font-size:9.5pt; line-height:1.55'>{risk}</div>")
        self.recap.setHtml(f"<div style='line-height:1.55'>{html}</div>")

        method = esc(data.get("method") or "").replace("\n", "<br>")
        note = esc(data.get("disclaimer", ""))
        self.method.setHtml(
            f"<div style='color:{TEXT}; font-size:9.5pt; line-height:1.7'>{method}</div>"
            f"<div style='margin-top:8px; color:{ACCENT}; font-size:9.5pt'>{note}</div>")

    # ------------------------------------------------------------------
    def _open_row(self, index):
        row = index.row()
        item = self.pick_table.item(row, 0)
        if item and item.text():
            self.symbol_selected.emit(item.text())
