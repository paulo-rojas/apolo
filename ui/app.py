import sys
from pathlib import Path

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication

from manager import ApoloManager
from ui.main_window import MainWindow
from ui.process_cleanup import cleanup_apolo_processes
from ui.single_instance import SingleInstance
from ui.theme import APP_STYLE


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("apolov2")
    app.setStyleSheet(APP_STYLE)
    instance = SingleInstance("Global\\Apolov2DesktopUI")
    if instance.already_running:
        from PySide6.QtWidgets import QMessageBox

        if not instance.notify_existing("show"):
            QMessageBox.information(app.activeWindow(), "apolov2", "apolov2 ya está abierto.")
        return 0
    lock_path = Path(app.applicationDirPath()) / "apolo-ui.lock"
    lock = QLockFile(str(lock_path))
    lock.setStaleLockTime(30000)
    if not lock.tryLock(100):
        lock.removeStaleLockFile()
        if not lock.tryLock(100):
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.information(app.activeWindow(), "apolov2", "apolov2 ya está abierto.")
            return 0
    cleanup_apolo_processes()
    manager = ApoloManager(manage_backend=True)
    window = MainWindow(manager)
    instance.listen(window.request_show)
    window.show()
    manager.start()
    try:
        return app.exec()
    finally:
        lock.unlock()
        instance.release()


if __name__ == "__main__":
    raise SystemExit(main())
