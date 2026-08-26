from PySide6.QtWidgets import QFrame, QLabel, QHBoxLayout, QVBoxLayout

from manager.service_status import ServiceStatus


class ServiceStatusWidget(QFrame):
    def __init__(self, status: ServiceStatus, parent=None):
        super().__init__(parent)
        self.setObjectName("service")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        self.dot = QLabel("●")
        layout.addWidget(self.dot)
        text = QVBoxLayout()
        self.name = QLabel(status.name)
        self.detail = QLabel()
        self.detail.setObjectName("muted")
        text.addWidget(self.name)
        text.addWidget(self.detail)
        layout.addLayout(text)
        layout.addStretch()
        self.state = QLabel()
        self.state.setObjectName("muted")
        layout.addWidget(self.state)
        self.update_status(status)

    def update_status(self, status: ServiceStatus) -> None:
        self.name.setText(status.name)
        self.detail.setText(status.detail or status.state.value)
        self.state.setText(status.state.value.title())
        self.dot.setStyleSheet(f"color: {self._color(status)}; font-size: 12px;")

    @staticmethod
    def _color(status):
        return {"connected": "#8fc7a3", "ready": "#8fc7a3", "error": "#d78383", "disabled": "#707783"}.get(status.state.value, "#8b929d")
