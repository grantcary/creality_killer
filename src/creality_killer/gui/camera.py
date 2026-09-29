"""MJPEG camera widget. The stream is read on a plain thread and framed by JPEG SOI/EOI markers,
so it doesn't depend on the multipart boundary format the printer's streamer uses."""
from __future__ import annotations

import time

import httpx
from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel

from creality_killer.gui import theme

SOI, EOI = b"\xff\xd8", b"\xff\xd9"
MAX_FPS = 15


class MjpegThread(QThread):
    frame = Signal(QImage)
    failed = Signal(str)

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url
        self._halt = False

    def stop(self) -> None:
        self._halt = True
        self.wait(2000)

    def run(self) -> None:
        while not self._halt:
            try:
                self._stream()
            except Exception as e:  # noqa: BLE001
                self.failed.emit(str(e))
            for _ in range(20):  # 2s back-off, but stay stoppable
                if self._halt:
                    return
                time.sleep(0.1)

    def _stream(self) -> None:
        buf = b""
        last = 0.0
        with httpx.stream("GET", self.url, timeout=httpx.Timeout(5.0, read=10.0)) as r:
            r.raise_for_status()
            for chunk in r.iter_bytes(8192):
                if self._halt:
                    return
                buf += chunk
                while True:
                    s = buf.find(SOI)
                    e = buf.find(EOI, s + 2) if s >= 0 else -1
                    if s < 0 or e < 0:
                        buf = buf[s:] if s >= 0 else buf[-1:]
                        break
                    jpg, buf = buf[s:e + 2], buf[e + 2:]
                    now = time.monotonic()
                    if now - last >= 1 / MAX_FPS:
                        img = QImage.fromData(jpg, "JPEG")
                        if not img.isNull():
                            last = now
                            self.frame.emit(img)


class CameraWidget(QLabel):
    def __init__(self) -> None:
        super().__init__("camera offline")
        self.setMinimumHeight(170)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"background: {theme.BG}; color: {theme.MUTED}; border-radius: 10px;")
        self._thread: MjpegThread | None = None
        self._img: QImage | None = None

    def set_url(self, url: str | None) -> None:
        self.stop()
        if not url:
            self.setText("no camera configured")
            return
        self.setText("connecting…")
        self._thread = MjpegThread(url)
        self._thread.frame.connect(self._on_frame)
        self._thread.failed.connect(lambda m: self._img is None and self.setText(f"camera unavailable\n{m[:60]}"))
        self._thread.start()

    def stop(self) -> None:
        if self._thread:
            self._thread.stop()
            self._thread = None
        self._img = None

    def _on_frame(self, img: QImage) -> None:
        self._img = img
        self._paint()

    def _paint(self) -> None:
        if self._img:
            self.setPixmap(QPixmap.fromImage(self._img).scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._paint()
