from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout


class Sidebar(QFrame):
    page_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 22, 16, 16)
        layout.setSpacing(6)
        brand = QLabel("apolov2")
        brand.setObjectName("brand")
        layout.addWidget(brand)
        layout.addSpacing(26)
        for label, page in [("Inicio", "home"), ("Conexiones", "connections"), ("Memoria", "memory"), ("Logs", "logs"), ("Ajustes", "settings")]:
            button = QPushButton(label)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, value=page: self.page_selected.emit(value))
            layout.addWidget(button)
            if page == "home":
                button.setChecked(True)
        layout.addStretch()
        version = QLabel("LOCAL AGENT / v2")
        version.setObjectName("muted")
        layout.addWidget(version)
