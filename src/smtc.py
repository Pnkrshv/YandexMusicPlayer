"""
smtc.py — Управление медиасессиями Windows через SMTC API.

Исправления:
- _post() эмитит сигналы напрямую из asyncio-потока (Qt AutoConnection
  сам ставит событие в очередь потока-приёмника). Раньше был QTimer.singleShot,
  но у asyncio-потока нет Qt event dispatcher, и таймер не срабатывал —
  сигналы не доходили до виджета.
- Отложенный сброс сессии (1.5 с): устраняет фликер при смене трека,
  когда Яндекс Музыка на мгновение дерегестрирует SMTC-сессию.
- Fallback на медиа-клавиши Windows (VK_MEDIA_NEXT_TRACK /
  VK_MEDIA_PREV_TRACK), если SMTC-команда вернула False.
- После (пере)подключения к сессии сразу вызывается _emit_all(), чтобы
  виджет не оставался в состоянии «нет трека».
- _emit_* не эмитят None, когда сессии нет — UI сбрасывается
  по сигналу session_changed(False).
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import sys
import threading
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

log = logging.getLogger("yandex_widget.smtc")


# --------------------------------------------------------------------------- #
#  Загрузка WinRT-модулей
# --------------------------------------------------------------------------- #

_SMTC_AVAILABLE = False
_SessionManager = None
_DataReader = None
_Buffer = None
_InputStreamOptions = None

if sys.platform == "win32":
    _import_errors = []

    try:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as _SessionManager,
        )
        from winrt.windows.storage.streams import (
            DataReader as _DataReader,
            Buffer as _Buffer,
            InputStreamOptions as _InputStreamOptions,
        )
        _SMTC_AVAILABLE = True
        log.info("Используется winrt.* (per-namespace)")
    except ImportError as e:
        _import_errors.append(f"winrt: {e}")

    if not _SMTC_AVAILABLE:
        try:
            from winsdk.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as _SessionManager,
            )
            from winsdk.windows.storage.streams import (
                DataReader as _DataReader,
                Buffer as _Buffer,
                InputStreamOptions as _InputStreamOptions,
            )
            _SMTC_AVAILABLE = True
            log.info("Используется winsdk.* (монолитный)")
        except ImportError as e:
            _import_errors.append(f"winsdk: {e}")

    if not _SMTC_AVAILABLE:
        log.warning(
            "Не удалось импортировать ни winsdk, ни winrt-Windows.Media.Control.\n"
            "Ошибки: %s",
            "; ".join(_import_errors),
        )
else:
    log.warning("SMTC API доступен только на Windows. Текущая ОС: %s", sys.platform)


# Значения GlobalSystemMediaTransportControlsSessionPlaybackStatus
PLAYBACK_STATUS_CLOSED = 0
PLAYBACK_STATUS_OPENED = 1
PLAYBACK_STATUS_CHANGING = 2
PLAYBACK_STATUS_STOPPED = 3
PLAYBACK_STATUS_PLAYING = 4
PLAYBACK_STATUS_PAUSED = 5

# Виртуальные коды медиа-клавиш Windows
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3
KEYEVENTF_KEYUP = 0x0002


def _send_media_key(vk: int) -> None:
    """Синтезирует нажатие медиа-клавиши через keybd_event."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        log.info("Отправлена медиа-клавиша vk=0x%02X", vk)
    except Exception as e:
        log.warning("_send_media_key failed: %s", e)


def _get_property(obj, name: str, default=None):
    """Универсальный доступ к свойству WinRT-объекта (атрибут или get_*())."""
    if obj is None:
        return default
    try:
        if hasattr(obj, name):
            return getattr(obj, name)
    except Exception:
        pass
    try:
        getter = getattr(obj, "get_" + name, None)
        if getter is not None:
            return getter()
    except Exception:
        pass
    return default


@dataclass
class TrackInfo:
    title: str = "—"
    artist: str = "—"
    album: str = ""
    thumbnail: Optional[bytes] = None
    playback_status: str = "stopped"
    position_ms: int = 0
    duration_ms: int = 0
    can_play: bool = False
    can_pause: bool = False
    can_next: bool = False
    can_previous: bool = False
    can_seek: bool = False
    source_app: str = ""


