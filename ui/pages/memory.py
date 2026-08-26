from PySide6.QtWidgets import QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget


class MemoryPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 25, 30, 24)
        title = QLabel("Memoria")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        subtitle = QLabel("Patrones preparados para AdaptiveRouter")
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)
        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["Pattern", "Intent", "Uses", "Confidence", "Source"])
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        layout.addWidget(table)
        layout.addStretch()
