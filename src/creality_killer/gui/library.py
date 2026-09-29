"""Left panel: every G-code file on the printer. Drag one onto the viewport to queue it."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QByteArray, QMimeData, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QFileDialog, QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout, QWidget)

from creality_killer.gui.viewport import MIME_GCODE


def fmt_duration(sec: float | None) -> str:
    if not sec:
        return "—"
    h, m = divmod(int(sec) // 60, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


class _FileList(QListWidget):
    files_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setIconSize(QSize(56, 56))
        self.setSpacing(2)

    def mimeData(self, items) -> QMimeData:
        m = QMimeData()
        if items:
            m.setData(MIME_GCODE, QByteArray(items[0].data(Qt.ItemDataRole.UserRole).encode()))
        return m

    def _local_gcodes(self, mime) -> list[Path]:
        return [Path(u.toLocalFile()) for u in mime.urls()
                if u.isLocalFile() and u.toLocalFile().lower().endswith((".gcode", ".gco"))]

    def dragEnterEvent(self, ev):
        if self._local_gcodes(ev.mimeData()):
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev):
        if self._local_gcodes(ev.mimeData()):
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        paths = self._local_gcodes(ev.mimeData())
        if paths:
            self.files_dropped.emit(paths)
            ev.acceptProposedAction()


class LibraryPanel(QWidget):
    import_requested = Signal(list)  # list[Path]
    refresh_requested = Signal()
    selected = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("panel")
        self.setMinimumWidth(240)
        self._items: dict[str, QListWidgetItem] = {}
        title = QLabel("MODELS")
        title.setObjectName("h")
        self.list = _FileList()
        self.list.files_dropped.connect(self.import_requested)
        self.list.itemClicked.connect(lambda it: self.selected.emit(it.data(Qt.ItemDataRole.UserRole)))
        imp = QPushButton("Import G-code…")
        imp.clicked.connect(self._pick)
        ref = QPushButton("Refresh")
        ref.clicked.connect(self.refresh_requested)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        for w in (title, self.list, imp, ref):
            lay.addWidget(w)
        lay.setStretchFactor(self.list, 1)

    def _pick(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(self, "Import G-code", "", "G-code (*.gcode *.gco)")
        if names:
            self.import_requested.emit([Path(n) for n in names])

    def set_files(self, files: list[dict]) -> None:
        self.list.clear()
        self._items.clear()
        for f in sorted(files, key=lambda f: f.get("modified", 0), reverse=True):
            path = f["path"]
            it = QListWidgetItem(self._label(path, f.get("size"), f.get("modified"), None))
            it.setData(Qt.ItemDataRole.UserRole, path)
            it.setSizeHint(QSize(0, 68))
            self.list.addItem(it)
            self._items[path] = it

    @staticmethod
    def _label(path: str, size: int | None, modified: float | None, est: float | None) -> str:
        bits = [fmt_duration(est)] if est else []
        if size:
            bits.append(f"{size / 1e6:.1f} MB")
        if modified:
            bits.append(datetime.fromtimestamp(modified).strftime("%b %d"))
        return f"{Path(path).stem}\n{' · '.join(bits)}"

    def set_card(self, path: str, meta: dict, thumb: bytes | None) -> None:
        it = self._items.get(path)
        if not it:
            return
        it.setText(self._label(path, meta.get("size"), meta.get("modified"), meta.get("estimated_time")))
        if thumb:
            pm = QPixmap()
            if pm.loadFromData(thumb):
                it.setIcon(QIcon(pm))

    def paths(self) -> list[str]:
        return list(self._items)
