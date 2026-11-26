"""
main.py — Точка входа в приложение «Виджет Яндекс Музыки».

Запуск из исходников:  python main.py
Сборка:                pyinstaller --noconfirm --clean YandexMusicWidget.spec

Горячие клавиши (когда виджет активен):
Ctrl+Alt+P  Play/Pause
Ctrl+Alt+N  Следующий трек
Ctrl+Alt+B  Предыдущий трек
Ctrl+Alt+M  Показать/скрыть виджет
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


# --------------------------------------------------------------------------- #
#  Пути: работают и из исходников, и внутри собранного exe
# --------------------------------------------------------------------------- #
def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


BASE_DIR = _base_dir()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

IS_FROZEN = getattr(sys, "frozen", False)


# --------------------------------------------------------------------------- #
#  Логирование: в exe пишем в %LOCALAPPDATA%\YandexMusicWidget\widget.log
# --------------------------------------------------------------------------- #
def _setup_logging() -> None:
    handlers: list[logging.Handler] = []

    # В режиме --noconsole sys.stderr равен None — обработчик создавать нельзя
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))

    if IS_FROZEN:
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        log_dir = root / "YandexMusicWidget"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            handlers.append(
                logging.FileHandler(log_dir / "widget.log", encoding="utf-8")
            )
        except Exception:
            pass

    if not handlers:
        handlers.append(logging.NullHandler())

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


_setup_logging()
log = logging.getLogger("yandex_widget.main")


# --------------------------------------------------------------------------- #
#  comtypes внутри exe не может писать сгенерированные COM-обёртки на диск —
#  переводим его в режим генерации в памяти (иначе pycaw упадёт)
# --------------------------------------------------------------------------- #
if IS_FROZEN:
    try:
        import comtypes.client
        comtypes.client.gen_dir = None
    except Exception as e:
        log.debug("comtypes gen_dir override failed: %s", e)


from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtWidgets import QApplication

from src.smtc import SmtcController
from src.widget import TaskbarWidget
from src.tray import TrayIcon
from src.styles import svg_to_icon, SVG_APP_ICON


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

        self.widget = TaskbarWidget(self.smtc)
        self.tray = TrayIcon()

        self._connect_signals()
        self._register_hotkeys()

        self.smtc.start()
        self.widget.show_widget()

        self.tray.show_message(
            "Яндекс Музыка — виджет",
            "Виджет запущен. Запустите приложение Яндекс Музыки "
            "и начните воспроизведение — виджет подхватит трек автоматически.",
        )

        return app.exec()

    def _connect_signals(self) -> None:
        self.tray.show_widget.connect(self.widget.show_widget)
        self.tray.play_pause.connect(self.smtc.play_pause)
        self.tray.next_track.connect(self.smtc.next)
        self.tray.prev_track.connect(self.smtc.previous)
        self.tray.quit_app.connect(self._on_quit)

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

    def _register_hotkeys(self) -> None:
        # Родителем QShortcut должен быть QWidget, а не QApplication
        parent = self.widget
        QShortcut(QKeySequence("Ctrl+Alt+P"), parent).activated.connect(
            self.smtc.play_pause
        )
        QShortcut(QKeySequence("Ctrl+Alt+N"), parent).activated.connect(
            self.smtc.next
        )
        QShortcut(QKeySequence("Ctrl+Alt+B"), parent).activated.connect(
            self.smtc.previous
        )
        QShortcut(QKeySequence("Ctrl+Alt+M"), parent).activated.connect(
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