from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget
from core.codex_bridge import CodexBridge
from core.config import get_bool, get_str, set_config
from voice.audio_devices import list_audio_devices


CODEX_MODEL_OPTIONS = [
    ("Luna - rápido y económico", "gpt-5.6-luna"),
    ("Terra - balanceado", "gpt-5.6-terra"),
    ("Sol - más capaz", "gpt-5.6-sol"),
    ("Spark - preview rápido", "gpt-5.3-codex-spark"),
    ("Auto de Codex", "default"),
]


class SettingsPage(QWidget):
    def __init__(self, manager=None, parent=None):
        super().__init__(parent)
        self.manager = manager
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 25, 30, 24)
        title = QLabel("Ajustes")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel(f"Browser: {get_str('browser.selected', 'brave')}") )
        layout.addWidget(QLabel(f"Whisper model: {get_str('whisper.model', 'not configured')}") )
        audio_title = QLabel("Audio")
        audio_title.setObjectName("eyebrow")
        layout.addWidget(audio_title)
        audio_form = QFormLayout()
        self.input_combo = QComboBox()
        self.output_combo = QComboBox()
        self.input_combo.currentIndexChanged.connect(lambda _index: self._save_device("input"))
        self.output_combo.currentIndexChanged.connect(lambda _index: self._save_device("output"))
        audio_form.addRow("Entrada", self.input_combo)
        audio_form.addRow("Salida", self.output_combo)
        layout.addLayout(audio_form)
        audio_actions = QHBoxLayout()
        refresh_audio = QPushButton("Actualizar dispositivos")
        refresh_audio.setObjectName("secondary")
        refresh_audio.clicked.connect(self._load_audio_devices)
        test_voice = QPushButton("Probar salida")
        test_voice.setObjectName("secondary")
        test_voice.clicked.connect(lambda: self.manager.speak("Salida de audio configurada.") if self.manager else None)
        audio_actions.addWidget(refresh_audio)
        audio_actions.addWidget(test_voice)
        audio_actions.addStretch()
        layout.addLayout(audio_actions)
        codex_title = QLabel("Codex")
        codex_title.setObjectName("eyebrow")
        layout.addWidget(codex_title)
        codex_form = QFormLayout()
        self.codex_model_combo = QComboBox()
        self.codex_model_combo.setEditable(True)
        for label, model in CODEX_MODEL_OPTIONS:
            self.codex_model_combo.addItem(label, model)
        self.codex_model_combo.currentIndexChanged.connect(lambda _index: self._save_codex_model())
        self.codex_model_combo.lineEdit().editingFinished.connect(self._save_codex_model)
        codex_form.addRow("Modelo", self.codex_model_combo)
        layout.addLayout(codex_form)
        layout.addWidget(QCheckBox("Codex enabled", checked=get_bool('codex.enabled', False)))
        layout.addWidget(QCheckBox("Start Apolo with Windows"))
        layout.addWidget(QCheckBox("Minimize to tray", checked=True))
        test_button = QPushButton("Probar conexión Codex")
        test_button.setObjectName("secondary")
        test_button.clicked.connect(self._test_codex)
        layout.addWidget(test_button)
        layout.addStretch()
        self._loading_audio = False
        self._loading_codex = False
        self._load_audio_devices()
        self._load_codex_model()

    def _test_codex(self):
        try:
            result = CodexBridge().test_connection()
        except Exception as error:
            QMessageBox.critical(self, "Conexión Codex", str(error))
            return
        model = get_str("codex.model", None) or "Auto"
        QMessageBox.information(self, "Conexión Codex", f"Codex disponible: {result['version']}\nModelo Apolo: {model}")

    def _load_audio_devices(self):
        self._loading_audio = True
        try:
            self._populate_combo(self.input_combo, list_audio_devices("input"), get_str("audio.input_device", "default"))
            self._populate_combo(self.output_combo, list_audio_devices("output"), get_str("audio.output_device", "default"))
        finally:
            self._loading_audio = False

    def _populate_combo(self, combo, devices, selected):
        combo.clear()
        combo.addItem("Predeterminado del sistema", "default")
        for device in devices:
            combo.addItem(device.label, str(device.id))
        index = combo.findData(selected or "default")
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _save_device(self, kind):
        if self._loading_audio:
            return
        combo = self.input_combo if kind == "input" else self.output_combo
        value = combo.currentData() or "default"
        set_config(f"audio.{kind}_device", value)
        if kind == "input" and self.manager is not None:
            self.manager.restart()

    def _load_codex_model(self):
        self._loading_codex = True
        try:
            model = get_str("codex.model", None) or "default"
            index = self.codex_model_combo.findData(model)
            if index >= 0:
                self.codex_model_combo.setCurrentIndex(index)
            else:
                self.codex_model_combo.setEditText(model)
        finally:
            self._loading_codex = False

    def _save_codex_model(self):
        if self._loading_codex:
            return
        text = self.codex_model_combo.currentText().strip()
        value = None
        for label, model in CODEX_MODEL_OPTIONS:
            if text == label or text == model:
                value = model
                break
        if value is None:
            value = text
        if value == "default":
            value = None
        set_config("codex.model", value)
