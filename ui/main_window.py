from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow, QStackedWidget, QSystemTrayIcon, QMenu, QWidget, QHBoxLayout, QApplication, QStyle, QMessageBox

from ui.pages.connections import ConnectionsPage
from ui.pages.home import HomePage
from ui.pages.logs import LogsPage
from ui.pages.memory import MemoryPage
from ui.pages.settings import SettingsPage
from ui.process_cleanup import cleanup_apolo_processes
from ui.widgets.sidebar import Sidebar


class _WindowBridge(QObject):
    shutdown_requested = Signal()
    show_requested = Signal()


class MainWindow(QMainWindow):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self._exiting = False
        self._talking = False
        self._bridge = _WindowBridge(self)
        self._bridge.shutdown_requested.connect(self._exit)
        self._bridge.show_requested.connect(self.show_window)
        manager.on("shutdown_requested", self._bridge.shutdown_requested.emit)
        self.setWindowTitle("apolov2")
        self.resize(900, 600)
        self.setMinimumSize(760, 500)
        QApplication.instance().installEventFilter(self)
        shell = QWidget()
        layout = QHBoxLayout(shell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(Sidebar())
        self.stack = QStackedWidget()
        self.pages = {"home": HomePage(manager), "connections": ConnectionsPage(manager), "memory": MemoryPage(), "logs": LogsPage(manager), "settings": SettingsPage(manager)}
        for page in self.pages.values():
            self.stack.addWidget(page)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(shell)
        sidebar = layout.itemAt(0).widget()
        sidebar.page_selected.connect(self.show_page)
        self.tray = QSystemTrayIcon(self)
        self.tray.setToolTip("apolov2")
        self.tray.setIcon(QApplication.style().standardIcon(QStyle.SP_ComputerIcon))
        menu = QMenu()
        open_action = QAction("Abrir apolov2", self)
        open_action.triggered.connect(self.show_window)
        pause_action = QAction("Pausar escucha", self)
        pause_action.triggered.connect(manager.stop)
        restart_action = QAction("Reiniciar apolov2", self)
        restart_action.triggered.connect(manager.restart)
        exit_action = QAction("Salir", self)
        exit_action.triggered.connect(self._confirm_exit)
        menu.addAction(open_action)
        menu.addAction(pause_action)
        menu.addAction(restart_action)
        menu.addSeparator()
        menu.addAction(exit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_window() if reason == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def show_page(self, name):
        self.stack.setCurrentWidget(self.pages[name])

    def eventFilter(self, watched, event):
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Space and event.modifiers() & Qt.ControlModifier:
            if not self._talking:
                self._talking = True
                self.manager.set_voice_state("Escuchando", 0.2)
            return True
        if event.type() == QEvent.KeyRelease and event.key() == Qt.Key_Space and self._talking:
            self._talking = False
            self.manager.set_voice_state("Activo", 0.0)
            return True
        return super().eventFilter(watched, event)

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def request_show(self, message: str = "show") -> None:
        if message == "show":
            self._bridge.show_requested.emit()

    def closeEvent(self, event):
        if self._exiting:
            event.accept()
            return
        self._exit()
        event.accept()

    def _exit(self):
        self._exiting = True
        self.tray.hide()
        self.manager.stop()
        cleanup_apolo_processes()
        QMainWindow.close(self)
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _confirm_exit(self):
        answer = QMessageBox.question(self, "Salir de apolov2", "¿Quieres cerrar apolov2 completamente?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self._exit()
