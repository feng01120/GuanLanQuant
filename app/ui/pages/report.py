"""研报：预览、导出 Markdown / HTML / PDF。"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QMarginsF, Qt
from PySide6.QtGui import QFont, QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QTextBrowser, QVBoxLayout, QWidget)

from ...config import REPORT_DIR
from ...research import report
from ..theme import ACCENT, BORDER, MUTED, TEXT
from ..widgets.base import Card
from ..workers import FnWorker


class ReportPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.market = ctx.market
        self._worker = None
        self._data = None
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 3, 0, 0)
        outer.setSpacing(9)
        head = QHBoxLayout()
        t = QLabel("研报中心")
        t.setMinimumHeight(21)
        t.setStyleSheet(f"color:{TEXT}; font-size:14px; font-weight:600;")
        head.addWidget(t)
        self.combo = QComboBox()
        self.combo.setMinimumWidth(190)
        head.addWidget(self.combo)
        self.gen = QPushButton("生成 / 刷新")
        self.gen.clicked.connect(self.generate)
        head.addWidget(self.gen)
        self.md = QPushButton("导出 Markdown")
        self.md.clicked.connect(self.export_md)
        head.addWidget(self.md)
        self.html = QPushButton("导出 HTML")
        self.html.clicked.connect(self.export_html)
        head.addWidget(self.html)
        self.pdf = QPushButton("导出 PDF")
        self.pdf.clicked.connect(self.export_pdf)
        head.addWidget(self.pdf)
        head.addStretch(1)
        self.hint = QLabel("报告保存到 reports/，内容仅用于研究")
        self.hint.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        head.addWidget(self.hint)
        outer.addLayout(head)

        card = Card("报告预览", "浅色版式，便于打印")
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(True)
        self.preview.setFont(QFont("Microsoft YaHei UI", 10))
        self.preview.setStyleSheet(
            f"QTextBrowser{{background:#FBFBF8;color:#1C2833;border:1px solid {BORDER};"
            "border-radius:6px;padding:4px;}}")
        card.add(self.preview, 1)
        outer.addWidget(card, 1)

    def reload_combo(self):
        names = self.market.settings.watchlist_names
        self.combo.blockSignals(True)
        self.combo.clear()
        for s in self.market.settings.watchlist:
            self.combo.addItem(f"{names.get(s, s)}  {s}", s)
        self.combo.blockSignals(False)

    def generate(self):
        s = self.combo.currentData()
        if not s:
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self.gen.setEnabled(False)
        self.hint.setText("正在生成…")
        w = FnWorker(lambda: self.market.analyze(s, force=False, persist=True), f"report-{s}")
        w.done.connect(self._done)
        w.failed.connect(self._fail)
        w.start()
        self._worker = w

    def _done(self, r):
        self.gen.setEnabled(True)
        self.apply_from(r)

    def apply_from(self, r):
        self._data = r
        if self.combo.count() == 0:
            self.reload_combo()
        idx = self.combo.findData(r.get("symbol"))
        if idx >= 0:
            self.combo.blockSignals(True)
            self.combo.setCurrentIndex(idx)
            self.combo.blockSignals(False)
        self.hint.setText(f"{r['name']}（{r['symbol']}）· 生成于 {r['research']['generated_at']}")
        self.preview.setHtml(report.build_html(r))

    def _fail(self, e):
        self.gen.setEnabled(True)
        self.hint.setText(f"失败：{e}")
        QMessageBox.warning(self, "生成失败", str(e))

    def show_for(self, symbol: str):
        idx = self.combo.findData(symbol)
        if idx >= 0:
            self.combo.setCurrentIndex(idx)
            self.generate()

    # ------------------------------------------------------------------
    def _stem(self) -> tuple[str, str]:
        r = self._data or {}
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        return f"观澜研报-{r.get('name', '标的')}{r.get('symbol', '')}-{stamp}", stamp

    def export_md(self):
        if not self._data:
            self.generate()
            return
        stem, _ = self._stem()
        path, _ = QFileDialog.getSaveFileName(self, "导出 Markdown", str(REPORT_DIR / f"{stem}.md"),
                                              "Markdown (*.md)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(report.build_markdown(self._data))
        self.hint.setText(f"已导出 {path}")

    def export_html(self):
        if not self._data:
            self.generate()
            return
        stem, _ = self._stem()
        path, _ = QFileDialog.getSaveFileName(self, "导出 HTML", str(REPORT_DIR / f"{stem}.html"),
                                              "HTML (*.html)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(report.build_html(self._data))
        self.hint.setText(f"已导出 {path}")

    def export_pdf(self):
        if not self._data:
            self.generate()
            return
        stem, _ = self._stem()
        path, _ = QFileDialog.getSaveFileName(self, "导出 PDF", str(REPORT_DIR / f"{stem}.pdf"),
                                              "PDF (*.pdf)")
        if not path:
            return
        doc = QTextDocument()
        doc.setDefaultFont(QFont("Microsoft YaHei UI", 10))
        doc.setHtml(report.build_print_html(self._data))
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        printer.setPageMargins(QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)
        doc.print_(printer)
        self.hint.setText(f"已导出 {path}")
