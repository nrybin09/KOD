"""Быстрая небесная карта: перерисовка маски не зависит от расчёта."""

from nka_app.common import QBrush, QColor, QPainter, QPen, QPointF, QRectF, QWidget, Qt, math


class SkyMap(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(220, 180)
        self.samples = {}
        self.selected = set()
        self.lower, self.upper = 0.0, 90.0

    def update_view(self, samples, selected, lower, upper):
        self.samples = samples
        self.selected = set(selected)
        self.lower, self.upper = lower, upper
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        center = QPointF(self.width() / 2, self.height() / 2)
        radius = min(self.width(), self.height()) / 2 - 32

        def circle(r):
            return QRectF(center.x() - r, center.y() - r, 2 * r, 2 * r)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e9edf2"))
        painter.drawEllipse(circle(radius))
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(circle(radius * (90 - self.lower) / 90))
        painter.setBrush(QColor("#e9edf2"))
        painter.drawEllipse(circle(radius * (90 - self.upper) / 90))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for elevation in (0, 30, 60):
            r = radius * (90 - elevation) / 90
            painter.setPen(QPen(QColor("#c6d0dd"), 1))
            painter.drawEllipse(circle(r))
            painter.drawText(QPointF(center.x() + 4, center.y() - r + 13), f"{elevation}°")
        for az in range(0, 360, 45):
            angle = math.radians(az)
            end = center + QPointF(radius * math.sin(angle), -radius * math.cos(angle))
            painter.drawLine(center, end)
        painter.setPen(QColor("#334155"))
        for text, dx, dy in (("С · 0°", -20, -radius - 10), ("Ю · 180°", -25, radius + 22),
                             ("З", -radius - 22, 5), ("В", radius + 12, 5)):
            painter.drawText(center + QPointF(dx, dy), text)
        for prn, sample in self.samples.items():
            if sample.el < 0:
                continue
            az = math.radians(sample.az)
            r = radius * (90 - sample.el) / 90
            point = center + QPointF(r * math.sin(az), -r * math.cos(az))
            visible = self.lower <= sample.el <= self.upper
            color = "#16a36a" if prn in self.selected else "#2563eb" if visible else "#9ca3af"
            painter.setBrush(QBrush(QColor(color)))
            painter.setPen(QPen(QColor("#ffffff"), 1))
            painter.drawEllipse(point, 5, 5)
            painter.setPen(QColor("#166534") if prn in self.selected else QColor("#334155"))
            painter.drawText(point + QPointF(7, -5), f"{prn:02d}")
        if not self.samples:
            painter.setPen(QColor("#64748b"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Загрузите файл и задайте координаты")
