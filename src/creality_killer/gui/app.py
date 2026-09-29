from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QInputDialog

from creality_killer import config
from creality_killer.gui import theme
from creality_killer.gui.backend import Backend
from creality_killer.gui.main_window import MainWindow


def main(host: str | None, port: int = 7125) -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.STYLESHEET)
    if not host:
        host, ok = QInputDialog.getText(None, "Creality K1C", "Printer IP address:")
        if not ok or not host.strip():
            return 1
        host = host.strip()
        config.save(host=host)
    backend = Backend(host, port)
    win = MainWindow(backend)
    win.show()
    backend.start()
    return app.exec()
