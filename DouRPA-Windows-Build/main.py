import os
import shutil
import sys
from pathlib import Path

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from app.main_window_v209 import MainWindow
from app.theme import APP_STYLESHEET


def resource_root() -> Path:
    """Return bundled read-only resources in dev and PyInstaller builds."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def user_root() -> Path:
    """All mutable app data lives outside Program Files."""
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


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("DouRPA")
    app.setOrganizationName("LocalOps")
    font = QFont("Microsoft YaHei UI")
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(APP_STYLESHEET)

    try:
        root = bootstrap_user_files()
        window = MainWindow(root)
        window.show()
        return app.exec()
    except Exception as exc:
        QMessageBox.critical(None, "DouRPA 启动失败", f"软件启动时发生异常：\n\n{exc}")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
