"""
styles.py — Стилизация под Windows 11 + размытие фона (Acrylic / Blur).

Размытие делается напрямую через WinAPI (ctypes), без сторонних библиотек:
SetWindowCompositionAttribute + ACCENT_ENABLE_ACRYLICBLURBEHIND.
Это совместимо с Qt-окном WA_TranslucentBackground, которое нужно для
скруглённых углов и прозрачных полей.

ВАЖНО: DwmExtendFrameIntoClientArea(-1) здесь НЕ используется —
именно он рисовал тёмную подложку под карточкой.
"""

from __future__ import annotations

import ctypes
import sys

from PyQt6.QtCore import Qt, QByteArray
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap, QPen, QBrush
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication, QWidget


# --------------------------------------------------------------------------- #
#  Палитры (базовые — сплошные цвета, используются если размытие недоступно)
# --------------------------------------------------------------------------- #

WIN11_LIGHT = {
    "bg":           "transparent",
    "surface":      "#F3F3F3",
    "surface_alt":  "#E6E6E8",
    "cover_bg":     "#E4E4E8",
    "text":         "#1A1A1A",
    "text_alt":     "#5B5B5B",
    "accent":       "#0067C0",
    "accent_hover": "#005A9E",
    "border":       "#DCDCDE",
}

WIN11_DARK = {
    "bg":           "transparent",
    "surface":      "#2B2B2E",
    "surface_alt":  "#3A3A3E",
    "cover_bg":     "#38383C",
    "text":         "#FFFFFF",
    "text_alt":     "#C5C5C8",
    "accent":       "#4CC2FF",
    "accent_hover": "#62CCFF",
    "border":       "#3F3F44",
}

# Режим фона: "none" | "blur" | "acrylic". Выставляется из виджета.
_BLUR_MODE = "none"


def set_blur_mode(mode: str) -> None:
    global _BLUR_MODE
    _BLUR_MODE = mode if mode in ("none", "blur", "acrylic") else "none"


def blur_mode() -> str:
    return _BLUR_MODE


def _is_dark() -> bool:
    try:
        return QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


def palette() -> dict:
    """Возвращает палитру с учётом темы и доступности размытия."""
    dark = _is_dark()
    p = dict(WIN11_DARK if dark else WIN11_LIGHT)

    if _BLUR_MODE == "acrylic":
        # Акриллик сам даёт тонировку — карточка почти прозрачная
        if dark:
            p["surface"]     = "rgba(43, 43, 46, 70)"
            p["surface_alt"] = "rgba(255, 255, 255, 36)"
            p["border"]      = "rgba(255, 255, 255, 45)"
        else:
            p["surface"]     = "rgba(249, 249, 249, 70)"
            p["surface_alt"] = "rgba(0, 0, 0, 20)"
            p["border"]      = "rgba(0, 0, 0, 25)"
    elif _BLUR_MODE == "blur":
        # Обычный blur без тонировки — тонируем сами
        if dark:
            p["surface"]     = "rgba(37, 37, 40, 175)"
            p["surface_alt"] = "rgba(255, 255, 255, 40)"
            p["border"]      = "rgba(255, 255, 255, 50)"
        else:
            p["surface"]     = "rgba(249, 249, 249, 185)"
            p["surface_alt"] = "rgba(0, 0, 0, 22)"
            p["border"]      = "rgba(0, 0, 0, 28)"

    return p


# --------------------------------------------------------------------------- #
#  QSS
# --------------------------------------------------------------------------- #

