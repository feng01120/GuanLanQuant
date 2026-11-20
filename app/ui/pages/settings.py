"""设置：自选池、运行参数、缓存与数据库信息。"""
from __future__ import annotations

import shutil

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
                               QWidget)

from ...config import CACHE_DIR
from ..theme import BORDER, DOWN, MUTED, TEXT, UP
from ..widgets.base import Card


class SettingsPage(QWidget):
    settings_changed = Signal()

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.market = ctx.market
        self.settings = ctx.market.settings
        self._build()
        self.reload_watch()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 3, 0, 0)
        outer.setSpacing(9)
        head = QHBoxLayout()
        t = QLabel("设置")
        t.setMinimumHeight(21)
        t.setStyleSheet(f"color:{TEXT}; font-size:14px; font-weight:600;")
        head.addWidget(t)
        head.addStretch(1)
        self.hint = QLabel("修改立即写入 data/settings.json")
        self.hint.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        head.addWidget(self.hint)
        outer.addLayout(head)

        mid = QHBoxLayout()
        mid.setSpacing(9)
        watch_card = Card("自选池", "总览、预测、研报共用")
        self.list = QListWidget()
        self.list.setMinimumHeight(220)
        watch_card.add(self.list, 1)
        add_row = QHBoxLayout()
        self.symbol = QLineEdit()
        self.symbol.setPlaceholderText("6 位代码")
        self.symbol.setMaximumWidth(120)
        self.name = QLineEdit()
        self.name.setPlaceholderText("名称（可空，自动获取）")
        btn_add = QPushButton("添加")
        btn_add.clicked.connect(self._add)
        btn_del = QPushButton("移除选中")
        btn_del.clicked.connect(self._remove)
        add_row.addWidget(self.symbol)
        add_row.addWidget(self.name)
        add_row.addWidget(btn_add)
        add_row.addWidget(btn_del)
        watch_card.add_layout(add_row)
        tip = QLabel("提示：自选池扩充会增加每小时校准耗时，建议不超过 20 只。")
        tip.setStyleSheet(f"color:{MUTED}; font-size:9px;")
        watch_card.add(tip)
        mid.addWidget(watch_card, 1)

        param_card = Card("运行参数", "保存后下一轮校准生效")
        form = QVBoxLayout()
        form.setSpacing(8)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("校准间隔（分钟）"))
        self.interval = QSpinBox()
        self.interval.setRange(30, 240)
        self.interval.setValue(max(30, int(self.settings.get("hourly_interval_sec", 3600)) // 60))
        row1.addWidget(self.interval)
        row1.addStretch(1)
        form.addLayout(row1)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("历史 K 线天数"))
        self.history = QSpinBox()
        self.history.setRange(300, 1500)
        self.history.setValue(int(self.settings.get("history_days", 900)))
        row2.addWidget(self.history)
        row2.addStretch(1)
        form.addLayout(row2)
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("单票仓位上限"))
        self.maxpos = QDoubleSpinBox()
        self.maxpos.setRange(5.0, 50.0)
        self.maxpos.setDecimals(0)
        self.maxpos.setSuffix("%")
        self.maxpos.setValue(float(self.settings.get("max_position_pct", 0.2)) * 100)
        row3.addWidget(self.maxpos)
        row3.addStretch(1)
        form.addLayout(row3)
        self.enable_macro = QCheckBox("宏观因子参与评分")
        self.enable_macro.setChecked(bool(self.settings.get("enable_macro", True)))
        self.enable_hum = QCheckBox("人文日历参与评分")
        self.enable_hum.setChecked(bool(self.settings.get("enable_humanities", True)))
        form.addWidget(self.enable_macro)
        form.addWidget(self.enable_hum)
        save = QPushButton("保存参数")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        form.addWidget(save)
        form.addStretch(1)
        param_card.add_layout(form)
        mid.addWidget(param_card, 1)
        outer.addLayout(mid)
        arch = Card("运行机理", "manifest → 能力注册 → 优先级回退 → 冲突检测 → 健康检查")
        txt = QLabel(
            "插件以 manifest.json 声明 id、版本、API（guanlan-1）、kind、capabilities、priority 与 authority；"
            "内核启动时扫描 plugins/*/manifest.json，按能力建立索引，同一能力按 priority 从小到大回退调用。"
            "同能力多插件会在「插件」页标注为能力重叠而非错误；健康检查逐个记录可用性与延迟。<br>"
            "每小时校准：刷新行情与公告 → 重算技术/资金/估值/情绪/宏观/人文六维 → 重估短周期集成权重 → "
            "重采样长周期蒙特卡洛 → 落库并刷新界面。非交易时段使用最近收盘数据，仍按间隔运行。")
        txt.setWordWrap(True)
        txt.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        arch.add(txt)
        outer.addWidget(arch)
        outer.addStretch(1)

        data_card = Card("数据与缓存", "SQLite（WAL）· 磁盘缓存")
        self.db_label = QLabel("读取中…")
        self.db_label.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        data_card.add(self.db_label)
        row = QHBoxLayout()
        btn_stats = QPushButton("刷新统计")
        btn_stats.clicked.connect(self.reload_stats)
        btn_cache = QPushButton("清理过期缓存")
        btn_cache.clicked.connect(self._clear_cache)
        row.addWidget(btn_stats)
        row.addWidget(btn_cache)
        row.addStretch(1)
        data_card.add_layout(row)
        outer.addWidget(data_card)

        disc = QLabel(
            "免责声明：观澜 QuantDesk 为学习与研究工具。所有评分、概率与交易计划均为统计输出，"
            "不构成投资建议，不承诺收益。数据来自公开接口，可能存在延迟、缺失或口径差异；"
            "A 股存在涨跌停、停牌、复权与流动性约束，历史回测无法完全复现。"
            "软件设计与实现责任归属：@烬羽鱼。")
        disc.setWordWrap(True)
        disc.setStyleSheet(f"color:{MUTED}; font-size:10px; border:1px solid {BORDER};"
                           "border-radius:6px; padding:8px;")
        outer.addWidget(disc)
        self.reload_stats()

    # ------------------------------------------------------------------
    def reload_watch(self):
        names = self.settings.watchlist_names
        self.list.clear()
        for s in self.settings.watchlist:
            self.list.addItem(f"{names.get(s, '')}  {s}")

    def _add(self):
        s = self.symbol.text().strip()
        if not s.isdigit() or len(s) != 6:
            QMessageBox.warning(self, "代码无效", "请输入 6 位 A 股/ETF 代码。")
            return
        name = self.name.text().strip()
        self.market.add_watch(s, name)
        # 不要在这里同步跑整池校准；一次 add 会阻塞 UI 几十秒。
        # 报价由后台定时器补，研判交给下一轮校准。
        self.symbol.clear()
        self.name.clear()
        self.reload_watch()
        self.settings_changed.emit()
        self.hint.setText(f"已加入自选：{s}；下一轮校准会分析")

    def _remove(self):
        row = self.list.currentRow()
        wl = self.settings.watchlist
        if row < 0 or row >= len(wl):
            return
        s = wl[row]
        if len(wl) <= 1:
            QMessageBox.information(self, "至少保留一只", "自选池不能为空。")
            return
        self.market.remove_watch(s)
        self.reload_watch()
        self.settings_changed.emit()
        self.hint.setText(f"已移除：{s}")

    def _save(self):
        self.settings.update({
            "hourly_interval_sec": int(self.interval.value()) * 60,
            "history_days": int(self.history.value()),
            "max_position_pct": float(self.maxpos.value()) / 100,
            "enable_macro": self.enable_macro.isChecked(),
            "enable_humanities": self.enable_hum.isChecked(),
        })
        self.hint.setText("参数已保存，将在下一轮校准生效。")
        self.settings_changed.emit()

    def reload_stats(self):
        try:
            st = self.market.store.stats()
            size = st.get("db_mb", 0)
            self.db_label.setText(
                f"数据库 guanlan.db · {size:.2f} MB · K线 {st.get('bars', 0)} 行 · "
                f"预测 {st.get('forecasts', 0)} 条 · 情绪 {st.get('sentiment', 0)} 次 · "
                f"组合 {st.get('portfolio', 0)} 条")
        except Exception as e:  # noqa: BLE001
            self.db_label.setText(f"统计失败：{e}")

    def _clear_cache(self):
        files = list(CACHE_DIR.glob("*")) if CACHE_DIR.exists() else []
        if not files:
            self.hint.setText("缓存已为空。")
            return
        total = sum(f.stat().st_size for f in files if f.is_file())
        ok = QMessageBox.question(
            self, "清理缓存",
            f"将删除 data/cache 下 {len(files)} 个缓存文件（{total / 1024 / 1024:.1f} MB）。\n"
            "行情会重新向公开接口请求，数据库不受影响。继续？")
        if ok != QMessageBox.StandardButton.Yes:
            return
        for f in files:
            try:
                if f.is_dir():
                    shutil.rmtree(f, ignore_errors=True)
                else:
                    f.unlink()
            except Exception:
                pass
        self.hint.setText("缓存已清理。")
        self.reload_stats()
