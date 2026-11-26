"""
main.py — Точка входа в приложение «Виджет Яндекс Музыки».

Виджет управляет приложением Яндекс Музыки через Windows SMTC API
(GlobalSystemMediaTransportControls). Тот же API используют медиа-клавиши
клавиатуры, Bluetooth-наушники и стандартные виджеты Windows.

Запуск:
    python main.py

Горячие клавиши (когда приложение активно):
    Ctrl+Alt+P  Play/Pause
    Ctrl+Alt+N  Следующий трек
    Ctrl+Alt+B  Предыдущий трек
    Ctrl+Alt+M  Показать/скрыть виджет
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).parent))

from src.smtc import SmtcController
from src.widget import TaskbarWidget
from src.tray import TrayIcon
from src.styles import svg_to_icon, SVG_APP_ICON

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("yandex_widget.main")


class Application:
    """Связывает SMTC-контроллер, виджет и трей."""

    def __init__(self):
        self.smtc = SmtcController()
        self.widget: TaskbarWidget | None = None
        self.tray: TrayIcon | None = None

    def run(self) -> int:
        app = QApplication.instance() or QApplication(sys.argv)
        app.setApplicationName("Яндекс Музыка — виджет")
        app.setApplicationDisplayName("Яндекс Музыка — виджет")
        app.setWindowIcon(svg_to_icon(SVG_APP_ICON, 64))
        app.setQuitOnLastWindowClosed(False)

        # Создаём виджет и трей
        self.widget = TaskbarWidget(self.smtc)
        self.tray = TrayIcon()

        # Связываем сигналы
        self._connect_signals()
        self._register_hotkeys(app)

        # Запускаем SMTC (подключение к приложению Яндекс Музыки)
        self.smtc.start()

        # Показываем виджет
        self.widget.show_widget()

        # Стартовое уведомление
        self.tray.show_message(
            "Яндекс Музыка — виджет",
            "Виджет запущен. Запустите приложение Яндекс Музыки "
            "и начните воспроизведение — виджет подхватит трек автоматически.",
        )

        return app.exec()

    def _connect_signals(self) -> None:
        # Трей -> действия
        self.tray.show_widget.connect(self.widget.show_widget)
        self.tray.play_pause.connect(self.smtc.play_pause)
        self.tray.next_track.connect(self.smtc.next)
        self.tray.prev_track.connect(self.smtc.previous)
        self.tray.quit_app.connect(self._on_quit)

        # SMTC -> трей (обновление иконки)
        self.smtc.state_changed.connect(self._on_state_changed)
        self.smtc.error_occurred.connect(
            lambda msg: self.tray.show_message("Ошибка", msg)
        )

    def _on_state_changed(self, state: str) -> None:
        if not self.tray:
            return
        self.tray.set_playing(state == "playing")

    def _on_quit(self) -> None:
        log.info("Завершение работы…")
        try:
            self.smtc.stop()
        except Exception:
            pass
        QApplication.quit()

    def _register_hotkeys(self, app: QApplication) -> None:
        QShortcut(QKeySequence("Ctrl+Alt+P"), app).activated.connect(
            self.smtc.play_pause
        )
        QShortcut(QKeySequence("Ctrl+Alt+N"), app).activated.connect(
            self.smtc.next
        )
        QShortcut(QKeySequence("Ctrl+Alt+B"), app).activated.connect(
            self.smtc.previous
        )
        QShortcut(QKeySequence("Ctrl+Alt+M"), app).activated.connect(
            self.widget.toggle
        )


def main() -> int:
    try:
        return Application().run()
    except Exception:
        log.exception("Фатальная ошибка приложения")
        return 1


if __name__ == "__main__":
    sys.exit(main())
