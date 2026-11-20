"""基础 UI 组件：卡片、指标、徽章、评分条。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QFont
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout,
                               QWidget)

from ..theme import ACCENT, BORDER, DOWN, FLAT, MUTED, TEXT, UP


class Card(QFrame):
    def __init__(self, title: str = "", subtitle: str = "", right: QWidget | None = None,
                 parent=None, margins=(14, 12, 14, 13)):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAttribute(Qt.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*margins)
        outer.setSpacing(8)
        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        self.sub_label = QLabel(subtitle)
        self.sub_label.setObjectName("CardSub")
        if title:
            self.header.addWidget(self.title_label)
            if subtitle:
                self.header.addWidget(self.sub_label)
            self.header.addStretch(1)
            if right is not None:
                self.header.addWidget(right)
            outer.addLayout(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(6)
        self.body.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(self.body, 1)

    def add(self, w: QWidget, stretch: int = 0):
        self.body.addWidget(w, stretch)
        return w

    def add_layout(self, layout, stretch: int = 0):
        self.body.addLayout(layout, stretch)
        return layout


class MetricCard(QFrame):
    def __init__(self, label: str, value: str = "--", sub: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("MetricCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(13, 10, 13, 10)
        lay.setSpacing(1)
        self.label = QLabel(label)
        self.label.setObjectName("MetricLabel")
        self.value = QLabel(value)
        self.value.setObjectName("MetricValue")
        self.sub = QLabel(sub)
        self.sub.setObjectName("MetricSub")
        lay.addWidget(self.label)
        lay.addWidget(self.value)
        lay.addWidget(self.sub)
        lay.addStretch(1)

    def set(self, value: str, color: str | None = None, sub: str | None = None):
        self.value.setText(value)
        if color:
            self.value.setStyleSheet(f"color:{color};")
        if sub is not None:
            self.sub.setText(sub)


class Badge(QLabel):
    def __init__(self, text: str = "", tone: str = "neutral", parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.set_tone(tone)

    def set_tone(self, tone: str):
        names = {"up": "BadgeUp", "down": "BadgeDown", "gold": "BadgeGold", "neutral": "BadgeNeutral"}
        self.setObjectName(names.get(tone, "BadgeNeutral"))
        self.setStyleSheet("")  # 交给 QSS
        self.style().unpolish(self)
        self.style().polish(self)


class ScoreBar(QWidget):
    """-100 ~ 100 的居中评分条。"""

    def __init__(self, label: str = "", value: float = 0.0, parent=None):
        super().__init__(parent)
        self._label = label
        self._value = value
        self.setMinimumHeight(20)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_value(self, value: float, label: str | None = None):
        self._value = max(-100, min(100, float(value)))
        if label is not None:
            self._label = label
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        label_w = 58 if self._label else 0
        if self._label:
            p.setPen(QPen(QColor(MUTED)))
            p.setFont(QFont("Microsoft YaHei UI", 8))
            p.drawText(QRectF(0, 0, label_w - 6, h), Qt.AlignVCenter | Qt.AlignLeft, self._label)
        x0, x1 = label_w, w - 34
        mid = (x0 + x1) / 2
        p.setPen(QPen(QColor(BORDER), 1))
        p.drawLine(int(x0), int(h / 2), int(x1), int(h / 2))
        p.setPen(QPen(QColor("#CBD5E1"), 1))
        p.drawLine(int(mid), 3, int(mid), h - 3)
        half = (x1 - x0) / 2
        v = self._value
        color = QColor(UP if v > 0 else DOWN if v < 0 else FLAT)
        color.setAlpha(200)
        if abs(v) > 0.5:
            bar_w = abs(v) / 100 * half
            rect = QRectF(mid if v > 0 else mid - bar_w, h / 2 - 4, bar_w, 8)
            p.setBrush(color)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(rect, 4, 4)
        p.setPen(QPen(QColor(TEXT if abs(v) > 0.5 else MUTED)))
        p.setFont(QFont("Segoe UI", 9, QFont.Bold))
        p.drawText(QRectF(w - 34, 0, 34, h), Qt.AlignVCenter | Qt.AlignRight, f"{v:+.0f}")


class KeyValue(QWidget):
    def __init__(self, key: str, value: str = "", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 1, 0, 1)
        lay.setSpacing(6)
        self.k = QLabel(key)
        self.k.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        self.v = QLabel(value)
        self.v.setStyleSheet(f"color:{TEXT}; font-size:11px;")
        self.v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.k)
        lay.addStretch(1)
        lay.addWidget(self.v)

    def set(self, value: str, color: str | None = None):
        self.v.setText(value)
        if color:
            self.v.setStyleSheet(f"color:{color}; font-size:11px;")


def muted(text: str, size: int = 11) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(f"color:{MUTED}; font-size:{size}px;")
    lab.setWordWrap(True)
    return lab


def accent_line() -> QFrame:
    line = QFrame()
    line.setFixedHeight(2)
    line.setStyleSheet(f"background:{ACCENT}; border:none;")
    return line
