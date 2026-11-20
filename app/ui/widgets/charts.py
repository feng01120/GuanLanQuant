"""图表组件：K线、迷你走势、情绪仪表、雷达、蒙特卡洛扇形图、校准图。"""
from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath,
                           QPen, QPicture)
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from ..theme import ACCENT, ACCENT2, BG2, BLUE, BORDER, DOWN, FLAT, MUTED, PANEL2, PURPLE, TEXT, UP

pg.setConfigOptions(antialias=True, foreground=MUTED)


class Sparkline(QWidget):
    def __init__(self, values=None, color: str | None = None, parent=None):
        super().__init__(parent)
        self._values = list(values or [])
        self._color = color
        self.setMinimumHeight(30)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_data(self, values, color: str | None = None):
        self._values = [float(x) for x in (values or []) if x is not None and np.isfinite(x)]
        if color:
            self._color = color
        self.update()

    def paintEvent(self, event):
        if len(self._values) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        pad = 2
        vals = self._values
        lo, hi = min(vals), max(vals)
        if hi - lo < 1e-9:
            hi = lo + 1
        color = QColor(self._color or (UP if vals[-1] >= vals[0] else DOWN))
        path = QPainterPath()
        for i, v in enumerate(vals):
            x = pad + i / max(1, len(vals) - 1) * (w - 2 * pad)
            y = h - pad - (v - lo) / (hi - lo) * (h - 2 * pad)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        fill = QPainterPath(path)
        fill.lineTo(w - pad, h - pad)
        fill.lineTo(pad, h - pad)
        fill.closeSubpath()
        grad = QLinearGradient(0, 0, 0, h)
        c1 = QColor(color)
        c1.setAlpha(55)
        c2 = QColor(color)
        c2.setAlpha(0)
        grad.setColorAt(0, c1)
        grad.setColorAt(1, c2)
        p.fillPath(fill, QBrush(grad))
        p.setPen(QPen(color, 1.4))
        p.drawPath(path)


class Gauge(QWidget):
    """-100 ~ 100 的情绪/宏观温度计。"""

    def __init__(self, value: float = 0, label: str = "", parent=None):
        super().__init__(parent)
        self._value = value
        self._label = label
        self.setMinimumSize(170, 145)

    def set_value(self, value: float, label: str | None = None):
        self._value = max(-100, min(100, float(value)))
        if label is not None:
            self._label = label
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h * 0.58
        r = min(w * 0.42, h * 0.46)
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        p.setPen(QPen(QColor("#E3E8F0"), 9))
        p.drawArc(rect, 210 * 16, -240 * 16)
        v = self._value
        color = QColor(UP if v > 0 else DOWN if v < 0 else FLAT)
        if abs(v) > 1:
            span = -240 * (v / 100)
            p.setPen(QPen(color, 9))
            p.drawArc(rect, 210 * 16, int(span * 16))
        # 刻度
        p.setPen(QPen(QColor("#CBD5E1"), 1))
        for k in range(5):
            ang = math.radians(210 - 60 * k)
            x1 = cx + (r - 10) * math.cos(ang)
            y1 = cy - (r - 10) * math.sin(ang)
            x2 = cx + (r + 1) * math.cos(ang)
            y2 = cy - (r + 1) * math.sin(ang)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        # 指针
        ang = math.radians(210 - 240 * (v + 100) / 200)
        p.setPen(QPen(color, 2))
        p.drawLine(QPointF(cx, cy), QPointF(cx + r * 0.72 * math.cos(ang), cy - r * 0.72 * math.sin(ang)))
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), 5, 5)
        p.setPen(QPen(QColor(TEXT)))
        p.setFont(QFont("Segoe UI", 16, QFont.Bold))
        p.drawText(QRectF(cx - 60, cy + 12, 120, 28), Qt.AlignCenter, f"{v:+.0f}")
        p.setPen(QPen(QColor(MUTED)))
        p.setFont(QFont("Microsoft YaHei UI", 8))
        p.drawText(QRectF(cx - 80, cy + 40, 160, 20), Qt.AlignCenter, self._label)
        p.setFont(QFont("Microsoft YaHei UI", 7))
        p.drawText(QRectF(cx - r, cy + r * 0.45, 40, 18), Qt.AlignLeft, "冰点")
        p.drawText(QRectF(cx + r - 40, cy + r * 0.45, 40, 18), Qt.AlignRight, "亢奋")


