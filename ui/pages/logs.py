from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget
from datetime import datetime

from core.logging import read_recent_lines


class _LogBridge(QObject):
    log = Signal(str, str)


class LogsPage(QWidget):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 25, 30, 24)
        header = QHBoxLayout()
        title = QLabel("Logs")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch()
        clear = QPushButton("Limpiar")
        clear.setObjectName("secondary")
        header.addWidget(clear)
        layout.addLayout(header)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)
        self.output.setPlainText("\n".join(read_recent_lines()))
        clear.clicked.connect(self.output.clear)
        self._bridge = _LogBridge(self)
        self._bridge.log.connect(self.add_log)
        manager.on("log_received", self._bridge.log.emit)

    def add_log(self, source, message):
        timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
        self.output.appendPlainText(f"{timestamp} {source:<12} {message}")