def build_qss(p: dict) -> str:
    return f"""
    QWidget#WidgetRoot {{
        background: transparent;
    }}

    QFrame#Card {{
        background: {p['surface']};
        border: 1px solid {p['border']};
        border-radius: 16px;
    }}

    QLabel#BrandLabel {{
        color: {p['text']};
        font-size: 12px;
        font-weight: 600;
        background: transparent;
    }}

    QLabel#TrackTitle {{
        color: {p['text']};
        font-size: 15px;
        font-weight: 600;
        background: transparent;
    }}

    QLabel#TrackArtist {{
        color: {p['text_alt']};
        font-size: 12px;
        background: transparent;
    }}

    QLabel#TimeLabel {{
        color: {p['text_alt']};
        font-size: 10px;
        background: transparent;
    }}

    QLabel#StatusLabel {{
        color: {p['text_alt']};
        font-size: 11px;
        background: transparent;
    }}

    QPushButton#CtrlButton {{
        background: transparent;
        border: none;
        border-radius: 14px;
        color: {p['text']};
        padding: 0;
    }}
    QPushButton#CtrlButton:hover {{
        background: {p['surface_alt']};
    }}
    QPushButton#CtrlButton:pressed {{
        background: {p['border']};
    }}
    QPushButton#CtrlButton:disabled {{
        background: transparent;
    }}

    QPushButton#PlayButton {{
        background: {p['accent']};
        border: none;
        border-radius: 20px;
        color: white;
    }}
    QPushButton#PlayButton:hover {{
        background: {p['accent_hover']};
    }}
    QPushButton#PlayButton:pressed {{
        background: {p['accent']};
    }}
    QPushButton#PlayButton:disabled {{
        background: {p['border']};
    }}

    QSlider#ProgressSlider::groove:horizontal {{
        height: 4px;
        background: {p['border']};
        border-radius: 2px;
    }}
    QSlider#ProgressSlider::sub-page:horizontal {{
        background: {p['accent']};
        border-radius: 2px;
    }}
    QSlider#ProgressSlider::add-page:horizontal {{
        background: {p['border']};
        border-radius: 2px;
    }}
    QSlider#ProgressSlider::handle:horizontal {{
        background: {p['accent']};
        width: 12px;
        height: 12px;
        margin: -4px 0;
        border-radius: 6px;
    }}

    QSlider#VolumeSlider::groove:horizontal {{
        height: 3px;
        background: {p['border']};
        border-radius: 1px;
    }}
    QSlider#VolumeSlider::sub-page:horizontal {{
        background: {p['text_alt']};
        border-radius: 1px;
    }}
    QSlider#VolumeSlider::add-page:horizontal {{
        background: {p['border']};
        border-radius: 1px;
    }}
    QSlider#VolumeSlider::handle:horizontal {{
        background: {p['text']};
        width: 10px;
        height: 10px;
        margin: -4px 0;
        border-radius: 5px;
    }}

    QPushButton#IconButton {{
        background: transparent;
        border: none;
        border-radius: 12px;
        padding: 0;
    }}
    QPushButton#IconButton:hover {{
        background: {p['surface_alt']};
    }}
    """


# --------------------------------------------------------------------------- #
#  SVG-иконки
# --------------------------------------------------------------------------- #

SVG_PLAY = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>'
SVG_PAUSE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path d="M6 5h4v14H6zM14 5h4v14h-4z"/></svg>'
SVG_NEXT = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path d="M6 6l8.5 6L6 18V6zm9 0h2v12h-2z"/></svg>'
SVG_PREV = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path d="M18 6l-8.5 6L18 18V6zM7 6H5v12h2z"/></svg>'
SVG_SHUFFLE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path d="M10.59 9.17 5.41 4 4 5.41l5.17 5.17 1.42-1.41zM14.5 4l2.04 2.04L4 18.59 5.41 20 17.96 7.46 20 9.5V4h-5.5zm.33 9.41-1.41 1.41 3.13 3.13L14.5 20H20v-5.5l-2.04 2.04-3.13-3.13z"/></svg>'
SVG_REPEAT = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path d="M7 7h10v3l4-4-4-4v3H5v6h2V7zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2v4z"/></svg>'
SVG_VOLUME = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3A4.5 4.5 0 0 0 14 7.97v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>'
SVG_VOLUME_MUTE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path d="M16.5 12A4.5 4.5 0 0 0 14 7.97v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51A8.8 8.8 0 0 0 21 12c0-4.28-2.99-7.86-7-8.77v2.06c1.7.43 3.16 1.57 4 3.07v.64zM4.27 3 3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06a8.99 8.99 0 0 0 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4 9.91 6.09 12 8.18V4z"/></svg>'
SVG_CLOSE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>'
SVG_APP_ICON = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <defs><linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%" stop-color="#FFCC00"/><stop offset="100%" stop-color="#FF3333"/>
  </linearGradient></defs>
  <rect x="6" y="6" width="52" height="52" rx="14" fill="url(#g)"/>
  <circle cx="32" cy="32" r="14" fill="none" stroke="white" stroke-width="3"/>
  <circle cx="46" cy="18" r="4" fill="white"/>
