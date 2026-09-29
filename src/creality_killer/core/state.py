"""Printer state assembled from Moonraker status deltas."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _merge(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        else:
            dst[k] = v


@dataclass
class PrinterState:
    raw: dict[str, Any] = field(default_factory=dict)

    def apply(self, delta: dict) -> None:
        _merge(self.raw, delta)

    def get(self, obj: str, key: str, default: Any = None) -> Any:
        return self.raw.get(obj, {}).get(key, default)

    # --- print job
    @property
    def job_state(self) -> str:
        return self.get("print_stats", "state", "unknown")

    @property
    def filename(self) -> str:
        return self.get("print_stats", "filename", "") or ""

    @property
    def is_printing(self) -> bool:
        return self.job_state in ("printing", "paused")

    @property
    def progress(self) -> float:
        return float(self.get("virtual_sdcard", "progress", 0.0) or 0.0)

    @property
    def file_position(self) -> int:
        return int(self.get("virtual_sdcard", "file_position", 0) or 0)

    @property
    def print_duration(self) -> float:
        return float(self.get("print_stats", "print_duration", 0.0) or 0.0)

    @property
    def current_layer(self) -> int | None:
        return self.raw.get("print_stats", {}).get("info", {}).get("current_layer")

    @property
    def total_layers(self) -> int | None:
        return self.raw.get("print_stats", {}).get("info", {}).get("total_layer")

    @property
    def eta_seconds(self) -> float | None:
        p = self.progress
        d = self.print_duration
        if p <= 0.01 or d <= 0:
            return None
        return d / p - d

    # --- temperatures: (current, target) or None if the sensor doesn't exist
    def temp(self, obj: str) -> tuple[float, float] | None:
        o = self.raw.get(obj)
        if not o or "temperature" not in o:
            return None
        return float(o["temperature"]), float(o.get("target", 0.0) or 0.0)

    def extra_sensors(self) -> dict[str, tuple[float, float]]:
        """Chamber / other sensors, keyed by display name."""
        out = {}
        for name in self.raw:
            for prefix in ("heater_generic ", "temperature_sensor ", "temperature_fan "):
                if name.startswith(prefix):
                    t = self.temp(name)
                    if t:
                        out[name[len(prefix):]] = t
        return out

    @property
    def position(self) -> tuple[float, float, float] | None:
        p = self.get("toolhead", "position")
        return (p[0], p[1], p[2]) if p and len(p) >= 3 else None
