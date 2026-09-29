"""Right panel: progress ring, temperatures, camera, and the print queue."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout, QWidget)

from creality_killer.core.state import PrinterState
from creality_killer.gui import theme
from creality_killer.gui.camera import CameraWidget
from creality_killer.gui.library import fmt_duration


class ProgressRing(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(120, 120)
        self.value = 0.0
        self.caption = ""

    def set(self, value: float, caption: str) -> None:
        self.value, self.caption = max(0.0, min(1.0, value)), caption
        self.update()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(9, 9, self.width() - 18, self.height() - 18)
        pen = QPen(QColor(theme.PANEL_HI), 8)
        p.setPen(pen)
        p.drawEllipse(r)
        pen.setColor(QColor(theme.ACCENT))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(r, 90 * 16, int(-self.value * 360 * 16))
        p.setPen(QColor(theme.TEXT))
        f = QFont(self.font())
        f.setPointSize(17)
        f.setBold(True)
        p.setFont(f)
        p.drawText(self.rect().adjusted(0, -8, 0, 0), Qt.AlignmentFlag.AlignCenter, f"{self.value * 100:.0f}%")
        f.setPointSize(8)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(theme.MUTED))
        p.drawText(self.rect().adjusted(0, 34, 0, 0), Qt.AlignmentFlag.AlignCenter, self.caption)


class TempRow(QWidget):
    def __init__(self, name: str) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.name = QLabel(name)
        self.name.setObjectName("muted")
        self.value = QLabel("—")
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight)
        lay.addWidget(self.name)
        lay.addWidget(self.value)

    def set(self, t: tuple[float, float] | None) -> None:
        if t is None:
            self.value.setText("—")
            return
        cur, target = t
        self.value.setText(f"{cur:.0f}°  /  {target:.0f}°" if target else f"{cur:.0f}°")
        self.value.setStyleSheet(f"color: {theme.WARN if target and abs(cur - target) > 3 else theme.TEXT};")


class InfoPanel(QWidget):
    start_requested = Signal()
    pause_toggle_requested = Signal()
    cancel_requested = Signal()
    queue_selected = Signal(str)
    queue_remove = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("panel")
        self.setMinimumWidth(300)
        self.title = QLabel("Idle")
        self.title.setStyleSheet("font-size: 15px; font-weight: 600;")
        self.title.setWordWrap(True)
        self.sub = QLabel("")
        self.sub.setObjectName("muted")
        self.ring = ProgressRing()
        self.stats = QLabel("")
        self.stats.setObjectName("muted")
        top = QHBoxLayout()
        top.addWidget(self.ring)
        top.addWidget(self.stats, 1)

        self.nozzle, self.bed = TempRow("Nozzle"), TempRow("Bed")
        self.extras: dict[str, TempRow] = {}
        self.temp_box = QVBoxLayout()
        self.temp_box.addWidget(self.nozzle)
        self.temp_box.addWidget(self.bed)

        self.camera = CameraWidget()

        self.queue = QListWidget()
        self.queue.setMaximumHeight(130)
        self.queue.itemClicked.connect(lambda it: self.queue_selected.emit(it.data(Qt.ItemDataRole.UserRole)))
        self.queue.keyPressEvent = self._queue_key  # Delete removes the selected entry
        self.start_btn = QPushButton("Start")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start_requested)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(self.pause_toggle_requested)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("danger")
        self.cancel_btn.clicked.connect(self.cancel_requested)
        btns = QHBoxLayout()
        for b in (self.start_btn, self.pause_btn, self.cancel_btn):
            btns.addWidget(b)

        def h(text: str) -> QLabel:
            lab = QLabel(text)
            lab.setObjectName("h")
            return lab

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)
        lay.addWidget(self.title)
        lay.addWidget(self.sub)
        lay.addLayout(top)
        lay.addWidget(h("TEMPERATURES"))
        lay.addLayout(self.temp_box)
        lay.addWidget(h("CAMERA"))
        lay.addWidget(self.camera, 1)
        lay.addWidget(h("QUEUE"))
        lay.addWidget(self.queue)
        lay.addLayout(btns)
        self.update_state(PrinterState())
        self.set_queue([])

    def _queue_key(self, ev) -> None:
        if ev.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.queue.currentRow() >= 0:
            self.queue_remove.emit(self.queue.currentRow())
        else:
            QListWidget.keyPressEvent(self.queue, ev)

    def set_queue(self, paths: list[str]) -> None:
        self.queue.clear()
        for i, p in enumerate(paths, 1):
            it = QListWidgetItem(f"{i}.  {p.rsplit('/', 1)[-1]}")
            it.setData(Qt.ItemDataRole.UserRole, p)
            self.queue.addItem(it)
        self.start_btn.setEnabled(bool(paths) and not self._printing)
        self.start_btn.setText("Start")
        self.start_btn.setToolTip(f"Start {paths[0]}" if paths else "Queue is empty")

    _printing = False

    def update_state(self, s: PrinterState) -> None:
        self._printing = s.is_printing
        self.pause_btn.setEnabled(s.is_printing)
        self.cancel_btn.setEnabled(s.is_printing)
        self.pause_btn.setText("Resume" if s.job_state == "paused" else "Pause")
        self.start_btn.setEnabled(self.queue.count() > 0 and not s.is_printing)
        self.title.setText(s.filename.rsplit("/", 1)[-1] if s.is_printing else "Idle")
        self.sub.setText(s.job_state.capitalize())
        layer = f"layer {s.current_layer}/{s.total_layers}" if s.current_layer and s.total_layers else ""
        self.ring.set(s.progress if s.is_printing else 0.0, layer)
        eta = s.eta_seconds
        self.stats.setText(
            f"elapsed  {fmt_duration(s.print_duration)}\nremaining  {fmt_duration(eta)}" if s.is_printing else ""
        )
        self.nozzle.set(s.temp("extruder"))
        self.bed.set(s.temp("heater_bed"))
        for name, t in s.extra_sensors().items():
            if name not in self.extras:
                row = TempRow(name.replace("_", " ").capitalize())
                self.extras[name] = row
                self.temp_box.addWidget(row)
            self.extras[name].set(t)
