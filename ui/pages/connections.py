from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from ui.widgets.service_status import ServiceStatusWidget


class _ServiceBridge(QObject):
    service = Signal(object)


class ConnectionsPage(QWidget):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 25, 30, 24)
        title = QLabel("Conexiones")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        subtitle = QLabel("Estado de los adaptadores de apolov2")
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)
        layout.addSpacing(20)
        self.service_widgets = {}
        for status in manager.get_services():
            widget = ServiceStatusWidget(status)
            self.service_widgets[status.name] = widget
            layout.addWidget(widget)
        layout.addStretch()
        self._bridge = _ServiceBridge(self)
        self._bridge.service.connect(self._service_changed)
        manager.on("service_changed", self._bridge.service.emit)

    def _service_changed(self, status):
        widget = self.service_widgets.get(status.name)
        if widget is not None:
            widget.update_status(status)