class SmtcController(QObject):
    track_changed = pyqtSignal(object)
    state_changed = pyqtSignal(str)
    position_changed = pyqtSignal(int, int)
    session_changed = pyqtSignal(bool)
    error_occurred = pyqtSignal(str)

    YANDEX_APP_HINTS = ("yandex", "яндекс", "music", "музык")
    SESSION_LOST_GRACE_SEC = 1.5  # окно, в течение которого сессия считается «мигнувшей»

    def __init__(self):
        super().__init__()
        self._available = _SMTC_AVAILABLE
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._manager = None
        self._session = None
        self._last_track: Optional[TrackInfo] = None
        self._poll_timer: Optional[QTimer] = None
        self._started = False
        self._session_lost_handle: Optional[asyncio.TimerHandle] = None

    @property
    def available(self) -> bool:
        return self._available

    # ------------------------------------------------------------------ #
    #  Жизненный цикл
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        if not self._available:
            self.error_occurred.emit(
                "SMTC API недоступен. Требуется Windows 10+ и пакет "
                "winrt-Windows.Media.Control или winsdk."
            )
            return
        if self._started:
            return
        self._started = True

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, name="smtc-asyncio", daemon=True
        )
        self._thread.start()

        asyncio.run_coroutine_threadsafe(self._setup(), self._loop)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1000)
        self._poll_timer.timeout.connect(self._poll_position)
        self._poll_timer.start()

    def stop(self) -> None:
        if self._poll_timer:
            self._poll_timer.stop()
            self._poll_timer = None
        if self._loop:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._teardown(), self._loop
                ).result(timeout=5)
            except Exception:
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=2)
        self._started = False

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        except Exception as e:
            log.exception("Asyncio loop failed: %s", e)

    # ------------------------------------------------------------------ #
    #  Инициализация
    # ------------------------------------------------------------------ #

    async def _setup(self) -> None:
        try:
            self._manager = await _SessionManager.request_async()
            self._manager.add_sessions_changed(self._on_sessions_changed)
            log.info("SMTC менеджер создан")
            await self._refresh_session()
        except Exception as e:
            log.exception("SMTC setup failed")
            self._emit_error(f"Не удалось подключиться к SMTC: {e}")

    async def _teardown(self) -> None:
        if self._session_lost_handle is not None:
            self._session_lost_handle.cancel()
            self._session_lost_handle = None
        if self._session is not None:
            self._unsubscribe_session(self._session)
        if self._manager is not None:
            try:
                self._manager.remove_sessions_changed(self._on_sessions_changed)
            except Exception:
                pass

    def _unsubscribe_session(self, session) -> None:
        if session is None:
            return
        for attr, remove_name in [
            ("_h_media", "remove_media_properties_changed"),
            ("_h_playback", "remove_playback_info_changed"),
            ("_h_timeline", "remove_timeline_properties_changed"),
        ]:
            token = getattr(self, attr, None)
            if token is not None:
                try:
                    getattr(session, remove_name)(token)
                except Exception as e:
                    log.debug("unsubscribe %s failed: %s", remove_name, e)
                setattr(self, attr, None)

    # ------------------------------------------------------------------ #
    #  Поиск сессии
    # ------------------------------------------------------------------ #

    async def _refresh_session(self) -> None:
        if self._manager is None:
            return
        try:
            sessions = self._manager.get_sessions()
        except Exception as e:
            log.warning("get_sessions failed: %s", e)
            return

        try:
            current = self._manager.get_current_session()
        except Exception:
            current = None

        size = sessions.size if sessions else 0
        log.info(
            "SMTC sessions: %d, current=%s",
            size, self._app_id(current) if current else "None",
        )

        yandex_session = None
        for i in range(size):
            s = sessions[i]
            app_id = self._app_id(s).lower()
            if any(h in app_id for h in self.YANDEX_APP_HINTS):
                yandex_session = s
                log.info("Найдена сессия Яндекса: %s", app_id)
                break

        if yandex_session is None and current is not None:
            yandex_session = current
            log.info(
                "Сессия Яндекса не найдена, используем текущую: %s",
                self._app_id(current),
            )

        await self._switch_session(yandex_session)

    async def _switch_session(self, new_session) -> None:
        if self._session_lost_handle is not None:
            self._session_lost_handle.cancel()
            self._session_lost_handle = None

        if new_session is None:
            if self._session is not None and self._last_track is not None:
                if self._session_lost_handle is None:
                    log.info(
                        "Сессия пропала, отложенный сброс через %.1fс",
                        self.SESSION_LOST_GRACE_SEC,
                    )
                    self._session_lost_handle = self._loop.call_later(
                        self.SESSION_LOST_GRACE_SEC, self._do_session_lost
                    )
                else:
                    log.debug("Отложенный сброс уже запланирован")
            else:
                if self._session is not None:
                    self._unsubscribe_session(self._session)
                self._session = None
                self._post(self.session_changed.emit, False)
            return

        if self._session is not None:
            self._unsubscribe_session(self._session)

        self._session = new_session
        self._post(self.session_changed.emit, True)

        try:
            self._h_media = new_session.add_media_properties_changed(
                self._on_media_changed
            )
            self._h_playback = new_session.add_playback_info_changed(
                self._on_playback_changed
            )
            self._h_timeline = new_session.add_timeline_properties_changed(
                self._on_timeline_changed
            )
            log.info("Подписались на сессию: %s", self._app_id(new_session))
        except Exception as e:
            log.warning("Не удалось подписаться на сессию: %s", e)
            self._session = None
            self._post(self.session_changed.emit, False)
            self._emit_error(f"Не удалось подписаться: {e}")
            return

        try:
            await self._emit_all()
        except Exception as e:
            log.exception("_emit_all after subscribe failed: %s", e)

    def _do_session_lost(self) -> None:
        self._session_lost_handle = None

        if self._manager is not None:
            try:
                sessions = self._manager.get_sessions()
                if sessions and sessions.size > 0:
                    log.info("Сессия уже вернулась, отменяем сброс")
                    return
            except Exception:
                pass

        log.info("Сессия окончательно потеряна")
        if self._session is not None:
            self._unsubscribe_session(self._session)
        self._session = None
        self._last_track = None
        self._post(self.session_changed.emit, False)

    # ------------------------------------------------------------------ #
    #  Обработчики событий
    # ------------------------------------------------------------------ #

    def _on_sessions_changed(self, manager, args):
        log.debug("SMTC sessions_changed")
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._refresh_session(), self._loop)

    def _on_media_changed(self, session, args):
        log.debug("SMTC media_properties_changed")
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._emit_track(), self._loop)

    def _on_playback_changed(self, session, args):
        log.debug("SMTC playback_info_changed")
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._emit_state(), self._loop)

    def _on_timeline_changed(self, session, args):
        log.debug("SMTC timeline_properties_changed")
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._emit_position(), self._loop)

    # ------------------------------------------------------------------ #
    #  Эмиттинг
    # ------------------------------------------------------------------ #

    async def _emit_all(self) -> None:
        log.debug("_emit_all start")
        for coro_fn, name in (
            (self._emit_track, "_emit_track"),
            (self._emit_state, "_emit_state"),
            (self._emit_position, "_emit_position"),
        ):
            try:
                await coro_fn()
            except Exception as e:
                log.exception("%s failed: %s", name, e)
        log.debug("_emit_all done")

    async def _emit_track(self) -> None:
        if self._session is None:
            return
        try:
            media = await self._session.try_get_media_properties_async()
            if media is None:
                self._post(self.track_changed.emit, None)
                return
            title = _get_property(media, "title", "") or "—"
            artist = _get_property(media, "artist", "") or "—"
            album = _get_property(media, "album_title", "") or ""
            thumbnail_bytes = await self._read_thumbnail(media)

            info = TrackInfo(
                title=title,
                artist=artist,
                album=album,
                thumbnail=thumbnail_bytes,
                source_app=self._app_id(self._session),
            )
            if self._last_track is not None:
                info.playback_status = self._last_track.playback_status
                info.can_play = self._last_track.can_play
                info.can_pause = self._last_track.can_pause
                info.can_next = self._last_track.can_next
                info.can_previous = self._last_track.can_previous
                info.can_seek = self._last_track.can_seek
                info.position_ms = self._last_track.position_ms
                info.duration_ms = self._last_track.duration_ms
            self._last_track = info
            log.info(
                "_emit_track: %r — %r (thumb=%s)",
                title, artist, "yes" if thumbnail_bytes else "no",
            )
            self._post(self.track_changed.emit, info)
        except Exception as e:
            log.exception("_emit_track failed: %s", e)
            self._emit_error(f"Не удалось получить трек: {e}")

    async def _emit_state(self) -> None:
        if self._session is None:
            return
        try:
            info = _get_property(self._session, "playback_info")
            if info is None:
                return
            status_int = self._get_playback_status_int(info)
            status_str = self._status_to_str(status_int)

            controls = _get_property(info, "controls")
            if controls is not None:
                can_play = bool(_get_property(controls, "is_play_enabled", False))
                can_pause = bool(_get_property(controls, "is_pause_enabled", False))
                can_next = bool(_get_property(controls, "is_next_enabled", False))
                can_prev = bool(_get_property(controls, "is_previous_enabled", False))
                log.debug(
                    "_emit_state: status=%s play=%s pause=%s next=%s prev=%s",
                    status_str, can_play, can_pause, can_next, can_prev,
                )
                if self._last_track is not None:
                    self._last_track.playback_status = status_str
                    self._last_track.can_play = can_play
                    self._last_track.can_pause = can_pause
                    self._last_track.can_next = can_next
                    self._last_track.can_previous = can_prev
                    self._last_track.can_seek = True
            else:
                log.debug("_emit_state: status=%s (no controls)", status_str)

            self._post(self.state_changed.emit, status_str)
        except Exception as e:
            log.exception("_emit_state failed: %s", e)

    async def _emit_position(self) -> None:
        if self._session is None:
            return
        try:
            timeline = _get_property(self._session, "timeline_properties")
            if timeline is None:
                return
            pos_ms = self._timespan_to_ms(_get_property(timeline, "position", 0))
            end_ms = self._timespan_to_ms(_get_property(timeline, "end_time", 0))
            if self._last_track is not None:
                self._last_track.position_ms = pos_ms
                self._last_track.duration_ms = end_ms
            self._post(self.position_changed.emit, pos_ms, end_ms)
        except Exception as e:
            log.exception("_emit_position failed: %s", e)

    # ------------------------------------------------------------------ #
    #  Управление
    # ------------------------------------------------------------------ #

    def play_pause(self) -> None:
        session = self._session
        if session is None:
            log.warning("play_pause: нет сессии")
            return
        if self._last_track and self._last_track.playback_status == "playing":
            self.pause()
        else:
            self.play()

    def play(self) -> None:
        session = self._session
        if session is None:
            log.warning("play: нет сессии")
            return
        log.info("play: try_play_async")
        self._run_async(session.try_play_async())

    def pause(self) -> None:
        session = self._session
        if session is None:
            log.warning("pause: нет сессии")
            return
        log.info("pause: try_pause_async")
        self._run_async(session.try_pause_async())

    def next(self) -> None:
        session = self._session
        if session is None:
            log.warning("next: нет сессии")
            return
        log.info("next: try_skip_next_async (fallback на медиа-клавишу)")
        self._run_async_with_fallback(
            session.try_skip_next_async(), VK_MEDIA_NEXT_TRACK
        )

    def previous(self) -> None:
        session = self._session
        if session is None:
            log.warning("previous: нет сессии")
            return
        log.info("previous: try_skip_previous_async (fallback на медиа-клавишу)")
        self._run_async_with_fallback(
            session.try_skip_previous_async(), VK_MEDIA_PREV_TRACK
        )

    def seek(self, position_ms: int) -> None:
        session = self._session
        if session is None:
            log.warning("seek: нет сессии")
            return
        position_hns = int(position_ms * 10_000)
        log.info("seek: %d ms", position_ms)
        self._run_async(session.try_change_playback_position_async(position_hns))

    def _poll_position(self) -> None:
        if self._session is None or self._loop is None:
            return
        if self._last_track is None or self._last_track.playback_status != "playing":
            return
        asyncio.run_coroutine_threadsafe(self._emit_position(), self._loop)

    # ------------------------------------------------------------------ #
    #  Вспомогательные
    # ------------------------------------------------------------------ #

    @staticmethod
    def _app_id(session) -> str:
        try:
            return _get_property(session, "source_app_user_model_id", "") or ""
        except Exception:
            return ""

    @staticmethod
    def _get_playback_status_int(playback_info) -> int:
        try:
            status = _get_property(playback_info, "playback_status", 0)
            if isinstance(status, int):
                return int(status)
            value = getattr(status, "value", None)
            if value is not None:
                return int(value)
            return int(status)
        except Exception:
            return 0

    @staticmethod
    def _status_to_str(status_int: int) -> str:
        return {
            PLAYBACK_STATUS_PLAYING: "playing",
            PLAYBACK_STATUS_PAUSED: "paused",
            PLAYBACK_STATUS_STOPPED: "stopped",
            PLAYBACK_STATUS_CLOSED: "stopped",
            PLAYBACK_STATUS_OPENED: "stopped",
            PLAYBACK_STATUS_CHANGING: "stopped",
        }.get(status_int, "stopped")

    @staticmethod
    def _timespan_to_ms(timespan) -> int:
        try:
            value = _get_property(timespan, "duration", timespan)
            return int(value) // 10_000
        except Exception:
            return 0

    async def _read_thumbnail(self, media) -> Optional[bytes]:
        if _Buffer is None or _InputStreamOptions is None:
            return None
        try:
            thumb = _get_property(media, "thumbnail", None)
            if thumb is None:
                return None
            readable_stream = await thumb.open_read_async()
            try:
                size = int(_get_property(readable_stream, "size", 0))
                if size <= 0 or size > 5 * 1024 * 1024:
                    return None
                buf = _Buffer(size)
                await readable_stream.read_async(
                    buf, size, _InputStreamOptions.READ_AHEAD
                )
                try:
                    data = bytes(buf)
                    if data:
                        return data
                except Exception:
                    pass
                if _DataReader is not None:
                    try:
                        reader = _DataReader.from_buffer(buf)
                        buf_len = _get_property(buf, "length", size)
                        raw = reader.read_bytes(buf_len)
                        if isinstance(raw, (bytes, bytearray)):
                            return bytes(raw)
                        if isinstance(raw, (list, tuple)):
                            return bytes(raw)
                        return bytes(raw)
                    except Exception as e:
                        log.warning("DataReader approach failed: %s", e)
                return None
            finally:
                try:
                    readable_stream.close()
                except Exception:
                    pass
        except Exception as e:
            log.warning("_read_thumbnail failed: %s", e)
            return None

    def _run_async(self, coro) -> None:
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._await_safely(coro), self._loop)

    def _run_async_with_fallback(self, coro, fallback_vk: int) -> None:
        if self._loop is None:
            _send_media_key(fallback_vk)
            return

        async def _wrapper():
            try:
                result = await coro
                log.debug("SMTC op result=%r", result)
                return result
            except Exception as e:
                log.warning("SMTC op raised: %s", e)
                return False

        fut = asyncio.run_coroutine_threadsafe(_wrapper(), self._loop)

        def _on_done(f):
            try:
                ok = f.result()
            except Exception as e:
                log.warning("Future failed: %s", e)
                ok = False
            if not ok:
                log.info("SMTC вернул False — отправляем медиа-клавишу")
                self._post(_send_media_key, fallback_vk)

        fut.add_done_callback(_on_done)

    @staticmethod
    async def _await_safely(coro):
        try:
            return await coro
        except Exception as e:
            log.warning("SMTC async op failed: %s", e)

    def _post(self, fn, *args) -> None:
        """
        Вызывает fn(*args) в текущем (asyncio) потоке.

        Для pyqtSignal.emit это безопасно: Qt с AutoConnection сам
        ставит событие в очередь потока-приёмника, если он отличается
        от потока-отправителя. Оборачивать в QTimer.singleShot нельзя —
        у asyncio-потока нет Qt event dispatcher, и таймер не сработает.
        """
        fn(*args)

    def _emit_error(self, msg: str) -> None:
        log.error(msg)
        self.error_occurred.emit(msg)

    # ------------------------------------------------------------------ #
    #  Свойства
    # ------------------------------------------------------------------ #

    @property
    def has_session(self) -> bool:
        return self._session is not None

    @property
    def last_track(self) -> Optional[TrackInfo]:
        return self._last_track