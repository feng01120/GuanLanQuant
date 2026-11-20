"""生成应用图标：深色底 + 金色 K 线 + 青色波动线。"""
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF, QLinearGradient
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets"
OUT.mkdir(exist_ok=True)
S = 256

app = QApplication([])

img = QImage(S, S, QImage.Format.Format_ARGB32)
img.fill(Qt.GlobalColor.transparent)

p = QPainter(img)
p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

# 圆角深色底
grad = QLinearGradient(0, 0, S, S)
grad.setColorAt(0, QColor("#0C1626"))
grad.setColorAt(1, QColor("#060A12"))
p.setBrush(grad)
p.setPen(QPen(QColor("#D8A657"), 3))
p.drawRoundedRect(QRectF(6, 6, S - 12, S - 12), 46, 46)

# 金色 K 线
pens = QPen(QColor("#D8A657"), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
p.setPen(pens)
candles = [(58, 178, 96, 142), (98, 188, 132, 118), (134, 170, 168, 100), (170, 150, 202, 76)]
for x, y_low, _, y_high in candles:
    p.drawLine(QPointF(x, y_low), QPointF(x, y_high))
p.setBrush(QColor("#D8A657"))
p.setPen(Qt.PenStyle.NoPen)
p.drawRoundedRect(QRectF(46, 156, 26, 34), 4, 4)
p.drawRoundedRect(QRectF(122, 132, 26, 50), 4, 4)
p.setBrush(QColor("#2EC4B6"))
p.drawRoundedRect(QRectF(84, 162, 26, 40), 4, 4)
p.drawRoundedRect(QRectF(158, 118, 26, 54), 4, 4)

# 青色波动线
pen = QPen(QColor("#2EC4B6"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
p.setPen(pen)
p.setBrush(Qt.BrushStyle.NoBrush)
poly = QPolygonF([
    QPointF(40, 214), QPointF(72, 204), QPointF(100, 218), QPointF(128, 198),
    QPointF(156, 210), QPointF(184, 188), QPointF(216, 196),
])
p.drawPolyline(poly)

# 底部“观澜”
p.setPen(QColor("#E9EFF9"))
p.setFont(QFont("Microsoft YaHei UI", 25, QFont.Weight.Bold))
p.drawText(QRectF(0, 14, S, 38), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, "观 澜")
p.end()

png = OUT / "guanlan.png"
ico = OUT / "guanlan.ico"
img.save(str(png), "PNG")
ok = img.save(str(ico), "ICO")
print("png", png, png.stat().st_size)
print("ico", ico, ico.stat().st_size, "ok" if ok else "failed")
