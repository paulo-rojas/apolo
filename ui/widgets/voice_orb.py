import math

from PySide6.QtCore import QPointF, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


class VoiceOrb(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._level = 0.0
        self._phase = 0.0
        self._state = "Listo"
        self.setMinimumSize(280, 240)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def _tick(self):
        self._phase = (self._phase + 0.055) % (math.pi * 2)
        if self._state not in {"Escuchando", "Atento", "Hablando"}:
            self._level = max(0.0, self._level * 0.94)
        self.update()

    def set_state(self, state: str):
        self._state = state
        self.update()

    def set_level(self, level: float):
        normalized = max(0.0, min(1.0, float(level)))
        self._level = max(self._level * 0.45, math.sqrt(normalized))
        self.update()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        center = QPointF(self.rect().center())
        breathing = math.sin(self._phase * 0.8) * 2.5
        radius = 52 + breathing + self._level * 24
        accent = QColor("#9df0d7") if self._state == "Atento" else QColor("#a7c7e7")
        motion = self._phase * (2.2 if self._state == "Atento" else 1.8 if self._state == "Procesando" else 0.7)
        attention_boost = 10 if self._state == "Atento" else 0
        for index in range(3, 0, -1):
            spread = radius + 14 + index * 15 + self._level * 22 + attention_boost
            alpha = max(10, 48 - index * 10 + int(self._level * 30) + attention_boost)
            painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), min(95, alpha)), 1.4 + self._level * 0.8))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(self._organic_path(center, spread, motion, index * 0.9))
        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 180), 1.7))
        painter.setBrush(QColor(167, 199, 231, 30))
        painter.drawPath(self._organic_path(center, radius, motion, 0.0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(214, 230, 245, 165))
        painter.drawPath(self._organic_path(center, radius * 0.54, motion * 0.6, 1.3))

    @staticmethod
    def _organic_path(center, radius, phase, offset):
        path = QPainterPath()
        points = []
        for step in range(49):
            angle = math.tau * step / 48 + offset
            wobble = (math.sin(angle * 3 + phase) * 2.8 + math.sin(angle * 5 - phase * 0.7) * 1.8 + math.sin(angle * 2 + phase * 0.4) * 1.2)
            current_radius = radius + wobble
            points.append(QPointF(center.x() + math.cos(angle) * current_radius, center.y() + math.sin(angle) * current_radius))
        path.moveTo(points[0])
        for point in points[1:]:
            path.lineTo(point)
        path.closeSubpath()
        return path
