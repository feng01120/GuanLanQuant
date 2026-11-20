"""主窗口：导航、顶栏、状态栏与后台任务编排。"""
from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow,
                               QPushButton, QStackedWidget, QStatusBar, QVBoxLayout, QWidget)

from ..config import APP_VERSION, INDICES
from ..util import market_phase
from .pages.dashboard import DashboardPage
from .pages.events import EventsPage
from .pages.forecast import ForecastPage
from .pages.macro import MacroPage
from .pages.plugins import PluginsPage
from .pages.portfolio import PortfolioPage
from .pages.recommend import RecommendPage
from .pages.report import ReportPage
from .pages.research import ResearchPage
from .pages.settings import SettingsPage
from .pages.terminal import TerminalPage
from .theme import ACCENT, ACCENT2, BG, BG2, BORDER, DOWN, MUTED, TEXT, UP
from .widgets.base import Badge
from .workers import FnWorker, WarmupWorker
from ..services.scheduler import HourlyEngine


WORKSPACES = {
    "research": {
        "label": "研究台",
        "sub": "结论优先 · 六维研判",
        "pages": [("总览", "dashboard"), ("个股研究", "research"), ("每日荐股", "recommend"),
                  ("周期预测", "forecast"), ("宏观人文", "macro"), ("组合风控", "portfolio"),
                  ("研判报告", "report")],
    },
    "terminal": {
        "label": "专业终端",
        "sub": "K 线 · 筹码 · 公告事件",
        "pages": [("K 线终端", "terminal"), ("公告事件", "events")],
    },
}
SYSTEM_PAGES = [("插件生态", "plugins"), ("设置", "settings")]
PAGE_ORDER = ["dashboard", "research", "recommend", "forecast", "macro", "portfolio",
              "report", "terminal", "events", "plugins", "settings"]


