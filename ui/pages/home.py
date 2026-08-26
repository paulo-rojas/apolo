from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QInputDialog, QVBoxLayout, QWidget

from ui.widgets.service_status import ServiceStatusWidget
from ui.widgets.voice_orb import VoiceOrb


class _AudioBridge(QObject):
    level = Signal(float)
    error = Signal(str)
    status = Signal(str)
    service = Signal(object)


class HomePage(QWidget):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 25, 30, 24)
        layout.setSpacing(14)
        top = QHBoxLayout()
        title = QLabel("APOLOV2")
        title.setObjectName("pageTitle")
        top.addWidget(title)
        top.addStretch()
        self.status = QLabel("● DETENIDO")
        self.status.setObjectName("muted")
        top.addWidget(self.status)
        layout.addLayout(top)
        self.orb = VoiceOrb()
        self._audio_bridge = _AudioBridge(self)
        self._audio_bridge.level.connect(self.orb.set_level)
        self._audio_bridge.error.connect(self._show_voice_error)
        self._audio_bridge.status.connect(self._status_changed)
        self._audio_bridge.service.connect(self._service_changed)
        layout.addWidget(self.orb, 1, Qt.AlignCenter)
        self.activity = QLabel("Listo")
        self.activity.setAlignment(Qt.AlignCenter)
        self.activity.setObjectName("muted")
        layout.addWidget(self.activity)
        services_title = QLabel("SERVICIOS")
        services_title.setObjectName("eyebrow")
        layout.addWidget(services_title)
        services = QHBoxLayout()
        services.setSpacing(8)
        self.service_widgets = {}
        for service in manager.get_services():
            widget = ServiceStatusWidget(service)
            self.service_widgets[service.name] = widget
            services.addWidget(widget)
        layout.addLayout(services)
        actions = QHBoxLayout()
        actions.addStretch()
        for label, method in [("Iniciar", "start"), ("Detener", "stop"), ("Reiniciar", "restart")]:
            button = QPushButton(label)
            button.setObjectName("primary" if method == "start" else "secondary")
            button.clicked.connect(lambda checked=False, action=method: self._run_action(action))
            actions.addWidget(button)
        voice_button = QPushButton("Probar voz")
        voice_button.setObjectName("secondary")
        voice_button.clicked.connect(self._test_voice)
        actions.addWidget(voice_button)
        actions.addStretch()
        layout.addLayout(actions)
        manager.on("status_changed", self._audio_bridge.status.emit)
        manager.on("audio_level_changed", self._audio_bridge.level.emit)
        manager.on("error_received", self._audio_bridge.error.emit)
        manager.on("service_changed", self._audio_bridge.service.emit)

    def _status_changed(self, state):
        self.status.setText(f"● {state.upper()}")
        self.activity.setText({"Activo": "Listo", "Detenido": "Pausado", "Escuchando": "Escuchando...", "Atento": "Atento", "Procesando": "Procesando...", "Hablando": "Reproduciendo"}.get(state, state))
        self.orb.set_state(self.activity.text().replace("...", ""))

    def _run_action(self, action):
        labels = {"stop": "detener apolov2", "restart": "reiniciar apolov2"}
        if action in labels:
            answer = QMessageBox.question(self, "Confirmar acción", f"¿Quieres {labels[action]}?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        getattr(self.manager, action)()

    def _test_voice(self):
        text, accepted = QInputDialog.getText(self, "Probar voz Kokoro", "Texto que debe decir apolov2:", text="Hola, soy apolov2.")
        if accepted and text.strip():
            self.manager.speak(text)

    def _show_voice_error(self, message):
        QMessageBox.critical(self, "No se pudo reproducir la voz", message)

    def _service_changed(self, status):
        widget = self.service_widgets.get(status.name)
        if widget is not None:
            widget.update_status(status)
