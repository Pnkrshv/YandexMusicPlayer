"""
tray.py — Иконка в системном трее Windows.

Позволяет:
- Кликнуть левой кнопкой — показать/скрыть виджет
- Кликнуть правой кнопкой — контекстное меню (Показать, Play/Pause,
  Следующий/Предыдущий трек, Выход)
- Иконка в трее отражает состояние (зелёная точка при воспроизведении)
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor, QBrush, QPen
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu

from .styles import svg_to_icon, svg_to_pixmap, SVG_APP_ICON

log = logging.getLogger("yandex_widget.tray")


class TrayIcon(QObject):
    """Иконка трея с меню."""

    show_widget = pyqtSignal()
    play_pause = pyqtSignal()
    next_track = pyqtSignal()
    prev_track = pyqtSignal()
    quit_app = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tray = QSystemTrayIcon(parent)
        self._tray.setIcon(self._make_icon(playing=False))
        self._tray.setToolTip("Яндекс Музыка")

        self._build_menu()

        self._tray.activated.connect(self._on_activated)
        self._tray.show()

    def _build_menu(self) -> None:
        menu = QMenu()

        act_show = QAction("Показать виджет", menu)
        act_show.triggered.connect(self.show_widget.emit)
        menu.addAction(act_show)

        menu.addSeparator()

        act_prev = QAction("Предыдущий трек", menu)
        act_prev.triggered.connect(self.prev_track.emit)
        menu.addAction(act_prev)

        act_pp = QAction("Воспроизведение / Пауза", menu)
        act_pp.triggered.connect(self.play_pause.emit)
        menu.addAction(act_pp)

        act_next = QAction("Следующий трек", menu)
        act_next.triggered.connect(self.next_track.emit)
        menu.addAction(act_next)

        menu.addSeparator()

        act_quit = QAction("Выход", menu)
        act_quit.triggered.connect(self.quit_app.emit)
        menu.addAction(act_quit)

        self._tray.setContextMenu(menu)

    # ------------------------------------------------------------------ #
    #  Состояние иконки
    # ------------------------------------------------------------------ #

    def set_playing(self, playing: bool) -> None:
        self._tray.setIcon(self._make_icon(playing=playing))
        self._tray.setToolTip(
            "Яндекс Музыка — воспроизведение"
            if playing else
            "Яндекс Музыка — пауза"
        )

    def _make_icon(self, playing: bool) -> QIcon:
        from PyQt6.QtCore import Qt
        base = svg_to_pixmap(SVG_APP_ICON, 32)
        result = QPixmap(base.size())
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.drawPixmap(0, 0, base)
        painter.setBrush(QBrush(QColor("#22C55E" if playing else "#9CA3AF")))
        painter.setPen(QPen(Qt.GlobalColor.white, 1))
        painter.drawEllipse(22, 22, 9, 9)
        painter.end()
        return QIcon(result)

    # ------------------------------------------------------------------ #
    #  Активация
    # ------------------------------------------------------------------ #

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_widget.emit()
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            self.play_pause.emit()

    def show_message(self, title: str, message: str) -> None:
        self._tray.showMessage(
            title, message, QSystemTrayIcon.MessageIcon.Information, 4000
        )