class RadarChart(QWidget):
    def __init__(self, values: list[dict] | None = None, parent=None):
        super().__init__(parent)
        self._values = values or []
        self.setMinimumSize(240, 210)

    def set_data(self, values: list[dict]):
        self._values = values or []
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2 + 4
        r = min(w, h) * 0.30
        n = max(3, len(self._values))
        if not self._values:
            p.setPen(QPen(QColor(MUTED)))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "等待数据")
            return
        for ring in (0.25, 0.5, 0.75, 1.0):
            path = QPainterPath()
            for i in range(n):
                ang = math.pi / 2 + 2 * math.pi * i / n
                x = cx + r * ring * math.cos(ang)
                y = cy - r * ring * math.sin(ang)
                if i == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            path.closeSubpath()
            p.setPen(QPen(QColor("#DFE6EF"), 1))
            p.drawPath(path)
        p.setPen(QPen(QColor("#CFDAE7"), 1))
        for i in range(n):
            ang = math.pi / 2 + 2 * math.pi * i / n
            p.drawLine(QPointF(cx, cy), QPointF(cx + r * math.cos(ang), cy - r * math.sin(ang)))

        path = QPainterPath()
        for i, d in enumerate(self._values):
            score = max(-100, min(100, float(d.get("score", 0))))
            rr = r * (score + 100) / 200
            ang = math.pi / 2 + 2 * math.pi * i / n
            x = cx + rr * math.cos(ang)
            y = cy - rr * math.sin(ang)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        path.closeSubpath()
        fill = QColor(ACCENT)
        fill.setAlpha(58)
        p.setBrush(fill)
        p.setPen(QPen(QColor(ACCENT), 1.5))
        p.drawPath(path)
        for i, d in enumerate(self._values):
            ang = math.pi / 2 + 2 * math.pi * i / n
            score = float(d.get("score", 0))
            rr = r * (max(-100, min(100, score)) + 100) / 200
            p.setBrush(QColor(UP if score > 0 else DOWN if score < 0 else FLAT))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cx + rr * math.cos(ang), cy - rr * math.sin(ang)), 3, 3)
            lx = cx + (r + 26) * math.cos(ang)
            ly = cy - (r + 26) * math.sin(ang)
            p.setPen(QPen(QColor("#334155")))
            p.setFont(QFont("Microsoft YaHei UI", 8))
            p.drawText(QRectF(lx - 34, ly - 10, 68, 20), Qt.AlignCenter,
                       f"{d.get('label', '')} {score:+.0f}")


