"""3D model preview: slow orbit, ghosted model while printing, solid current layer."""
from __future__ import annotations

import time

import numpy as np
import pyqtgraph.opengl as gl
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QLabel

from creality_killer.core.gcode import Toolpath
from creality_killer.gui import theme

MIME_GCODE = "application/x-ck-gcode"

ORBIT_DEG_PER_SEC = 6.0
ORBIT_RESUME_AFTER = 4.0  # seconds idle after the user grabs the camera

# opacity while printing
A_PRINTED, A_UPCOMING, A_CURRENT_DONE, A_CURRENT_TODO = 0.10, 0.03, 1.0, 0.45
A_PREVIEW = 0.95


class ModelViewport(gl.GLViewWidget):
    model_dropped = Signal(str)

    def __init__(self, bed: tuple[float, float, float] = (220.0, 220.0, 250.0)) -> None:
        super().__init__()
        self.bed = bed
        self.setBackgroundColor(theme.BG)
        self.setAcceptDrops(True)
        self.setMinimumWidth(360)
        self.tp: Toolpath | None = None
        self._rgb = np.zeros((0, 3), np.float32)
        self._item: gl.GLLinePlotItem | None = None
        self._last_touch = 0.0
        self._last_frame = time.monotonic()
        self._progress_key: tuple | None = None
        self.orbit_enabled = True

        bx, by, _ = bed
        grid = gl.GLGridItem()
        grid.setSize(bx, by)
        grid.setSpacing(20, 20)
        grid.setColor((255, 255, 255, 28))
        grid.translate(bx / 2, by / 2, 0)
        self.addItem(grid)
        outline = np.array([[0, 0, 0], [bx, 0, 0], [bx, by, 0], [0, by, 0], [0, 0, 0]], float)
        self.addItem(gl.GLLinePlotItem(pos=outline, color=(0.30, 0.76, 1.0, 0.55), width=1.5, antialias=True))
        self.opts["center"] = QVector3D(bx / 2, by / 2, 20)
        self.setCameraPosition(distance=max(bx, by) * 1.9, elevation=28, azimuth=-40)

        self._hint = QLabel("Drag a model here to queue it", self)
        self._hint.setStyleSheet(f"color: {theme.MUTED}; font-size: 15px; background: transparent;")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    # ------------------------------------------------------------ orbit
    def _touch(self) -> None:
        self._last_touch = time.monotonic()

    def mousePressEvent(self, ev):
        self._touch()
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        self._touch()
        super().mouseMoveEvent(ev)

    def wheelEvent(self, ev):
        self._touch()
        super().wheelEvent(ev)

    def _tick(self) -> None:
        now = time.monotonic()
        dt, self._last_frame = now - self._last_frame, now
        if self.orbit_enabled and self.isVisible() and now - self._last_touch > ORBIT_RESUME_AFTER:
            self.opts["azimuth"] = (self.opts["azimuth"] + ORBIT_DEG_PER_SEC * dt) % 360
            self.update()

    # ------------------------------------------------------------ model
    def set_toolpath(self, tp: Toolpath | None) -> None:
        if self._item is not None:
            self.removeItem(self._item)
            self._item = None
        self.tp = tp
        self._progress_key = None
        self._hint.setVisible(tp is None or len(tp.segments) == 0)
        if tp is None or len(tp.segments) == 0:
            return
        kind_rgb = np.array([theme.kind_color(k) for k in tp.kinds], np.float32)
        self._rgb = kind_rgb[tp.kind]
        self._item = gl.GLLinePlotItem(
            pos=tp.segments.reshape(-1, 3), color=self._colors(np.full(len(tp.segments), A_PREVIEW)),
            mode="lines", width=1.6, antialias=True,
        )
        self._item.setGLOptions("translucent")
        self.addItem(self._item)
        lo, hi = tp.bounds
        self.opts["center"] = QVector3D(*((lo + hi) / 2).tolist())
        extent = float(np.linalg.norm(hi - lo))
        self.opts["distance"] = max(extent * 1.9, 90.0)  # frame the part, not the whole bed

    def _colors(self, alpha: np.ndarray) -> np.ndarray:
        rgba = np.concatenate([self._rgb, alpha[:, None].astype(np.float32)], axis=1)
        return np.repeat(rgba, 2, axis=0)  # two vertices per segment

    def set_progress(self, file_position: int | None) -> None:
        """None -> plain solid preview; otherwise ghost the model around the active layer."""
        tp = self.tp
        if self._item is None or tp is None:
            return
        if file_position is None:
            key = ("preview",)
        else:
            seg = tp.segment_at_offset(file_position)
            key = ("print", int(tp.layer[max(seg, 0)]), seg // 200)  # ~200-segment steps
        if key == self._progress_key:
            return
        self._progress_key = key
        if file_position is None:
            alpha = np.full(len(tp.segments), A_PREVIEW)
        else:
            layer = key[1]
            alpha = np.where(tp.layer < layer, A_PRINTED, A_UPCOMING).astype(np.float32)
            s, e = int(tp.layer_start[layer]), int(tp.layer_start[layer + 1])
            done = seg + 1
            alpha[s:e] = A_CURRENT_TODO
            alpha[s:min(max(done, s), e)] = A_CURRENT_DONE
        self._item.setData(color=self._colors(alpha))

    # ------------------------------------------------------------ drag & drop
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasFormat(MIME_GCODE):
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev):
        if ev.mimeData().hasFormat(MIME_GCODE):
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        if ev.mimeData().hasFormat(MIME_GCODE):
            self.model_dropped.emit(bytes(ev.mimeData().data(MIME_GCODE)).decode())
            ev.acceptProposedAction()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._hint.setGeometry(0, self.height() // 2 - 20, self.width(), 40)
