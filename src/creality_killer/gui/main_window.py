from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QMessageBox, QSplitter

from creality_killer.core.gcode import Toolpath
from creality_killer.core.queue import PrintQueue
from creality_killer.core.state import PrinterState
from creality_killer.gui.backend import Backend
from creality_killer.gui.info import InfoPanel
from creality_killer.gui.library import LibraryPanel
from creality_killer.gui.viewport import ModelViewport


class MainWindow(QMainWindow):
    def __init__(self, backend: Backend) -> None:
        super().__init__()
        self.backend = backend
        self.state = PrinterState()
        self.queue = PrintQueue()
        self.toolpaths: dict[str, Toolpath] = {}
        self.shown: str | None = None  # path currently in the viewport
        self._loading: set[str] = set()
        self._camera_started = False

        self.setWindowTitle("Creality K1C")
        self.resize(1400, 860)
        self.library = LibraryPanel()
        self.viewport = ModelViewport()
        self.info = InfoPanel()
        split = QSplitter(Qt.Orientation.Horizontal)
        for w in (self.library, self.viewport, self.info):
            split.addWidget(w)
        split.setStretchFactor(1, 1)
        split.setSizes([260, 840, 320])
        split.setChildrenCollapsible(False)
        self.setCentralWidget(split)
        self.conn_label = self.statusBar()

        b = backend
        b.status.connect(self._on_status)
        b.connection.connect(self._on_connection)
        self.library.refresh_requested.connect(self.refresh_files)
        self.library.import_requested.connect(self.import_files)
        self.library.selected.connect(self.preview)
        self.viewport.model_dropped.connect(self.queue_model)
        self.info.queue_selected.connect(self.preview)
        self.info.queue_remove.connect(self._remove_queued)
        self.info.start_requested.connect(self._start_next)
        self.info.pause_toggle_requested.connect(self._toggle_pause)
        self.info.cancel_requested.connect(self._cancel)

    def closeEvent(self, ev) -> None:
        self.info.camera.stop()
        self.backend.stop()
        super().closeEvent(ev)

    def error(self, e: Exception | str) -> None:
        self.statusBar().showMessage(f"⚠ {e}", 8000)

    # ---------------------------------------------------------- connection / files
    def _on_connection(self, s: str) -> None:
        self.statusBar().showMessage(f"{self.backend.client.host}: {s}")
        if s == "connected":
            self.refresh_files()
            if not self._camera_started:
                self._camera_started = True
                self.backend.call(self.backend.client.webcams(), self._on_webcams, lambda e: self._on_webcams([]))

    def _on_webcams(self, cams) -> None:
        cams = cams if isinstance(cams, list) else []
        url = next((c.get("stream_url") for c in cams if c.get("enabled", True) and c.get("stream_url")), None)
        if url:
            url = self.backend.client.resolve_webcam_url(url)
        else:  # common K1-series default; unverified - see `ck connect` output
            url = f"http://{self.backend.client.host}:8080/?action=stream"
        self.info.camera.set_url(url)

    def refresh_files(self) -> None:
        self.backend.call(self.backend.client.list_files(), self._files_loaded, self.error)

    def _files_loaded(self, files: list[dict]) -> None:
        self.library.set_files(files)
        for f in files:
            self.backend.call(self.backend.load_card(f["path"]), lambda r: self.library.set_card(*r), lambda e: None)

    def import_files(self, paths: list[Path]) -> None:
        for p in paths:
            self.statusBar().showMessage(f"uploading {p.name}…")
            self.backend.call(
                self.backend.client.upload(p.name, p),
                lambda _r, n=p.name: (self.statusBar().showMessage(f"uploaded {n}", 4000), self.refresh_files()),
                self.error,
            )

    # ---------------------------------------------------------- preview / queue
    def preview(self, path: str) -> None:
        if path in self.toolpaths:
            self._show(path)
            return
        if path in self._loading:
            return
        self._loading.add(path)
        self.statusBar().showMessage(f"loading {path}…")

        def ok(res):
            p, tp = res
            self._loading.discard(p)
            self.toolpaths[p] = tp
            self.statusBar().showMessage(f"{p}: {tp.n_layers} layers", 5000)
            if self._wanted() == p:
                self._show(p)

        def fail(e):
            self._loading.discard(path)
            self.error(e)

        self.backend.call(self.backend.load_toolpath(path), ok, fail)
        self._want = path

    _want: str | None = None

    def _wanted(self) -> str | None:
        return self.state.filename if self.state.is_printing else self._want

    def _show(self, path: str) -> None:
        self.shown = path
        self.viewport.set_toolpath(self.toolpaths[path])
        self._sync_progress()

    def queue_model(self, path: str) -> None:
        self.queue.add(path)
        self.info.set_queue(self.queue.items)
        if not self.state.is_printing:
            self.preview(path)

    def _remove_queued(self, i: int) -> None:
        self.queue.remove_at(i)
        self.info.set_queue(self.queue.items)

    # ---------------------------------------------------------- live status
    def _on_status(self, delta: dict) -> None:
        was = self.state.filename if self.state.is_printing else None
        self.state.apply(delta)
        self.info.update_state(self.state)
        s = self.state
        if s.is_printing:
            if was != s.filename and self.queue.job_started(s.filename):
                self.info.set_queue(self.queue.items)
            if s.filename not in self.toolpaths:
                self._want = s.filename
                self.preview(s.filename)
            elif self.shown != s.filename:
                self._show(s.filename)
        self._sync_progress()

    def _sync_progress(self) -> None:
        s = self.state
        live = s.is_printing and self.shown == s.filename
        self.viewport.set_progress(s.file_position if live else None)

    # ---------------------------------------------------------- print control (all confirmed)
    def _confirm(self, text: str) -> bool:
        return QMessageBox.question(self, "Confirm", text) == QMessageBox.StandardButton.Yes

    def _start_next(self) -> None:
        head = self.queue.head
        if head and self._confirm(f"Start printing {head}?"):
            self.backend.call(self.backend.client.start_print(head), None, self.error)

    def _toggle_pause(self) -> None:
        c = self.backend.client
        coro = c.resume_print() if self.state.job_state == "paused" else c.pause_print()
        self.backend.call(coro, None, self.error)

    def _cancel(self) -> None:
        if self._confirm("Cancel the current print?"):
            self.backend.call(self.backend.client.cancel_print(), None, self.error)
