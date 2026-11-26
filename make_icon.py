"""
make_icon.py — генерирует assets/icon.ico из SVG_APP_ICON.
Запуск: python make_icon.py
"""
import sys
from pathlib import Path

from PyQt6.QtCore import QByteArray
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication

from src.styles import SVG_APP_ICON


def main() -> int:
    app = QApplication(sys.argv)

    out = Path("assets")
    out.mkdir(exist_ok=True)

    renderer = QSvgRenderer(QByteArray(SVG_APP_ICON.encode("utf-8")))
    img = QImage(512, 512, QImage.Format.Format_ARGB32)
    img.fill(0)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter)
    painter.end()

    png = out / "icon_512.png"
    img.save(str(png))

    try:
        from PIL import Image
    except ImportError:
        print("Нужен Pillow: pip install pillow")
        return 1

    Image.open(png).save(
        out / "icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
               (64, 64), (128, 128), (256, 256)],
    )
    print("Готово: assets/icon.ico")
    return 0


if __name__ == "__main__":
    sys.exit(main())