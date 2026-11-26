"""
widget.py — Виджет панели задач Windows 11 для управления Яндекс Музыкой.

Фон: настоящее размытие (Acrylic) через WinAPI из styles.apply_blur().
Сторонние библиотеки не требуются.
"""
from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, QPoint, QPropertyAnimation, QTimer
from PyQt6.QtGui import (
    QPixmap, QImage, QPainter, QMouseEvent, QPainterPath,
)
from PyQt6.QtWidgets import (
    QWidget, QLabel, QPushButton, QSlider, QVBoxLayout, QHBoxLayout,
    QFrame, QSizePolicy, QSpacerItem, QApplication,
)

from .styles import (
    palette, build_qss, svg_to_icon, make_placeholder_cover,
    apply_blur, set_blur_mode, blur_mode, round_window,
    SVG_PLAY, SVG_PAUSE, SVG_NEXT, SVG_PREV, SVG_CLOSE,
    SVG_VOLUME, SVG_VOLUME_MUTE,
)
from .smtc import SmtcController, TrackInfo

log = logging.getLogger("yandex_widget.widget")

YANDEX_PROCESS_HINTS = (
    "yandex", "music", "ymusic", "яндекс", "музык",
)

CARD_RADIUS = 16


class TaskbarWidget(QWidget):
    WIDTH = 340
    HEIGHT = 200

    def __init__(self, smtc: SmtcController):
        super().__init__()
        self._smtc = smtc
        self._drag_pos: Optional[QPoint] = None
        self._user_seeking = False
        self._volume_ctl = None
        self._pycaw_warned = False
        self._last_volume = 70

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        # Обязательно для скруглённых углов и прозрачных полей
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setObjectName("WidgetRoot")

        self._build_ui()

        # --- Размытие фона ---
        mode = apply_blur(self)
        set_blur_mode(mode)
        log.info("Режим фона: %s", mode)

        self._apply_styles()
        self._connect_signals()
        self._position_near_taskbar()

        # Обрезаем окно по скруглению карточки
        round_window(self, CARD_RADIUS)

        self._fade_in = QPropertyAnimation(self, b"windowOpacity")
        self._fade_in.setDuration(180)

    # ------------------------------------------------------------------ #
    #  UI
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        # Отступов нет: карточка занимает всё окно, углы обрезает SetWindowRgn
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 12, 16, 14)
        card_layout.setSpacing(6)

        # --- Верхняя строка ---
        top = QHBoxLayout()
        brand = QLabel("Яндекс Музыка")
        brand.setObjectName("BrandLabel")
        top.addWidget(brand)
        top.addStretch()

        self.status_lbl = QLabel("Поиск приложения…")
        self.status_lbl.setObjectName("StatusLabel")
        top.addWidget(self.status_lbl)
        top.addSpacing(6)

        close_btn = QPushButton()
        close_btn.setObjectName("IconButton")
        close_btn.setFixedSize(24, 24)
        close_btn.setIcon(svg_to_icon(SVG_CLOSE, 12, color="#8A8A8A"))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.hide)
        top.addWidget(close_btn)
        card_layout.addLayout(top)

        # --- Центр ---
        middle = QHBoxLayout()
        middle.setSpacing(12)

        self.cover_lbl = QLabel()
        self.cover_lbl.setFixedSize(64, 64)
        self.cover_lbl.setPixmap(make_placeholder_cover("♪", 64))
        self.cover_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_lbl.setStyleSheet("background: transparent;")
        middle.addWidget(self.cover_lbl, alignment=Qt.AlignmentFlag.AlignTop)

        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        info_col.setContentsMargins(0, 0, 0, 0)

        self.title_lbl = QLabel("Нет воспроизведения")
        self.title_lbl.setObjectName("TrackTitle")
        info_col.addWidget(self.title_lbl)

        self.artist_lbl = QLabel("Запустите приложение Яндекс Музыки")
        self.artist_lbl.setObjectName("TrackArtist")
        self.artist_lbl.setWordWrap(True)
        info_col.addWidget(self.artist_lbl)

        self.app_lbl = QLabel("")
        self.app_lbl.setObjectName("StatusLabel")
        info_col.addWidget(self.app_lbl)
        info_col.addStretch()

        middle.addLayout(info_col, 1)
        card_layout.addLayout(middle)

        # --- Прогресс ---
        self.progress_container = QWidget()
        self.progress_container.setStyleSheet("background: transparent;")
        progress_row = QHBoxLayout(self.progress_container)
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(6)

        self.current_time_lbl = QLabel("0:00")
        self.current_time_lbl.setObjectName("TimeLabel")
        self.current_time_lbl.setFixedWidth(32)
        progress_row.addWidget(self.current_time_lbl)

        self.progress = ClickSlider()
        self.progress.setObjectName("ProgressSlider")
        self.progress.setOrientation(Qt.Orientation.Horizontal)
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setFixedHeight(14)
        self.progress.sliderMoved.connect(self._on_seek)
        self.progress.sliderPressed.connect(lambda: self._user_seek(True))
        self.progress.sliderReleased.connect(lambda: self._user_seek(False))
        progress_row.addWidget(self.progress, 1)

        self.total_time_lbl = QLabel("0:00")
        self.total_time_lbl.setObjectName("TimeLabel")
        self.total_time_lbl.setFixedWidth(32)
        self.total_time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        progress_row.addWidget(self.total_time_lbl)

        card_layout.addWidget(self.progress_container)
        self.progress_container.setVisible(False)

        # --- Кнопки ---
        controls = QHBoxLayout()
        controls.setSpacing(6)
        controls.setContentsMargins(0, 0, 0, 0)

        self.volume_btn = self._make_ctrl_button(SVG_VOLUME, 28, "Без звука")
        self.volume_btn.clicked.connect(self._on_mute)
        self.volume_btn.setEnabled(True)
        controls.addWidget(self.volume_btn)

        self.volume_slider = QSlider()
        self.volume_slider.setObjectName("VolumeSlider")
        self.volume_slider.setOrientation(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.setFixedWidth(56)
        self.volume_slider.setFixedHeight(14)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        controls.addWidget(self.volume_slider)
        controls.addStretch()

        self.prev_btn = self._make_ctrl_button(SVG_PREV, 28, "Предыдущий трек")
        self.prev_btn.clicked.connect(self._smtc.previous)
        controls.addWidget(self.prev_btn)

        self.play_btn = QPushButton()
        self.play_btn.setObjectName("PlayButton")
        self.play_btn.setFixedSize(40, 40)
        self.play_btn.setIcon(svg_to_icon(SVG_PLAY, 20, color="#FFFFFF"))
        self.play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_btn.clicked.connect(self._smtc.play_pause)
        self.play_btn.setEnabled(False)
        controls.addWidget(self.play_btn)

        self.next_btn = self._make_ctrl_button(SVG_NEXT, 28, "Следующий трек")
        self.next_btn.clicked.connect(self._smtc.next)
        controls.addWidget(self.next_btn)
        controls.addStretch()

        controls.addItem(QSpacerItem(28, 28, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed))
        controls.addItem(QSpacerItem(56, 28, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed))

        card_layout.addLayout(controls)
        root.addWidget(card)

    def _make_ctrl_button(self, svg: str, size: int, tooltip: str) -> QPushButton:
        p = palette()
        btn = QPushButton()
        btn.setObjectName("CtrlButton")
        btn.setFixedSize(size, size)
        btn.setIcon(svg_to_icon(svg, 16, color=p["text"]))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(tooltip)
        btn.setEnabled(False)
        return btn

    def _apply_styles(self) -> None:
        self.setStyleSheet(build_qss(palette()))

    # ------------------------------------------------------------------ #
    #  Сигналы SMTC
    # ------------------------------------------------------------------ #
    def _connect_signals(self) -> None:
        self._smtc.track_changed.connect(self._on_track_changed)
        self._smtc.state_changed.connect(self._on_state_changed)
        self._smtc.position_changed.connect(self._on_position_changed)
        self._smtc.session_changed.connect(self._on_session_changed)
        self._smtc.error_occurred.connect(self._on_error)

    def _on_track_changed(self, track: Optional[TrackInfo]) -> None:
        log.info("Widget _on_track_changed: %r", track)
        if track is None:
            self.title_lbl.setText("Нет воспроизведения")
            self.artist_lbl.setText("Запустите приложение Яндекс Музыки")
            self.app_lbl.setText("")
            self.cover_lbl.setPixmap(make_placeholder_cover("♪", 64))
            self.play_btn.setIcon(svg_to_icon(SVG_PLAY, 20, color="#FFFFFF"))
            self.play_btn.setEnabled(False)
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            self.progress_container.setVisible(False)
            return

        self.title_lbl.setText(track.title or "—")
        artist_text = track.artist or "—"
        if track.album:
            artist_text = f"{artist_text} • {track.album}"
        self.artist_lbl.setText(artist_text)
        self.app_lbl.setText(track.source_app or "")

        if track.thumbnail:
            self._set_cover_from_bytes(track.thumbnail)
        else:
            self.cover_lbl.setPixmap(make_placeholder_cover("♪", 64))

        self.play_btn.setEnabled(True)
        self.prev_btn.setEnabled(True)
        self.next_btn.setEnabled(True)
        self._update_status()

    def _on_state_changed(self, state: str) -> None:
        log.info("Widget _on_state_changed: %r", state)
        if state == "playing":
            self.play_btn.setIcon(svg_to_icon(SVG_PAUSE, 20, color="#FFFFFF"))
            self._update_status("Воспроизведение")
        elif state == "paused":
            self.play_btn.setIcon(svg_to_icon(SVG_PLAY, 20, color="#FFFFFF"))
            self._update_status("Пауза")
        else:
            self.play_btn.setIcon(svg_to_icon(SVG_PLAY, 20, color="#FFFFFF"))
            self._update_status("Остановлено")

        if self._smtc.last_track is not None:
            self.play_btn.setEnabled(True)
            self.prev_btn.setEnabled(True)
            self.next_btn.setEnabled(True)

    def _on_position_changed(self, pos_ms: int, duration_ms: int) -> None:
        if duration_ms > 0:
            self.progress_container.setVisible(True)
            if not self._user_seeking:
                self.progress.setValue(int(pos_ms / duration_ms * 1000))
            self.current_time_lbl.setText(self._ms_to_str(pos_ms))
            self.total_time_lbl.setText(self._ms_to_str(duration_ms))
        else:
            self.progress_container.setVisible(False)

    def _on_session_changed(self, available: bool) -> None:
        log.info("Widget _on_session_changed: available=%s", available)
        if available:
            self._update_status("Подключено")
            QTimer.singleShot(500, self._refresh_status)
            if self._volume_ctl is None:
                self._volume_ctl = self._find_yandex_audio_volume()
                if self._volume_ctl is not None:
                    try:
                        actual = int(self._volume_ctl.GetMasterVolume() * 100)
                        self.volume_slider.blockSignals(True)
                        self.volume_slider.setValue(actual)
                        self.volume_slider.blockSignals(False)
                        log.info("Громкость синхронизирована: %d%%", actual)
                    except Exception as e:
                        log.debug("sync volume failed: %s", e)
        else:
            self._update_status("Яндекс Музыка не найдена")
            self.title_lbl.setText("Нет воспроизведения")
            self.artist_lbl.setText("Запустите приложение Яндекс Музыки")
            self.app_lbl.setText("")
            self.cover_lbl.setPixmap(make_placeholder_cover("♪", 64))
            self.play_btn.setIcon(svg_to_icon(SVG_PLAY, 20, color="#FFFFFF"))
            self.play_btn.setEnabled(False)
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            self.progress_container.setVisible(False)

    def _on_error(self, msg: str) -> None:
        log.error("SMTC error: %s", msg)
        self._update_status("Ошибка")

    # ------------------------------------------------------------------ #
    #  Обработчики UI
    # ------------------------------------------------------------------ #
    def _user_seek(self, val: bool) -> None:
        self._user_seeking = val

    def _on_seek(self, value: int) -> None:
        track = self._smtc.last_track
        if track is None or track.duration_ms == 0:
            duration_ms = self._str_to_ms(self.total_time_lbl.text())
        else:
            duration_ms = track.duration_ms
        if duration_ms > 0:
            self._smtc.seek(int(value / 1000 * duration_ms))

    def _on_volume_changed(self, value: int) -> None:
        if self._volume_ctl is None:
            self._volume_ctl = self._find_yandex_audio_volume()
        if self._volume_ctl is not None:
            try:
                self._volume_ctl.SetMasterVolume(value / 100.0, None)
                log.info("Громкость Яндекса = %d%%", value)
            except Exception as e:
                log.warning("SetMasterVolume failed: %s", e)
                self._volume_ctl = None

        p = palette()
        if value == 0:
            self.volume_btn.setIcon(svg_to_icon(SVG_VOLUME_MUTE, 16, color=p["text"]))
        else:
            self.volume_btn.setIcon(svg_to_icon(SVG_VOLUME, 16, color=p["text"]))

    def _find_yandex_audio_volume(self):
        """Находит ISimpleAudioVolume для аудио-сессии Яндекс Музыки."""
        try:
            from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
        except ImportError:
            if not self._pycaw_warned:
                log.warning(
                    "pycaw не установлен — громкость не управляется. "
                    "Установите: pip install pycaw comtypes"
                )
                self._pycaw_warned = True
            return None

        try:
            sessions = AudioUtilities.GetAllSessions()
        except Exception as e:
            log.warning("GetAllSessions failed: %s", e)
            return None

        found_names: list[str] = []
        candidate = None
        for s in sessions:
            if not s.Process:
                continue
            try:
                name = s.Process.name() or ""
            except Exception:
                continue
            found_names.append(name)
            name_lc = name.lower()
            if any(h in name_lc for h in YANDEX_PROCESS_HINTS):
                candidate = s
                break

        if candidate is None:
            non_system = []
            for s in sessions:
                if not s.Process:
                    continue
                try:
                    if not s._ctl.IsSystemSoundsSession():
                        non_system.append(s)
                except Exception:
                    continue
            if len(non_system) == 1:
                candidate = non_system[0]
                log.info(
                    "Fallback: единственная не-системная сессия — %s",
                    candidate.Process.name(),
                )

        if candidate is None:
            log.warning(
                "Аудио-сессия Яндекс Музыки не найдена. "
                "Доступные процессы: %s",
                ", ".join(sorted(set(found_names))) or "(нет)",
            )
            return None

        try:
            vol = candidate._ctl.QueryInterface(ISimpleAudioVolume)
            log.info(
                "Подключились к аудио-сессии: %s",
                candidate.Process.name() if candidate.Process else "(system)",
            )
            return vol
        except Exception as e:
            log.warning("QueryInterface(ISimpleAudioVolume) failed: %s", e)
            return None

    def _on_mute(self) -> None:
        if self.volume_slider.value() > 0:
            self._last_volume = self.volume_slider.value()
            self.volume_slider.setValue(0)
        else:
            self.volume_slider.setValue(self._last_volume or 70)

    # ------------------------------------------------------------------ #
    #  Обложка
    # ------------------------------------------------------------------ #
    def _set_cover_from_bytes(self, data: bytes) -> None:
        img = QImage()
        if not img.loadFromData(data):
            self.cover_lbl.setPixmap(make_placeholder_cover("♪", 64))
            return
        pixmap = QPixmap.fromImage(img).scaled(
            64, 64,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.cover_lbl.setPixmap(self._round_pixmap(pixmap, 8))

    @staticmethod
    def _round_pixmap(pixmap: QPixmap, radius: int) -> QPixmap:
        result = QPixmap(pixmap.size())
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(0, 0, pixmap.width(), pixmap.height(), radius, radius)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, pixmap)
        painter.end()
        return result

    # ------------------------------------------------------------------ #
    #  Хелперы
    # ------------------------------------------------------------------ #
    def _update_status(self, text: Optional[str] = None) -> None:
        self.status_lbl.setText(text if text is not None else "")

    def _refresh_status(self) -> None:
        track = self._smtc.last_track
        if track is None:
            return
        if track.playback_status == "playing":
            self.status_lbl.setText("Воспроизведение")
        elif track.playback_status == "paused":
            self.status_lbl.setText("Пауза")
        else:
            self.status_lbl.setText("Готово")

    @staticmethod
    def _ms_to_str(ms: int) -> str:
        if ms <= 0:
            return "0:00"
        s = ms // 1000
        m, s = divmod(s, 60)
        if m >= 60:
            h, m = divmod(m, 60)
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    @staticmethod
    def _str_to_ms(s: str) -> int:
        try:
            parts = s.split(":")
            if len(parts) == 2:
                return (int(parts[0]) * 60 + int(parts[1])) * 1000
            if len(parts) == 3:
                return (int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])) * 1000
        except Exception:
            pass
        return 0

    # ------------------------------------------------------------------ #
    #  Позиционирование и перетаскивание
    # ------------------------------------------------------------------ #
    def _position_near_taskbar(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.right() - self.WIDTH - 12
        y = screen.bottom() - self.HEIGHT - 12
        self.move(x, y)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None
        event.accept()

    # ------------------------------------------------------------------ #
    #  Показ/скрытие
    # ------------------------------------------------------------------ #
    def show_widget(self) -> None:
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
            self._fade_in.setStartValue(0.0)
            self._fade_in.setEndValue(1.0)
            self._fade_in.start()
        self.raise_()
        self.activateWindow()

    def hide_widget(self) -> None:
        self.hide()

    def toggle(self) -> None:
        if self.isVisible():
            self.hide_widget()
        else:
            self.show_widget()


class ClickSlider(QSlider):
    """Слайдер, поддерживающий клик по дорожке."""

    def __init__(self):
        super().__init__()
        self._being_dragged = False

    def mousePressEvent(self, ev: QMouseEvent) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            val = self._pixel_pos_to_range_value(ev.position().x())
            self.setValue(val)
            self.sliderMoved.emit(val)
            self._being_dragged = True
            self.sliderPressed.emit()
            ev.accept()
        else:
            super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev: QMouseEvent) -> None:
        if self._being_dragged:
            self._being_dragged = False
            self.sliderReleased.emit()
        super().mouseReleaseEvent(ev)

    def _pixel_pos_to_range_value(self, pos: float) -> int:
        rect = self.rect()
        if self.maximum() == self.minimum() or rect.width() <= 1:
            return self.minimum()
        ratio = max(0.0, min(1.0, pos / rect.width()))
        return int(self.minimum() + ratio * (self.maximum() - self.minimum()))