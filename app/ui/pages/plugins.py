"""插件：清单、能力、优先级回退、冲突与健康检查。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ...util import LOG_RING
from ..theme import ACCENT, ACCENT2, BORDER, DOWN, MUTED, TEXT, UP
from ..widgets.base import Badge, Card, MetricCard
from ..workers import FnWorker


class PluginCard(Card):
    def __init__(self, m, health: dict | None, parent=None):
        super().__init__(m.name, m.kind_label, parent=parent)
        self.m = m
        self.body.setSpacing(4)
        version = QLabel(f"{m.id} · v{m.version} · priority {m.priority}")
        version.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        self.add(version)
        desc = QLabel(m.description or "（无描述）")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color:{TEXT}; font-size:11px;")
        self.add(desc)
        caps = " ".join(f"#{c}" for c in m.capabilities[:6])
        cap_label = QLabel(caps or "无能力声明")
        cap_label.setWordWrap(True)
        cap_label.setStyleSheet(f"color:{ACCENT2}; font-size:9px;")
        self.add(cap_label)
        auth = QLabel(f"authority: {m.authority} · endpoints: {len(m.endpoints)}")
        auth.setStyleSheet(f"color:{MUTED}; font-size:9px;")
        self.add(auth)
        row = QHBoxLayout()
        self.badge = Badge("未检查", "neutral")
        row.addWidget(self.badge)
        if m.load_error:
            self.badge.setText("加载失败")
            self.badge.set_tone("up")
            err = QLabel(m.load_error)
            err.setWordWrap(True)
            err.setStyleSheet(f"color:{DOWN}; font-size:9px;")
            self.add(err)
        elif health:
            self.set_health(health)
        else:
            self.badge.setText("已加载")
            self.badge.set_tone("down")
        row.addStretch(1)
        self.lat = QLabel("")
        self.lat.setStyleSheet(f"color:{MUTED}; font-size:9px;")
        row.addWidget(self.lat)
        self.add_layout(row)

    def set_health(self, h: dict):
        ok = bool(h.get("ok"))
        self.badge.setText("健康" if ok else "异常")
        self.badge.set_tone("down" if ok else "up")
        self.lat.setText(f"{h.get('latency', 0):.0f} ms · {str(h.get('message', ''))[:24]}")


class PluginsPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.registry = ctx.registry
        self.store = ctx.store
        self._worker = None
        self._cards = {}
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 3, 0, 0)
        outer.setSpacing(9)
        head = QHBoxLayout()
        t = QLabel("插件生态")
        t.setMinimumHeight(21)
        t.setStyleSheet(f"color:{TEXT}; font-size:14px; font-weight:600;")
        head.addWidget(t)
        head.addStretch(1)
        self.sum_label = QLabel("")
        self.sum_label.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        head.addWidget(self.sum_label)
        btn = QPushButton("运行健康检查")
        btn.clicked.connect(self.check)
        head.addWidget(btn)
        outer.addLayout(head)

        self.conflict = QLabel("")
        self.conflict.setWordWrap(True)
        self.conflict.setStyleSheet(
            f"color:{ACCENT}; background:#FBF6EC; border:1px solid #EAD9BF;"
            "border-radius:6px; padding:7px; font-size:10px;")
        outer.addWidget(self.conflict)

        self.sum_cards = {}
        row = QHBoxLayout()
        for key, label in (("total", "清单总数"), ("loaded", "加载成功"),
                           ("caps", "能力条目"), ("conflicts", "能力重叠")):
            c = MetricCard(label)
            self.sum_cards[key] = c
            row.addWidget(c)
        outer.addLayout(row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        host = QWidget()
        host.setStyleSheet("background:transparent;")
        self.grid = QGridLayout(host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(8)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)
        self._host = host

        log_card = Card("运行日志（尾部）", "内存环形缓冲，最多 400 行")
        log_card.setFixedHeight(190)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(400)
        self.logs.setStyleSheet("QPlainTextEdit{font-family:Consolas,monospace;font-size:10px;}")
        log_card.add(self.logs, 1)
        outer.addWidget(log_card, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tail)
        self.timer.start(2000)

        self._populate()

    def _populate(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        health = {h["plugin"]: h for h in self.store.plugin_health()}
        manifests = list(self.registry.manifests.values())
        for i, m in enumerate(manifests):
            card = PluginCard(m, health.get(m.id))
            self._cards[m.id] = card
            self.grid.addWidget(card, i // 2, i % 2)
        self.summary()

    def summary(self):
        s = self.registry.summary()
        self.sum_cards["total"].set(str(s["total"]))
        self.sum_cards["loaded"].set(str(s["loaded"]), ACCENT2 if s["failing"] == 0 else DOWN)
        self.sum_cards["caps"].set(str(s["capabilities"]))
        self.sum_cards["conflicts"].set(str(s["conflicts"]), ACCENT if s["conflicts"] else None)
        self.sum_label.setText(f"API guanlan-1 · {s['loaded']}/{s['total']} 已加载 · "
                               f"{s['capabilities']} 项能力 · {s['conflicts']} 处重叠")
        if self.registry.conflicts:
            self.conflict.setText("冲突与回退：" + "；".join(self.registry.conflicts))
        else:
            self.conflict.setText("未检测到插件 ID 冲突或能力重叠。")

    def check(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self.conflict.setText("正在逐个检查插件健康状态…")
        w = FnWorker(lambda: self.registry.health_all(), "plugin-health")
        w.done.connect(self._checked)
        w.failed.connect(lambda e: self.conflict.setText(f"健康检查失败：{e}"))
        w.start()
        self._worker = w

    def _checked(self, results):
        for item in results:
            card = self._cards.get(item["id"])
            if card:
                card.set_health(item)
        self.summary()
        bad = [r for r in results if not r["ok"]]
        self.conflict.setText(("健康检查完成，异常：" + "；".join(f"{r['name']}({r['message']})" for r in bad))
                              if bad else "健康检查完成，全部插件可用。")

    def _tail(self):
        lines = LOG_RING.lines()
        self.logs.setPlainText("\n".join(lines[-120:]))
        self.logs.verticalScrollBar().setValue(self.logs.verticalScrollBar().maximum())
