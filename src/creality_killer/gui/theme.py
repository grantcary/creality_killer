from __future__ import annotations

BG = "#14161a"
PANEL = "#1b1e24"
PANEL_HI = "#242831"
BORDER = "#2c313b"
TEXT = "#e6e8ec"
MUTED = "#8a919e"
ACCENT = "#4cc2ff"
OK = "#5bd68a"
WARN = "#f5b84c"
BAD = "#ff6b6b"

# (keywords, rgb) - first match wins; slicers name features differently
# (Cura WALL-OUTER, Prusa "External perimeter", Orca "Outer wall").
_FEATURES = [
    (("outer", "external"), (0.30, 0.76, 1.00)),
    (("inner", "perimeter", "wall"), (0.36, 0.55, 0.95)),
    (("top", "skin", "bottom", "solid"), (0.98, 0.72, 0.30)),
    (("bridge",), (0.45, 0.90, 0.75)),
    (("infill", "fill"), (0.92, 0.46, 0.42)),
    (("support",), (0.72, 0.62, 0.95)),
    (("skirt", "brim"), (0.60, 0.65, 0.70)),
]
_DEFAULT = (0.80, 0.82, 0.86)


def kind_color(name: str) -> tuple[float, float, float]:
    n = name.lower()
    for words, rgb in _FEATURES:
        if any(w in n for w in words):
            return rgb
    return _DEFAULT


STYLESHEET = f"""
* {{ font-family: "Inter", "Segoe UI", "Helvetica Neue", sans-serif; font-size: 13px; color: {TEXT}; }}
QMainWindow, QWidget#root {{ background: {BG}; }}
QWidget#panel {{ background: {PANEL}; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#h {{ font-size: 11px; color: {MUTED}; letter-spacing: 1px; text-transform: uppercase; }}
QListWidget {{ background: transparent; border: none; outline: 0; }}
QListWidget::item {{ padding: 6px; border-radius: 8px; }}
QListWidget::item:hover {{ background: {PANEL_HI}; }}
QListWidget::item:selected {{ background: {PANEL_HI}; border: 1px solid {ACCENT}; }}
QPushButton {{ background: {PANEL_HI}; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 12px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {PANEL_HI}; }}
QPushButton#primary {{ background: {ACCENT}; color: #04202e; border: none; font-weight: 600; }}
QPushButton#primary:disabled {{ background: {PANEL_HI}; color: {MUTED}; }}
QPushButton#danger:hover {{ border-color: {BAD}; }}
QSplitter::handle {{ background: {BG}; width: 2px; }}
QStatusBar {{ background: {BG}; color: {MUTED}; }}
"""