</svg>'''


def svg_to_icon(svg: str, size: int = 24, color: str | None = None) -> QIcon:
    if color is not None:
        svg = svg.replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


def svg_to_pixmap(svg: str, size: int = 64) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    return pixmap


def make_placeholder_cover(text: str = "♪", size: int = 120) -> QPixmap:
    p = palette()
    bg = QColor(p["cover_bg"])          # всегда сплошной цвет — QColor-safe
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(bg))
    painter.drawRoundedRect(0, 0, size, size, size * 0.13, size * 0.13)
    painter.setPen(QColor(p["text_alt"]))
    font = painter.font()
    font.setPointSize(max(12, size // 3))
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return pixmap


# --------------------------------------------------------------------------- #
#  Размытие фона через WinAPI (без сторонних библиотек)
# --------------------------------------------------------------------------- #

_WCA_ACCENT_POLICY = 19
_ACCENT_ENABLE_BLURBEHIND = 3
_ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20


class _ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_uint),
        ("AnimationId", ctypes.c_int),
    ]


class _WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.c_void_p),
        ("SizeOfData", ctypes.c_size_t),
    ]


def _argb(alpha: int, r: int, g: int, b: int) -> int:
    """GradientColor хранится как 0xAABBGGRR."""
    return (alpha << 24) | (b << 16) | (g << 8) | r


def _set_accent(hwnd: int, state: int, gradient: int = 0) -> bool:
    try:
        user32 = ctypes.windll.user32
        fn = getattr(user32, "SetWindowCompositionAttribute", None)
        if fn is None:
            return False
        fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(_WINCOMPATTRDATA)]
        fn.restype = ctypes.c_int

        accent = _ACCENT_POLICY(state, 0, gradient, 0)
        data = _WINCOMPATTRDATA(
            _WCA_ACCENT_POLICY,
            ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p),
            ctypes.sizeof(accent),
        )
        return bool(fn(ctypes.c_void_p(hwnd), ctypes.byref(data)))
    except Exception as e:
        print(f"[styles] _set_accent({state}) failed: {e}", file=sys.stderr)
        return False


def apply_blur(widget: QWidget, dark: bool | None = None) -> str:
    """
    Включает размытие под окном. Возвращает применённый режим:
      "acrylic" — акриллик с тонировкой (Win10 1803+ / Win11)
      "blur"    — обычное размытие (Win10 / Win7 Aero)
      "none"    — размытие недоступно, палитра станет непрозрачной
    """
    if sys.platform != "win32":
        return "none"

    try:
        hwnd = int(widget.winId())

        if dark is None:
            dark = _is_dark()

        # Тёмный режим системной рамки (на всякий случай, без расширения рамки)
        try:
            val = ctypes.c_int(1 if dark else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(val), ctypes.sizeof(val),
            )
        except Exception:
            pass

        # Тонировка акрилла: 0x99 ≈ 60 % непрозрачности
        tint = _argb(0x99, 0x20, 0x20, 0x22) if dark else _argb(0x99, 0xF9, 0xF9, 0xF9)

        if _set_accent(hwnd, _ACCENT_ENABLE_ACRYLICBLURBEHIND, tint):
            return "acrylic"

        if _set_accent(hwnd, _ACCENT_ENABLE_BLURBEHIND, 0):
            return "blur"

    except Exception as e:
        print(f"[styles.apply_blur] не удалось: {e}", file=sys.stderr)

    return "none"


def round_window(widget: QWidget, radius: int = 16) -> None:
    """
    Обрезает окно скруглённым прямоугольником, чтобы размытие не торчало
    квадратом за пределами карточки. Учитывает DPI.
    """
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        dpr = widget.devicePixelRatioF() or 1.0
        w = int(widget.width() * dpr)
        h = int(widget.height() * dpr)
        r = int(radius * dpr)
        rgn = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, r * 2, r * 2)
        if rgn:
            # После SetWindowRgn регион принадлежит системе — удалять не нужно
            ctypes.windll.user32.SetWindowRgn(ctypes.c_void_p(hwnd),
                                              ctypes.c_void_p(rgn), True)
    except Exception as e:
        print(f"[styles.round_window] не удалось: {e}", file=sys.stderr)


def is_windows_11() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return sys.getwindowsversion().build >= 22000
    except Exception:
        return False