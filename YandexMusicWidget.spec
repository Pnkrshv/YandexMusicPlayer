# -*- mode: python ; coding: utf-8 -*-
"""
YandexMusicWidget.spec — сборка exe для виджета Яндекс Музыки.

Запуск:
    pyinstaller --noconfirm --clean YandexMusicWidget.spec

Результат:
    dist\YandexMusicWidget\YandexMusicWidget.exe
"""
import importlib.util
from PyInstaller.utils.hooks import collect_all

APP_NAME = "YandexMusicWidget"
ICON = "assets/icon.ico"

datas = []
binaries = []
hiddenimports = [
    "src",
    "src.smtc",
    "src.widget",
    "src.styles",
    "src.tray",
    "PyQt6.QtSvg",
]


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except Exception:
        return False


# --- WinRT (SMTC) и COM-аудио (pycaw): PyInstaller их сам не находит ---
for pkg in ("winrt", "winsdk", "comtypes", "pycaw", "psutil"):
    if not _installed(pkg):
        continue
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# --- Явные пространства имён WinRT на случай, если collect_all их пропустил ---
for mod in (
    "winrt.windows.media.control",
    "winrt.windows.storage.streams",
    "winrt.windows.foundation",
    "winrt.windows.foundation.collections",
    "winsdk.windows.media.control",
    "winsdk.windows.storage.streams",
    "comtypes.gen",
    "comtypes.stream",
):
    if _installed(mod) and mod not in hiddenimports:
        hiddenimports.append(mod)


# --- Выкидываем неиспользуемые тяжёлые модули Qt ---
excludes = [
    "tkinter", "unittest", "pydoc",
    "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets", "PyQt6.QtWebEngineQuick",
    "PyQt6.QtQuick", "PyQt6.QtQuick3D", "PyQt6.QtQml",
    "PyQt6.Qt3DCore", "PyQt6.Qt3DRender", "PyQt6.Qt3DInput", "PyQt6.Qt3DLogic",
    "PyQt6.QtCharts", "PyQt6.QtDataVisualization",
    "PyQt6.QtMultimedia", "PyQt6.QtMultimediaWidgets",
    "PyQt6.QtPdf", "PyQt6.QtPdfWidgets",
    "PyQt6.QtBluetooth", "PyQt6.QtNfc", "PyQt6.QtSensors",
    "PyQt6.QtSerialPort", "PyQt6.QtSql", "PyQt6.QtTest",
    "PyQt6.QtDesigner", "PyQt6.QtHelp",
    "PyQt6.QtOpenGL", "PyQt6.QtOpenGLWidgets",
]


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # <-- поставьте True для отладочной сборки
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)