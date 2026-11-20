"""总览页：指数、市场宽度、自选池研判、人文日历、校准日志。"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, Signal, QUrl, QRectF
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QSizePolicy, QSplitter,
                               QVBoxLayout, QWidget)

from ...config import INDICES
from ...util import LOG_RING, calendar_events, money, pct, price
from ..theme import ACCENT, BORDER, DOWN, FLAT, MUTED, TEXT, UP
from ..widgets.base import Badge, Card
from ..widgets.charts import Gauge, Sparkline
from ..widgets.table import make_table, prepare_rows, set_cell


class IndexTile(QFrame):
    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 8)
        lay.setSpacing(0)
        top = QHBoxLayout()
        self.name = QLabel(name)
        self.name.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        self.pct = Badge("--", "neutral")
        top.addWidget(self.name)
        top.addStretch(1)
        top.addWidget(self.pct)
        self.value = QLabel("--")
        self.value.setStyleSheet(f"color:{TEXT}; font-size:23px; font-weight:700;")
        self.value.setMinimumHeight(30)
        self.spark = Sparkline()
        self.spark.setFixedHeight(25)
        lay.addLayout(top)
        lay.addWidget(self.value)
        lay.addWidget(self.spark)

    def set(self, q, bars):
        self.value.setText(price(q.price) if q else "--")
        if q:
            tone = "up" if q.pct > 0 else "down" if q.pct < 0 else "neutral"
            self.pct.setText(pct(q.pct))
            self.pct.set_tone(tone)
            self.value.setStyleSheet(f"color:{UP if q.pct > 0 else DOWN if q.pct < 0 else TEXT};"
                                     "font-size:23px; font-weight:700;")
        else:
            self.pct.setText("--")
            self.pct.set_tone("neutral")
            self.value.setStyleSheet(f"color:{TEXT}; font-size:23px; font-weight:700;")
        if bars is not None and len(bars) > 5:
            self.spark.set_data(bars["close"].tolist(),
                                UP if bars["close"].iloc[-1] >= bars["close"].iloc[0] else DOWN)


class BreadthBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.up = 0
        self.down = 0
        self.flat = 0
        self.setFixedHeight(14)

    def set_data(self, up, down, flat):
        self.up, self.down, self.flat = up, down, flat
        self.update()

    def paintEvent(self, event):
        total = max(1, self.up + self.down + self.flat)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        x = 0
        for val, color in ((self.up, UP), (self.flat, MUTED), (self.down, DOWN)):
            seg = w * val / total
            p.setBrush(QColor(color))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(x, 0, max(0, seg - 1), h), 3, 3)
            x += seg


class DashboardPage(QWidget):
    symbol_selected = Signal(str)
    calibrate_requested = Signal()

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.market = ctx.market
        self.store = ctx.store
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 3, 0, 0)
        outer.setSpacing(10)

        # 指数卡
        row = QHBoxLayout()
        row.setSpacing(10)
        self.tiles = {}
        for secid, name, _ in INDICES:
            t = IndexTile(name)
            t.setMinimumHeight(102)
            self.tiles[secid] = t
            row.addWidget(t, 1)
        outer.addLayout(row)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        outer.addWidget(split, 1)

        # 左：市场宽度 + 情绪
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(10)
        breadth_card = Card("市场宽度", "涨跌家数 · 情绪温度")
        self.up_lab = QLabel("上涨 --")
        self.up_lab.setStyleSheet(f"color:{UP}; font-size:12px;")
        self.down_lab = QLabel("下跌 --")
        self.down_lab.setStyleSheet(f"color:{DOWN}; font-size:12px;")
        self.flat_lab = QLabel("平盘 --")
        self.flat_lab.setStyleSheet(f"color:{MUTED}; font-size:12px;")
        hb = QHBoxLayout()
        for w in (self.up_lab, self.flat_lab, self.down_lab):
            hb.addWidget(w)
        hb.addStretch(1)
        breadth_card.add_layout(hb)
        self.breadth_bar = BreadthBar()
        breadth_card.add(self.breadth_bar)
        self.gauge = Gauge(0, "市场情绪")
        self.gauge.setFixedHeight(190)
        breadth_card.add(self.gauge)
        self.sent_label = QLabel("等待数据")
        self.sent_label.setWordWrap(True)
        self.sent_label.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        breadth_card.add(self.sent_label)
        ll.addWidget(breadth_card, 1)

        width_card = Card("成交与涨停", "流动性温度")
        self.amount_lab = QLabel("成交额 --")
        self.amount_lab.setStyleSheet(f"color:{TEXT}; font-size:14px;")
        self.limit_lab = QLabel("涨停 -- / 跌停 --")
        self.limit_lab.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        self.macro_lab = QLabel("宏观评分 --")
        self.macro_lab.setWordWrap(True)
        self.macro_lab.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        width_card.add(self.amount_lab)
        width_card.add(self.limit_lab)
        width_card.add(self.macro_lab)
        ll.addWidget(width_card)
        split.addWidget(left)

        # 中：自选池
        center = Card("自选池 · 多维研判", "点击行进入个股分析")
        self.table = make_table(["名称", "现价", "涨跌", "六维", "T+1", "T+2", "20日", "信号"],
                                [168, 82, 68, 62, 58, 58, 62, 76])
        self.table.setMinimumHeight(300)
        self.table.cellClicked.connect(self._row_clicked)
        center.add(self.table, 1)
        self.summary = QLabel("预热中…")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(f"color:{MUTED}; font-size:11px; border-top:1px solid {BORDER}; padding-top:7px;")
        center.add(self.summary)
        split.addWidget(center)

        # 右：日历 + 快讯
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)
        cal_card = Card("人文 · 制度日历", "未来 30 天")
        self.cal = QListWidget()
        self.cal.setStyleSheet("QListWidget::item{padding:4px 2px;}")
        cal_card.add(self.cal, 1)
        rl.addWidget(cal_card, 3)
        news_card = Card("市场快讯", "东方财富 · 公开资讯")
        self.news = QListWidget()
        self.news.itemDoubleClicked.connect(self._open_news)
        news_card.add(self.news, 1)
        rl.addWidget(news_card, 4)
        split.addWidget(right)
        split.setSizes([290, 720, 330])

        # 底部：校准日志
        log_card = Card("每小时校准", "数据 → 因子 → 模型 → 权重 → 落库")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(300)
        self.log.setFixedHeight(96)
        self.log.setStyleSheet(f"font-size:11px; color:{MUTED};")
        log_card.add(self.log)
        self.cycle_lab = QLabel("尚未校准")
        self.cycle_lab.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        log_card.add(self.cycle_lab)
        outer.addWidget(log_card)

    # ------------------------------------------------------------------
    def _row_clicked(self, row, col):
        item = self.table.item(row, 0)
        if item:
            sym = item.data(Qt.UserRole)
            if sym:
                self.symbol_selected.emit(str(sym))

    def _open_news(self, item):
        url = item.data(Qt.UserRole)
        if url:
            QDesktopServices.openUrl(QUrl(str(url)))

    def refresh(self, ctx: dict | None = None):
        if ctx:
            self.update_context(ctx)
        self.refresh_table()

    def update_context(self, ctx: dict):
        for secid, _, _ in INDICES:
            q = ctx.get("quotes", {}).get(secid)
            bars = self.store.get_bars(secid, 60)
            self.tiles[secid].set(q, bars)
        up, down, flat = ctx.get("up", 0), ctx.get("down", 0), ctx.get("flat", 0)
        self.breadth_bar.set_data(up, down, flat)
        self.up_lab.setText(f"上涨 {up}")
        self.down_lab.setText(f"下跌 {down}")
        self.flat_lab.setText(f"平盘 {flat}")
        s = ctx.get("sentiment", {})
        self.gauge.set_value(s.get("score", 0), f"情绪 {s.get('label_text', '中性')}")
        rank = s.get("amount_rank")
        if ctx.get("amount_avg20", 0) and rank is not None:
            rank_text = f"成交额分位 {rank * 100:.0f}%"
        else:
            rank_text = "成交额分位暂缺"
        self.sent_label.setText(
            f"新闻语义 {s.get('news_score', 0) if 'news_score' in s else 0:+.0f} · "
            f"涨跌停 {ctx.get('limit_up', 0)}/{ctx.get('limit_down', 0)} · "
            f"{rank_text}")
        suffix = "（预估全天）" if ctx.get("progress", 1.0) < 0.98 else ""
        self.amount_lab.setText(f"两市成交额 {money(ctx.get('amount_est', ctx.get('amount', 0)))}{suffix}")
        self.limit_lab.setText(f"涨停 {ctx.get('limit_up', 0)} · 跌停 {ctx.get('limit_down', 0)}")
        macro = ctx.get("macro")
        if macro:
            self.macro_lab.setText(f"宏观评分 {macro.score:+.0f} · {macro.reasons[0] if macro.reasons else ''}")
        # 人文日历
        self.cal.clear()
        for e in [x for x in calendar_events(date.today(), 30) if x.get("days", 0) >= 0][:12]:
            days = e["days"]
            txt = f"{e['date'][5:]}  {e['title']}"
            sub = "（今日）" if days == 0 else (f"（{days}天后）" if days > 0 else "（已过）")
            item = QListWidgetItem(f"{txt} {sub}")
            color = {"假期": "#E7C873", "政策": "#4C8DFF", "财报": "#8E7CC3",
                     "交割": "#F0544F", "人文": "#2EC4B6", "制度": "#8CA0BE"}.get(e["kind"], MUTED)
            item.setForeground(QColor(color))
            item.setToolTip(e.get("impact", ""))
            self.cal.addItem(item)
        # 快讯
        self.news.clear()
        for n in ctx.get("scored_news", [])[:12]:
            title = n.get("title", "")
            item = QListWidgetItem(f"{n.get('time', '')[5:16]}  {title}")
            score = n.get("score", 0)
            item.setForeground(QColor(UP if score > 8 else DOWN if score < -8 else MUTED))
            item.setData(Qt.UserRole, n.get("url", ""))
            item.setToolTip(title + "\n情绪 " + f"{score:+.0f}")
            self.news.addItem(item)

        self.refresh_table()

    def update_quotes(self, quotes: dict):
        for secid, _, _ in INDICES:
            q = quotes.get(secid)
            if q:
                self.tiles[secid].set(q, self.store.get_bars(secid, 60))
        self.refresh_table()

    def refresh_table(self):
        symbols = self.market.settings.watchlist
        names = self.market.settings.watchlist_names
        prepare_rows(self.table, len(symbols))
        for i, s in enumerate(symbols):
            cached = self.market._analysis_cache.get(s)
            r = cached[1] if cached else None
            if r:
                q = r.get("quote")
                set_cell(self.table, i, 0, r["name"], None, bold=True)
                self.table.item(i, 0).setData(Qt.UserRole, s)
                qd = self.store.get_quote(s)
                cur = float(qd.get("price", 0)) if qd else (q.price if q else 0)
                pv = float(qd.get("pct", 0) or 0) if qd else (q.pct if q else 0)
                set_cell(self.table, i, 1, price(cur) if cur else "--", align_right=True)
                set_cell(self.table, i, 2, pct(pv), UP if pv > 0 else DOWN if pv < 0 else MUTED,
                         align_right=True)
                total = r["fused"]["total"]
                set_cell(self.table, i, 3, f"{total:+.0f}", UP if total > 0 else DOWN if total < 0 else MUTED,
                         bold=True, align_right=True)
                s1 = r["short"].get(1, {})
                s2 = r["short"].get(2, {})
                l20 = r["long"]["horizons"].get(20, {})
                set_cell(self.table, i, 4, f"{s1.get('prob_up', 0.5) * 100:.0f}%", align_right=True)
                set_cell(self.table, i, 5, f"{s2.get('prob_up', 0.5) * 100:.0f}%", align_right=True)
                set_cell(self.table, i, 6, f"{l20.get('prob_up', 0.5) * 100:.0f}%", align_right=True)
                set_cell(self.table, i, 7, r["fused"]["verdict"], align_right=True)
                self._color_signal(i, r["fused"]["signal"])
                self.table.item(i, 0).setToolTip(
                    f"{r['name']}｜{r.get('industry', '')}\n{r['research']['summary']}")
            else:
                qd = self.store.get_quote(s)
                name = qd.get("name", names.get(s, s)) if qd else names.get(s, s)
                set_cell(self.table, i, 0, name, None, bold=True)
                self.table.item(i, 0).setData(Qt.UserRole, s)
                if qd:
                    set_cell(self.table, i, 1, price(qd.get("price", 0)), None, align_right=True)
                    pv = float(qd.get("pct", 0) or 0)
                    set_cell(self.table, i, 2, pct(pv), UP if pv > 0 else DOWN if pv < 0 else MUTED,
                             align_right=True)
                else:
                    set_cell(self.table, i, 1, "--", MUTED, align_right=True)
                    set_cell(self.table, i, 2, "--", MUTED, align_right=True)
                for c in range(3, 8):
                    set_cell(self.table, i, c, "--", "#5B6B82", align_right=True)
        n = len([1 for s in symbols if s in self.market._analysis_cache])
        if n:
            rs = [self.market._analysis_cache[s][1] for s in symbols if s in self.market._analysis_cache]
            avg = sum(r["fused"]["total"] for r in rs) / len(rs)
            self.summary.setText(f"已研判 {n}/{len(symbols)} 只 · 平均六维 {avg:+.1f} · "
                                 f"模型每小时重估一次，盘中报价每 20 秒刷新。")
        else:
            self.summary.setText("正在预热自选池；可到「个股」页立即分析单只标的。")

    def _color_signal(self, row, signal):
        color = {"BULL": UP, "LEAN_BULL": "#E7A15A", "NEUTRAL": MUTED,
                 "LEAN_BEAR": "#5FA8D3", "BEAR": DOWN}.get(signal, MUTED)
        item = self.table.item(row, 7)
        if item:
            item.setForeground(QColor(color))

    def update_analysis(self, r: dict):
        self.refresh_table()

    def append_log(self, text: str):
        self.log.appendPlainText(text)
        self.cycle_lab.setText(f"最后更新：{text.split('·')[0].strip()}")

    def set_cycle(self, msg: str, stats: dict | None = None):
        self.append_log(msg)
        if stats:
            self.cycle_lab.setText(f"本轮 {stats.get('n', 0)} 只 · 耗时 {stats.get('elapsed', 0)}s · "
                                   f"平均 {stats.get('avg_score', 0):+.1f}")

    def load_logs(self):
        for line in LOG_RING.lines()[-120:]:
            self.log.appendPlainText(line)