class FanChart(QWidget):
    """蒙特卡洛 5/25/50/75/95 分位扇形图。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fan = None
        self._last = 0.0
        self._title = ""
        self.setMinimumHeight(250)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_data(self, fan: dict | None, last_close: float, title: str = ""):
        if fan and "q5" in fan and "q05" not in fan:
            fan = dict(fan)
            fan["q05"] = fan["q5"]
        self._fan = fan
        self._last = float(last_close or 0)
        self._title = title
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        ml, mr, mt, mb = 52, 20, 24, 30
        p.setPen(QPen(QColor(MUTED)))
        p.setFont(QFont("Microsoft YaHei UI", 9))
        p.drawText(QRectF(ml, 2, w - ml - mr, 18), Qt.AlignLeft, self._title)
        if not self._fan or not self._fan.get("q50"):
            p.setPen(QPen(QColor(MUTED)))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "暂无长周期预测")
            return
        days = self._fan["days"]
        q05, q25, q50, q75, q95 = (np.asarray(self._fan[k], dtype=float) for k in
                                   ("q05", "q25", "q50", "q75", "q95"))
        lo = float(np.nanmin(q05))
        hi = float(np.nanmax(q95))
        if hi - lo < 1e-6:
            hi = lo + 1
        pad_y = (hi - lo) * 0.08
        lo -= pad_y
        hi += pad_y

        def X(d):
            return ml + (w - ml - mr) * d / max(1, days[-1])

        def Y(v):
            return mt + (h - mt - mb) * (1 - (v - lo) / (hi - lo))

        # 网格
        p.setPen(QPen(QColor("#E8EDF4"), 1, Qt.DashLine))
        for i in range(5):
            v = lo + (hi - lo) * i / 4
            y = Y(v)
            p.drawLine(QPointF(ml, y), QPointF(w - mr, y))
            p.setPen(QPen(QColor(MUTED)))
            p.setFont(QFont("Segoe UI", 8))
            p.drawText(QRectF(4, y - 9, ml - 8, 18), Qt.AlignRight | Qt.AlignVCenter, f"{v:.2f}")
            p.setPen(QPen(QColor("#E8EDF4"), 1, Qt.DashLine))

        # 区间带
        def band(a, b, color: QColor):
            path = QPainterPath()
            path.moveTo(X(days[0]), Y(a[0]))
            for i, d in enumerate(days):
                path.lineTo(X(d), Y(a[i]))
            for i in range(len(days) - 1, -1, -1):
                path.lineTo(X(days[i]), Y(b[i]))
            path.closeSubpath()
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawPath(path)

        c95 = QColor(BLUE)
        c95.setAlpha(30)
        band(q05, q95, c95)
        c50 = QColor(ACCENT)
        c50.setAlpha(34)
        band(q25, q75, c50)

        # 中位线与现价
        p.setPen(QPen(QColor(ACCENT), 2))
        path = QPainterPath()
        for i, d in enumerate(days):
            if i == 0:
                path.moveTo(X(d), Y(q50[i]))
            else:
                path.lineTo(X(d), Y(q50[i]))
        p.drawPath(path)
        p.setPen(QPen(QColor(TEXT), 1, Qt.DashLine))
        p.drawLine(QPointF(ml, Y(self._last)), QPointF(w - mr, Y(self._last)))
        p.setPen(QPen(QColor(MUTED)))
        p.setFont(QFont("Segoe UI", 8))
        p.drawText(QRectF(ml - 46, Y(self._last) - 9, 44, 18), Qt.AlignRight | Qt.AlignVCenter,
                   f"{self._last:.2f}")
        # x 轴
        for d in (0, 5, 10, 15, 20, days[-1]):
            if d > days[-1]:
                continue
            x = X(d)
            p.setPen(QPen(QColor("#CFDAE7"), 1))
            p.drawLine(QPointF(x, h - mb), QPointF(x, h - mb + 4))
            p.setPen(QPen(QColor(MUTED)))
            p.setFont(QFont("Microsoft YaHei UI", 8))
            p.drawText(QRectF(x - 20, h - mb + 5, 40, 16), Qt.AlignCenter,
                       "今日" if d == 0 else f"T+{d}")


class DateAxis(pg.AxisItem):
    def __init__(self, dates: list[str], **kwargs):
        super().__init__(orientation="bottom", **kwargs)
        self.dates = dates
        self.setStyle(tickFont=QFont("Segoe UI", 7), tickLength=3)

    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            i = int(round(v))
            out.append(self.dates[i][2:7] if 0 <= i < len(self.dates) else "")
        return out


class CandlestickItem(pg.GraphicsObject):
    def __init__(self, data=None):
        super().__init__()
        self.data = data or []
        self.picture = QPicture()
        self._generate()

    def set_data(self, data):
        self.data = data
        self._generate()
        self.informViewBoundsChanged()
        self.update()

    def _generate(self):
        self.picture = QPicture()
        painter = QPainter(self.picture)
        painter.setRenderHint(QPainter.Antialiasing, False)
        for i, o, h, l, c in self.data:
            if c >= o:
                pen = QPen(QColor(UP), 1.0)
                painter.setPen(pen)
                painter.setBrush(QBrush(QColor("#FFFFFF")))
            else:
                pen = QPen(QColor(DOWN), 1.0)
                painter.setPen(pen)
                painter.setBrush(QBrush(QColor(DOWN)))
            painter.drawLine(QPointF(i, l), QPointF(i, h))
            body_h = abs(c - o)
            if body_h < 1e-9:
                body_h = 1e-6
            painter.drawRect(QRectF(i - 0.36, min(o, c), 0.72, body_h))
        painter.end()

    def paint(self, painter, *args):
        painter.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        r = self.picture.boundingRect()
        return QRectF(r)


class KlineWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.price = pg.PlotWidget(background="#FFFFFF")
        self.volume = pg.PlotWidget(background="#FFFFFF")
        self.macd = pg.PlotWidget(background="#FFFFFF")
        lay.addWidget(self.price, 5)
        lay.addWidget(self.volume, 2)
        lay.addWidget(self.macd, 2)
        for pw in (self.price, self.volume, self.macd):
            pw.setMenuEnabled(False)
            pw.hideButtons()
            pw.setMouseEnabled(x=True, y=False)
            pw.showGrid(x=False, y=True, alpha=0.16)
            p = pw.getPlotItem()
            p.getAxis("left").setPen(pg.mkPen("#D5DEE9"))
            p.getAxis("left").setTextPen(pg.mkPen(MUTED))
            p.getAxis("bottom").setPen(pg.mkPen("#D5DEE9"))
            p.getAxis("bottom").setTextPen(pg.mkPen(MUTED))
        self.price.setLabel("left", "价格", color=MUTED)
        self.volume.setLabel("left", "量(万手)", color=MUTED)
        self.macd.setLabel("left", "MACD", color=MUTED)
        self.price.getPlotItem().hideAxis("bottom")
        self.volume.getPlotItem().hideAxis("bottom")
        self.volume.setXLink(self.price)
        self.macd.setXLink(self.price)
        self.price.getViewBox().enableAutoRange(x=False, y=True)
        self.candles = CandlestickItem()
        self.price.addItem(self.candles)
        self.close_line = self.price.plot([], pen=pg.mkPen(ACCENT2, width=1.8),
                                          connect="finite", name="收盘")
        self.ma5 = self.price.plot([], pen=pg.mkPen("#C08A2E", width=1), connect="finite", name="MA5")
        self.ma20 = self.price.plot([], pen=pg.mkPen(BLUE, width=1), connect="finite", name="MA20")
        self.ma60 = self.price.plot([], pen=pg.mkPen(PURPLE, width=1), connect="finite", name="MA60")
        self.vol_up = pg.BarGraphItem(x=[], height=[], width=0.62, brush=pg.mkBrush(214, 69, 69, 110))
        self.vol_dn = pg.BarGraphItem(x=[], height=[], width=0.62, brush=pg.mkBrush(31, 157, 103, 110))
        self.volume.addItem(self.vol_up)
        self.volume.addItem(self.vol_dn)
        self.macd_up = pg.BarGraphItem(x=[], height=[], width=0.5, brush=pg.mkBrush(214, 69, 69, 110))
        self.macd_dn = pg.BarGraphItem(x=[], height=[], width=0.5, brush=pg.mkBrush(31, 157, 103, 110))
        self.macd.addItem(self.macd_up)
        self.macd.addItem(self.macd_dn)
        self.macd_line = self.macd.plot([], pen=pg.mkPen("#C08A2E", width=1), connect="finite")
        self.signal_line = self.macd.plot([], pen=pg.mkPen(PURPLE, width=1), connect="finite")
        self.price.addLegend(offset=(8, 6), labelTextSize="8pt",
                             brush=pg.mkBrush(255, 255, 255, 232), pen=pg.mkPen(BORDER))
        self._n = 0
        self._window = 120
        self._df = None
        self._dates = []
        self._mode = "line"
        self.set_mode("line")

    def set_data(self, df):
        if df is None or len(df) < 5:
            return
        self._df = df
        n = len(df)
        self._n = n
        x = np.arange(n)
        o = df["open"].to_numpy(float)
        h = df["high"].to_numpy(float)
        l = df["low"].to_numpy(float)
        c = df["close"].to_numpy(float)
        self.candles.set_data([(i, o[i], h[i], l[i], c[i]) for i in range(n)])
        self.close_line.setData(x, c)
        dates = [str(d)[:10] for d in df["date"].tolist()]
        self._dates = dates
        self.ma5.setData(x, df["ma5"].to_numpy(float))
        self.ma20.setData(x, df["ma20"].to_numpy(float))
        self.ma60.setData(x, df["ma60"].to_numpy(float))
        up = c >= o
        vol = df["volume"].to_numpy(float) / 1e4
        self.vol_up.setOpts(x=x[up], height=vol[up])
        self.vol_dn.setOpts(x=x[~up], height=vol[~up])
        hist = np.nan_to_num(df["macd_hist"].to_numpy(float))
        self.macd_up.setOpts(x=x[hist >= 0], height=hist[hist >= 0])
        self.macd_dn.setOpts(x=x[hist < 0], height=hist[hist < 0])
        self.macd_line.setData(x, np.nan_to_num(df["macd"].to_numpy(float)))
        self.signal_line.setData(x, np.nan_to_num(df["macd_signal"].to_numpy(float)))
        axis = DateAxis(dates)
        self.macd.setAxisItems({"bottom": axis})
        self._apply_range()
        self._refresh_ticks()
        self._set_y_ranges()

    def _refresh_ticks(self):
        if not self._dates:
            return
        n = len(self._dates)
        w = self._window if self._window > 0 else n
        start = max(0, n - w)
        # 四个内缩刻度，避免首尾标签被坐标轴/右侧面板裁掉
        idxs = sorted({start + int(round((n - 1 - start) * f))
                       for f in (0.12, 0.37, 0.62, 0.87)})
        axis = self.macd.getAxis("bottom")
        if isinstance(axis, DateAxis):
            axis.setTicks([[(i, self._dates[i][2:7]) for i in idxs]])

    def set_mode(self, mode: str):
        """line = 收盘价折线；candle = 蜡烛图。默认折线。"""
        self._mode = "candle" if str(mode).lower() == "candle" else "line"
        is_line = self._mode == "line"
        self.candles.setVisible(not is_line)
        self.close_line.setVisible(is_line)
        self.ma5.setVisible(not is_line)
        self.ma20.setVisible(True)
        self.ma60.setVisible(not is_line)
        self.ma20.setPen(pg.mkPen(BLUE, width=1, style=Qt.DashLine if is_line else Qt.SolidLine))

    def _set_y_ranges(self):
        if self._df is None:
            return
        df = self._df
        w = self._window if self._window > 0 else len(df)
        view = df.tail(max(5, w))
        lo = float(view["low"].min())
        hi = float(view["high"].max())
        pad = (hi - lo) * 0.06 + 1e-6
        self.price.setYRange(lo - pad, hi + pad, padding=0)
        vmax = float(view["volume"].max()) / 1e4
        self.volume.setYRange(0, vmax * 1.15 + 1e-6, padding=0)
        m = float(np.nanmax(np.abs(view["macd_hist"].to_numpy(float)))) * 1.25 + 1e-6
        self.macd.setYRange(-m, m, padding=0)

    def _apply_range(self):
        if self._n <= 0:
            return
        w = self._window if self._window > 0 else self._n
        self.price.setXRange(max(0, self._n - w), self._n - 1, padding=0)

    def set_window(self, days: int):
        self._window = days
        self._apply_range()
        self._refresh_ticks()
        self._set_y_ranges()


class ChipChart(QWidget):
    """筹码分布横向柱：现价以下为获利盘（红），以上为套牢盘（蓝）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._chips = {}
        self.setMinimumWidth(250)
        self.setMinimumHeight(320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_data(self, chips: dict | None):
        self._chips = chips or {}
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if not self._chips:
            p.setPen(QPen(QColor(MUTED)))
            p.setFont(QFont("Microsoft YaHei UI", 9))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "等待筹码数据")
            return
        ml, mr, mt, mb = 44, 42, 22, 18
        centers = self._chips.get("centers", [])
        weights = self._chips.get("weights", [])
        if not centers or not weights:
            return
        lo = float(self._chips.get("low", min(centers)))
        hi = float(self._chips.get("high", max(centers)))
        if hi - lo < 1e-9:
            hi = lo + 1
        price = float(self._chips.get("price", 0))
        maxw = max(weights) or 1.0
        n = len(centers)
        ph = (h - mt - mb) / max(1, n)
        bar_h = max(2.0, ph * 0.72)
        # 价格网格
        p.setFont(QFont("Segoe UI", 8))
        for k in range(5):
            v = hi - (hi - lo) * k / 4
            y = mt + (h - mt - mb) * k / 4
            p.setPen(QPen(QColor("#E8EDF4"), 1, Qt.DashLine))
            p.drawLine(QPointF(ml, y), QPointF(w - mr, y))
            p.setPen(QPen(QColor(MUTED)))
            p.drawText(QRectF(0, y - 8, ml - 5, 16), Qt.AlignRight | Qt.AlignVCenter, f"{v:.2f}")
        # 筹码条
        for c, wt in zip(centers, weights):
            y = mt + (hi - c) / (hi - lo) * (h - mt - mb)
            x2 = ml + (w - ml - mr) * min(1.0, float(wt) / maxw)
            color = QColor(UP if c <= price else BLUE)
            color.setAlpha(170 if c <= price else 130)
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawRect(QRectF(ml, y - bar_h / 2, max(1.0, x2 - ml), bar_h))
        # 现价线
        y_price = mt + (hi - price) / (hi - lo) * (h - mt - mb)
        p.setPen(QPen(QColor(ACCENT), 1.4, Qt.DashLine))
        p.drawLine(QPointF(ml, y_price), QPointF(w - mr + 4, y_price))
        p.setPen(QPen(QColor(ACCENT)))
        p.setFont(QFont("Segoe UI", 8, QFont.Bold))
        p.drawText(QRectF(w - mr + 2, y_price - 9, mr - 2, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   f"{price:.2f}")
        # 图例
        p.setFont(QFont("Microsoft YaHei UI", 8))
        p.setPen(QPen(QColor(UP)))
        p.drawText(QRectF(ml, 2, 90, 16), Qt.AlignLeft, "获利盘")
        p.setPen(QPen(QColor(BLUE)))
        p.drawText(QRectF(ml + 66, 2, 90, 16), Qt.AlignLeft, "套牢盘")


class LineChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.plot = pg.PlotWidget(background=PANEL2)
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.showGrid(x=False, y=True, alpha=0.12)
        self.plot.getPlotItem().getAxis("left").setTextPen(pg.mkPen(MUTED))
        self.plot.getPlotItem().getAxis("bottom").setTextPen(pg.mkPen(MUTED))
        lay.addWidget(self.plot)
        self._line = self.plot.plot([], pen=pg.mkPen(ACCENT, width=1.4))
        self._base = self.plot.plot([], pen=pg.mkPen("#B8C5D6", width=1, style=Qt.DashLine))
        self.setMinimumHeight(150)

    def set_series(self, values, baseline: float | None = None, color: str = ACCENT):
        vals = np.asarray(values, dtype=float)
        if vals.size == 0:
            return
        x = np.arange(len(vals))
        self._line.setData(x, vals, pen=pg.mkPen(color, width=1.4))
        if baseline is not None:
            self._base.setData(x, np.full(len(vals), baseline))
        lo, hi = np.nanmin(vals), np.nanmax(vals)
        if baseline is not None:
            lo, hi = min(lo, baseline), max(hi, baseline)
        # 净值/情绪序列可能完全平直；给一个最小可视跨度，避免纵轴出现
        # 1.0000005 / 0.9999995 这种无意义的浮点刻度。
        if hi - lo < 0.01:
            mid = (hi + lo) / 2
            lo, hi = mid - 0.005, mid + 0.005
        pad = (hi - lo) * 0.08
        self.plot.setYRange(lo - pad, hi + pad, padding=0)
        self.plot.setXRange(0, max(1, len(vals) - 1), padding=0)


class CalibrationChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = []
        self.setMinimumHeight(150)

    def set_data(self, data):
        self._data = data or []
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        ml, mr, mt, mb = 38, 16, 12, 24
        p.setPen(QPen(QColor("#DCE4EE"), 1))
        p.setBrush(QColor("#FFFFFF"))
        p.drawRect(QRectF(ml, mt, w - ml - mr, h - mt - mb))
        p.setPen(QPen(QColor("#C9D5E4"), 1, Qt.DashLine))
        p.drawLine(QPointF(ml, h - mb), QPointF(w - mr, mt))
        p.setPen(QPen(QColor(MUTED)))
        p.setFont(QFont("Microsoft YaHei UI", 8))
        p.drawText(QRectF(ml, h - mb + 4, w - ml - mr, 16), Qt.AlignCenter, "预测概率")
        p.drawText(QRectF(0, mt, ml - 4, h - mt - mb), Qt.AlignCenter, "实际")
        for d in self._data:
            x = ml + float(d["pred"]) * (w - ml - mr)
            y = h - mb - float(d["real"]) * (h - mt - mb)
            p.setBrush(QColor(ACCENT))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(x, y), max(3, min(6, 2 + d.get("n", 1) ** 0.5)), max(3, min(6, 2 + d.get("n", 1) ** 0.5)))
        p.setPen(QPen(QColor(MUTED)))
        p.setFont(QFont("Segoe UI", 7))
        p.drawText(QRectF(ml - 30, mt - 2, 28, 14), Qt.AlignRight, "1.0")
        p.drawText(QRectF(ml - 30, h - mb - 12, 28, 14), Qt.AlignRight, "0.0")