class MainWindow(QMainWindow):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.market = ctx.market
        self.settings = ctx.settings
        self.setWindowTitle(f"观澜 QuantDesk {APP_VERSION} · A股多维研判终端")
        self.resize(1560, 980)
        self.setMinimumSize(1280, 820)
        self._workers = []
        self._shutting_down = False
        self._build()
        self._engine = HourlyEngine(self.market, self.settings)
        self._engine.cycle_started.connect(self._cycle_started)
        self._engine.cycle_log.connect(self._cycle_log)
        self._engine.cycle_done.connect(self._cycle_done)
        self._engine.cycle_failed.connect(self._cycle_failed)
        self._engine.start()
        QTimer.singleShot(120, self._boot)

    # ------------------------------------------------------------------ 布局
    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 侧栏
        side = QFrame()
        side.setFixedWidth(212)
        side.setStyleSheet(f"QFrame{{background:{BG2}; border-right:1px solid {BORDER};}}")
        sl = QVBoxLayout(side)
        sl.setContentsMargins(16, 18, 16, 14)
        sl.setSpacing(6)
        brand = QLabel("观澜")
        brand.setStyleSheet(f"color:{ACCENT}; font-size:27px; font-weight:700; letter-spacing:3px;")
        sl.addWidget(brand)
        sub = QLabel("QUANTDESK  ·  A-SHARE")
        sub.setStyleSheet(f"color:{MUTED}; font-size:9px; letter-spacing:1px;")
        sl.addWidget(sub)
        sl.addSpacing(9)

        # 双工作区切换
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        ml = QHBoxLayout()
        ml.setSpacing(4)
        self.mode_buttons = []
        for i, key in enumerate(("research", "terminal")):
            b = QPushButton(WORKSPACES[key]["label"])
            b.setObjectName("ModeTab")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.mode_group.addButton(b, i)
            self.mode_buttons.append(b)
            ml.addWidget(b)
        self.mode_buttons[0].setChecked(True)
        self.mode_group.idClicked.connect(self._workspace_clicked)
        sl.addLayout(ml)
        self.workspace_sub = QLabel(WORKSPACES["research"]["sub"])
        self.workspace_sub.setStyleSheet(f"color:{MUTED}; font-size:9px; padding:1px 1px 4px 1px;")
        sl.addWidget(self.workspace_sub)
        self.phase_badge = Badge("--", "neutral")
        self.phase_badge.setMaximumWidth(96)
        sl.addWidget(self.phase_badge)
        sl.addSpacing(2)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_group.idClicked.connect(self._nav_clicked)
        self.nav_layout = QVBoxLayout()
        self.nav_layout.setSpacing(4)
        sl.addLayout(self.nav_layout)
        sl.addStretch(1)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{BORDER};")
        sl.addWidget(line)
        self.side_stat = QLabel("插件 -- · 数据库 --")
        self.side_stat.setWordWrap(True)
        self.side_stat.setStyleSheet(f"color:{MUTED}; font-size:9px;")
        sl.addWidget(self.side_stat)
        foot = QLabel("本地计算 · 公开数据 · 非投资建议")
        foot.setWordWrap(True)
        foot.setStyleSheet(f"color:{MUTED}; font-size:9px;")
        sl.addWidget(foot)
        sign = QLabel("@烬羽鱼")
        sign.setToolTip("责任归属：@烬羽鱼 · 软件设计与实现")
        sign.setStyleSheet(f"color:{ACCENT}; font-size:11px; font-weight:600; letter-spacing:1px; padding-top:3px;")
        sl.addWidget(sign)
        lay.addWidget(side)

        # 右侧
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(14, 10, 14, 8)
        rl.setSpacing(9)
        top = QHBoxLayout()
        top.setSpacing(10)
        self.title = QLabel("研究台")
        self.title.setStyleSheet(f"color:{TEXT}; font-size:18px; font-weight:700;")
        top.addWidget(self.title)
        tag = QLabel("技术 / 资金 / 估值 / 情绪 / 宏观 / 人文")
        tag.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        top.addWidget(tag)
        top.addStretch(1)
        self.clock = QLabel("")
        self.clock.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        top.addWidget(self.clock)
        self.manual = QPushButton("立即校准")
        self.manual.setObjectName("Primary")
        self.manual.clicked.connect(self._manual_cycle)
        top.addWidget(self.manual)
        rl.addLayout(top)

        self.stack = QStackedWidget()
        self.dashboard = DashboardPage(self.ctx)
        self.research = ResearchPage(self.ctx)
        self.recommend = RecommendPage(self.ctx)
        self.forecast = ForecastPage(self.ctx)
        self.macro = MacroPage(self.ctx)
        self.portfolio = PortfolioPage(self.ctx)
        self.report = ReportPage(self.ctx)
        self.terminal = TerminalPage(self.ctx)
        self.events = EventsPage(self.ctx)
        self.plugins = PluginsPage(self.ctx)
        self.settings_page = SettingsPage(self.ctx)
        self.pages = {
            "dashboard": self.dashboard, "research": self.research, "recommend": self.recommend,
            "forecast": self.forecast, "macro": self.macro, "portfolio": self.portfolio,
            "report": self.report, "terminal": self.terminal, "events": self.events,
            "plugins": self.plugins, "settings": self.settings_page,
        }
        self.page_index = {}
        for key in PAGE_ORDER:
            self.page_index[key] = self.stack.addWidget(self.pages[key])
        rl.addWidget(self.stack, 1)
        lay.addWidget(right, 1)

        self._workspace = "research"
        self._active_key = ""
        self._last_page = {"research": "dashboard", "terminal": "terminal"}
        self._build_nav()

        self.dashboard.symbol_selected.connect(self._open_symbol)
        self.dashboard.calibrate_requested.connect(self._manual_cycle)
        self.research.analysis_ready.connect(self._apply_result)
        self.recommend.symbol_selected.connect(self._open_symbol)
        self.terminal.analysis_ready.connect(self._apply_result)
        self.settings_page.settings_changed.connect(self._settings_changed)

        bar = QStatusBar()
        bar.setSizeGripEnabled(False)
        bar.setStyleSheet(f"QStatusBar{{background:{BG2}; color:{MUTED}; border-top:1px solid {BORDER};"
                          "font-size:10px;}}")
        self.setStatusBar(bar)
        self.st_src = QLabel("数据源：东方财富 / 腾讯 / 新浪（优先级回退）")
        self.st_src.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        self.st_cycle = QLabel("校准：等待首轮")
        self.st_cycle.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        self.st_dis = QLabel("仅供研究，不构成投资建议")
        self.st_dis.setStyleSheet(f"color:{ACCENT}; font-size:10px;")
        bar.addWidget(self.st_src)
        bar.addPermanentWidget(self.st_cycle)
        bar.addPermanentWidget(self.st_dis)

        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._tick)
        self.clock_timer.start(1000)
        self._tick()

        self.quote_timer = QTimer(self)
        self.quote_timer.timeout.connect(self._ticker)
        self.quote_timer.start(max(10, int(self.settings.get("quote_refresh_sec", 20))) * 1000)

    # ------------------------------------------------------------------ 启动
    def _boot(self):
        # 先用本地 quotes 把自选池名称/现价铺出来，联网上下文完成后再补指标。
        self.dashboard.refresh_table()
        self._ctx_worker = FnWorker(lambda: self.market.market_context(force=False), "boot-context")
        self._ctx_worker.done.connect(self._ctx_ok)
        self._ctx_worker.failed.connect(self._ctx_fail)
        self._ctx_worker.start()
        self._workers.append(self._ctx_worker)

        if os.environ.get("GUANLAN_SKIP_WARMUP") == "1":
            return

        self._warm = WarmupWorker(self.market)
        self._warm.one_done.connect(self._one_done)
        self._warm.progress.connect(lambda s: self.st_cycle.setText(s))
        self._warm.finished_all.connect(self._warm_done)
        self._warm.failed.connect(self._warm_fail)
        self._warm.start()

    def _ctx_ok(self, ctx):
        self.dashboard.update_context(ctx)
        self.macro.update_context(ctx)
        self.st_src.setText(f"数据源：东方财富/腾讯/新浪 · 宏观官方 · 更新 {ctx.get('updated', '')}")
        self.phase_badge.setText(market_phase()[0])
        self.phase_badge.set_tone("up" if market_phase()[1] else "neutral")
        self._refresh_side()

    def _ctx_fail(self, e):
        self.st_src.setText(f"市场上下文失败：{e}")
        self.phase_badge.setText("数据异常")
        self.phase_badge.set_tone("down")

    def _one_done(self, r):
        self.dashboard.update_analysis(r)
        self.st_cycle.setText(f"预热完成 {r['name']}（{r['symbol']}）· 六维 {r['fused']['total']:+.1f}")

    def _warm_done(self, payload):
        stats = payload.get("stats", {})
        errors = payload.get("errors", [])
        msg = (f"{datetime.now().strftime('%H:%M:%S')} · 启动预热 {stats.get('n', 0)} 只，"
               f"耗时 {stats.get('elapsed', 0)}s，平均六维 {stats.get('avg_score', 0):+.1f}")
        self.dashboard.set_cycle(msg, stats)
        self.st_cycle.setText(f"校准：{stats.get('n', 0)} 只 · {stats.get('elapsed', 0)}s")
        if errors:
            self.dashboard.append_log("预热异常：" + "；".join(errors[:3]))
        self.macro.refresh(force=False)
        self._refresh_side()

    def _warm_fail(self, e):
        self.st_cycle.setText(f"预热失败：{e}")
        self.dashboard.append_log(f"预热失败：{e}")

    # ------------------------------------------------------------------ 导航
    def _build_nav(self):
        while self.nav_layout.count():
            item = self.nav_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if self.nav_group is not None:
            self.nav_group.deleteLater()
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_group.idClicked.connect(self._nav_clicked)
        self.nav_buttons = []
        self._nav_keys = []

        entries = WORKSPACES[self._workspace]["pages"]
        for i, (label, key) in enumerate(entries):
            b = QPushButton(f"{i + 1:02d}   {label}")
            b.setObjectName("Nav")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.nav_group.addButton(b, i)
            self.nav_buttons.append(b)
            self._nav_keys.append(key)
            self.nav_layout.addWidget(b)

        gap = QLabel("系统")
        gap.setStyleSheet(f"color:{MUTED}; font-size:9px; letter-spacing:2px; padding:10px 2px 2px 2px;")
        self.nav_layout.addWidget(gap)
        base = len(entries)
        for j, (label, key) in enumerate(SYSTEM_PAGES):
            b = QPushButton(f"{base + j + 1:02d}   {label}")
            b.setObjectName("Nav")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.nav_group.addButton(b, base + j)
            self.nav_buttons.append(b)
            self._nav_keys.append(key)
            self.nav_layout.addWidget(b)

        target = self._last_page.get(self._workspace, entries[0][1])
        if target not in self._nav_keys:
            target = entries[0][1]
        self._go(target)

    def _workspace_clicked(self, idx: int):
        key = "research" if idx == 0 else "terminal"
        self._switch_workspace(key)

    def _switch_workspace(self, key: str):
        self._workspace = key
        self.mode_buttons[0].setChecked(key == "research")
        self.mode_buttons[1].setChecked(key == "terminal")
        self.workspace_sub.setText(WORKSPACES[key]["sub"])
        self.title.setText(WORKSPACES[key]["label"])
        self._build_nav()

    def _nav_clicked(self, idx: int):
        if 0 <= idx < len(self._nav_keys):
            self._go(self._nav_keys[idx])

    def _go(self, key: str):
        self._active_key = key
        self._last_page[self._workspace] = key
        idx = self.page_index.get(key, 0)
        self.stack.setCurrentIndex(idx)
        if key not in self._nav_keys:
            return
        btn_id = self._nav_keys.index(key)
        btn = self.nav_group.button(btn_id)
        if btn is not None:
            btn.setChecked(True)

        if key == "recommend":
            self.recommend.ensure_loaded()
        elif key == "forecast":
            self.forecast.reload_combo()
            if not self.forecast._symbol and self.forecast.watch.count():
                self.forecast.load(self.forecast.watch.itemData(0), force=False)
        elif key == "report":
            self.report.reload_combo()
            if not self.report._data and self.report.combo.count():
                self.report.generate()
        elif key == "macro" and (not self.macro._data or not self.macro._boards):
            self.macro.refresh(force=False)
        elif key == "portfolio":
            self.portfolio.refresh()
        elif key == "terminal":
            self.terminal.reload_watch_combo()
            if not self.terminal._symbol:
                sym = getattr(self.ctx, "active_symbol", "") or (
                    self.terminal.watch.itemData(0) if self.terminal.watch.count() else "")
                if sym:
                    self.terminal.load(sym, force=False)
        elif key == "events":
            self.events.ensure_loaded()
        elif key == "research":
            if not self.research._data:
                sym = getattr(self.ctx, "active_symbol", "") or (
                    self.settings.watchlist[0] if self.settings.watchlist else "")
                if sym:
                    self.research.load(sym, force=False)
        self._refresh_side()

    def _open_symbol(self, symbol: str):
        if self._workspace != "research":
            self._switch_workspace("research")
        self._go("research")
        self.research.load(symbol, force=True)

    def _apply_result(self, r: dict):
        symbol = r.get("symbol", "")
        if symbol:
            self.ctx.active_symbol = symbol
        if getattr(self.research, "_data", None) is not r:
            self.research.apply(r)
        if getattr(self.terminal, "_data", None) is not r:
            self.terminal.apply(r)
        if getattr(self.events, "_data", None) is not r:
            self.events.apply(r)
        if self.forecast._symbol == symbol:
            self.forecast.apply(r)
        if self.report._data and self.report._data.get("symbol") == symbol:
            self.report.apply_from(r)

    def _settings_changed(self):
        self.terminal.reload_watch_combo()
        self.forecast.reload_combo()
        self.report.reload_combo()
        self.quote_timer.setInterval(max(10, int(self.settings.get("quote_refresh_sec", 20))) * 1000)
        self._refresh_side()

    # ------------------------------------------------------------------ 校准
    def _manual_cycle(self):
        if self._engine.isRunning():
            self._engine.request_cycle()
            self.manual.setText("校准中…")
            self.manual.setEnabled(False)
        else:
            self._engine.start()
            self._engine.request_cycle()

    def _cycle_started(self, msg):
        self.dashboard.append_log(msg)
        self.st_cycle.setText(msg)

    def _cycle_log(self, msg):
        self.dashboard.append_log(msg)

    def _cycle_done(self, payload):
        self.manual.setText("立即校准")
        self.manual.setEnabled(True)
        stats = payload.get("stats", {})
        self.dashboard.append_log(payload.get("message", "校准完成"))
        self.dashboard.set_cycle(payload.get("message", ""), stats)
        self.dashboard.refresh_table()
        self.macro.refresh(force=False)
        for r in payload.get("results", []):
            if self.forecast._symbol == r["symbol"]:
                self.forecast.apply(r)
            if self.research._data and self.research._data.get("symbol") == r["symbol"]:
                self._apply_result(r)
        self.st_cycle.setText(f"校准：{stats.get('n', 0)} 只 · {stats.get('elapsed', 0)}s · "
                              f"平均 {stats.get('avg_score', 0):+.1f}")
        self._refresh_side()

    def _cycle_failed(self, e):
        self.manual.setText("立即校准")
        self.manual.setEnabled(True)
        self.dashboard.append_log(f"校准失败：{e}")
        self.st_cycle.setText(f"校准失败：{e}")

    # ------------------------------------------------------------------ 报价轮询
    def _ticker(self):
        if getattr(self, "_tick_worker", None) is not None and self._tick_worker.isRunning():
            return
        if getattr(self, "_warm", None) is not None and self._warm.isRunning():
            return
        symbols = [s for s, _, _ in INDICES] + self.settings.watchlist
        def task():
            return self.market.refresh_quotes(symbols)
        w = FnWorker(task, "quote-tick")
        w.done.connect(self._tick_done)
        w.failed.connect(lambda e: None)
        w.start()
        self._tick_worker = w

    def _tick_done(self, quotes):
        self.dashboard.update_quotes(quotes)

    # ------------------------------------------------------------------ 其它
    def _tick(self):
        now = datetime.now()
        week = "一二三四五六日"[now.weekday()]
        self.clock.setText(now.strftime("%Y-%m-%d  %H:%M:%S") + f"  周{week}")
        phase, is_open = market_phase()
        self.phase_badge.setText(phase)
        tone = "up" if is_open else "neutral"
        if self.phase_badge.objectName() != ("BadgeUp" if tone == "up" else "BadgeNeutral"):
            self.phase_badge.set_tone(tone)

    def _refresh_side(self):
        s = self.ctx.registry.summary()
        try:
            db = self.ctx.store.stats()
            db_txt = f"{db.get('db_mb', 0):.1f}MB"
        except Exception:
            db_txt = "--"
        self.side_stat.setText(f"插件 {s['loaded']}/{s['total']} · 能力 {s['capabilities']} · "
                               f"DB {db_txt}")
        if hasattr(self, "st_src"):
            self.st_src.setToolTip(
                self.market._ctx_cache[1].get("updated", "") if self.market._ctx_cache[1] else "")

    def shutdown(self):
        """非阻塞地停止所有后台任务，避免关窗时卡死或析构运行中的 QThread。"""
        if self._shutting_down:
            return
        self._shutting_down = True
        for timer in (getattr(self, "clock_timer", None), getattr(self, "quote_timer", None)):
            try:
                if timer is not None:
                    timer.stop()
            except Exception:
                pass
        if getattr(self, "_warm", None) is not None:
            self._warm.stop()
        try:
            self._engine.stop()
        except Exception:
            pass
        # 页面后台线程只请求中断，不在 UI 线程里长时间 wait；进程退出由入口统一兜底。
        for page in getattr(self, "pages", {}).values():
            for attr in ("_worker", "_search_worker"):
                w = getattr(page, attr, None)
                try:
                    if w is not None and w.isRunning():
                        w.requestInterruption()
                except Exception:
                    pass

    def closeEvent(self, event: QCloseEvent):
        self.shutdown()
        self.hide()
        event.accept()
