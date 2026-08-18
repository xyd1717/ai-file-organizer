from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "windows"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import app.ui.dialogs as dialogs_module
import app.ui.main_window as main_window_module
from app.database.repository import Repository
from app.ui.dialogs import SettingsDialog
from app.ui.main_window import MainWindow


def main() -> None:
    dialogs_module.get_api_key = lambda *_args, **_kwargs: ""
    main_window_module.get_api_key = lambda *_args, **_kwargs: ""
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(dir=ROOT, prefix=".aifo_capture_") as temporary:
        base = Path(temporary)
        repository = Repository(base / "data" / "audit.db")
        repository.initialize()
        window = MainWindow(repository, base / "application", data_dir=base / "data")
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.show(); app.processEvents()
        window.grab().save(str(ROOT / "audit" / "11-windows-native-main.png"))
        dialog = SettingsDialog(repository, window.password_store, window, initial_tab=0, material_manager=window.material_manager)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        dialog.show(); app.processEvents()
        dialog.grab().save(str(ROOT / "audit" / "12-api-provider-presets.png"))
        dialog.close(); window.close(); app.processEvents()


if __name__ == "__main__":
    main()
