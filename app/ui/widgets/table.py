"""表格辅助。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QTableWidget,
                               QTableWidgetItem)

from ..theme import MUTED, TEXT


def make_table(headers: list[str], widths: list[int] | None = None, parent=None) -> QTableWidget:
    t = QTableWidget(0, len(headers), parent)
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setAlternatingRowColors(True)
    t.setShowGrid(False)
    t.setWordWrap(False)
    h = t.horizontalHeader()
    h.setHighlightSections(False)
    h.setSectionResizeMode(QHeaderView.Interactive)
    h.setStretchLastSection(True)
    if widths:
        for i, w in enumerate(widths[:len(headers)]):
            t.setColumnWidth(i, w)
    t.setMinimumHeight(100)
    return t


def set_cell(t: QTableWidget, row: int, col: int, text: str, color: str | None = None,
             bold: bool = False, align_right: bool = False, tooltip: str | None = None):
    item = t.item(row, col)
    if item is None:
        item = QTableWidgetItem("")
        t.setItem(row, col, item)
    item.setText(str(text))
    if color:
        item.setForeground(QColor(color))
    if bold:
        f = item.font()
        f.setBold(True)
        item.setFont(f)
    item.setTextAlignment((Qt.AlignRight if align_right else Qt.AlignLeft) | Qt.AlignVCenter)
    if tooltip:
        item.setToolTip(tooltip)
    return item


def prepare_rows(t: QTableWidget, n: int):
    if t.rowCount() < n:
        t.setRowCount(n)
    elif t.rowCount() > n:
        t.setRowCount(n)


def clear_table(t: QTableWidget):
    t.setRowCount(0)
