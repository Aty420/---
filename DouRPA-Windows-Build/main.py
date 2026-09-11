import ctypes
import os
import shutil
import sys
from pathlib import Path

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from app.main_window_v210 import MainWindow
from app.theme import APP_STYLESHEET


def resource_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def user_root() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) / "DouRPA" if base else Path.home() / "AppData" / "Local" / "DouRPA"
    root.mkdir(parents=True, exist_ok=True)
    return root


def bootstrap_user_files() -> Path:
    src = resource_root()
    dst = user_root()
    for folder in ("config", "samples", "data", "screenshots", "logs"):
        (dst / folder).mkdir(parents=True, exist_ok=True)

    defaults = [
        (src / "config" / "selectors.json", dst / "config" / "selectors.json"),
        (src / "samples" / "相似品批量任务模板.xlsx", dst / "samples" / "相似品批量任务模板.xlsx"),
    ]
    for source, target in defaults:
        if source.exists() and not target.exists():
            shutil.copy2(source, target)
    return dst


def enable_windows_backdrop(window):
    """Best-effort Windows 11 Mica backdrop. Older Windows silently falls back."""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(window.winId())
        dwmapi = ctypes.windll.dwmapi
        # DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_ROUND = 2
        corner = ctypes.c_int(2)
        dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner))
        # DWMWA_SYSTEMBACKDROP_TYPE = 38, DWMSBT_MAINWINDOW = 2 (Mica)
        backdrop = ctypes.c_int(2)
        dwmapi.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(backdrop), ctypes.sizeof(backdrop))
    except Exception:
        pass


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("DouRPA")
    app.setOrganizationName("LocalOps")

    icon_path = resource_root() / "assets" / "DouRPA.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    font = QFont("Microsoft YaHei UI")
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(APP_STYLESHEET)

    try:
        root = bootstrap_user_files()
        window = MainWindow(root)
        if not app.windowIcon().isNull():
            window.setWindowIcon(app.windowIcon())
        window.show()
        enable_windows_backdrop(window)
        return app.exec()
    except Exception as exc:
        QMessageBox.critical(None, "DouRPA 启动失败", f"软件启动时发生异常：\n\n{exc}")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
