from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "windows"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont

import app.ui.dialogs as dialogs_module
import app.ui.main_window as main_window_module
from app.database.repository import Repository
from app.models.schemas import ArchiveStatus, FileRecord
from app.ui.dialogs import RenameOptionsDialog, SettingsDialog
from app.ui.main_window import MainWindow
from app.ui.user_guide import UserGuideDialog


def record(path: Path, category: str, confidence: float, source: str, reason: str) -> FileRecord:
    now = datetime.now()
    return FileRecord(
        path=path,
        name=path.name,
        suffix=path.suffix,
        size=path.stat().st_size,
        created_at=now,
        modified_at=now,
        mime_type="application/octet-stream",
        category=category,
        confidence=confidence,
        source=source,
        reason=reason,
    )


def main() -> None:
    output = Path(__file__).resolve().parent
    dialogs_module.get_api_key = lambda *_args, **_kwargs: ""
    main_window_module.get_api_key = lambda *_args, **_kwargs: ""
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 9))
    with tempfile.TemporaryDirectory(prefix="aifo_ui_audit_") as temporary:
        root = Path(temporary)
        inbox = root / "Downloads"
        inbox.mkdir()
        names = ["IMG_001.jpg", "invoice_2026.pdf", "meeting_notes.txt", "unknown.bin", "photos.zip"]
        for name in names:
            (inbox / name).write_bytes(b"sample")
        repository = Repository(root / "data" / "audit.db")
        repository.initialize()
        window = MainWindow(repository, root / "application", data_dir=root / "data")
        window.setAttribute(Qt.WA_DontShowOnScreen, True)
        window.set_folder(inbox)
        window.task_root = inbox
        window.task_source_roots = [inbox]
        window.records = [
            record(inbox / "IMG_001.jpg", "图片", 0.98, "前缀规则", "命中前缀规则：IMG_"),
            record(inbox / "invoice_2026.pdf", "财务", 0.94, "AI", "检测到发票号码与金额"),
            record(inbox / "meeting_notes.txt", "文档", 0.90, "扩展名规则", "命中扩展名规则：.txt"),
            record(inbox / "unknown.bin", "待确认", 0.35, "AI", "置信度低，需要用户确认"),
            record(inbox / "photos.zip", "压缩包", 0.90, "扩展名规则", "等待安全解压"),
        ]
        window.records[-1].archive_status = ArchiveStatus.WAITING
        window.refresh_table()
        window.show()
        app.processEvents()
        window.grab().save(str(output / "04-main-window-after.png"))

        window.switch_language("en")
        window.switch_material("dark")
        app.processEvents()
        window.grab().save(str(output / "07-main-window-english-dark.png"))

        settings = SettingsDialog(
            repository, window.password_store, window, initial_tab=0,
            material_manager=window.material_manager,
        )
        settings.setAttribute(Qt.WA_DontShowOnScreen, True)
        settings.show()
        app.processEvents()
        settings.grab().save(str(output / "05-api-settings-after.png"))
        settings.close()

        appearance = SettingsDialog(
            repository, window.password_store, window, initial_tab=5,
            material_manager=window.material_manager,
        )
        appearance.setAttribute(Qt.WA_DontShowOnScreen, True)
        appearance.show()
        app.processEvents()
        appearance.grab().save(str(output / "08-appearance-settings-english-dark.png"))
        appearance.tabs.setCurrentIndex(4)
        app.processEvents()
        appearance.grab().save(str(output / "10-extraction-settings-english-dark.png"))
        appearance.close()

        guide = UserGuideDialog(window, "ja")
        guide.setAttribute(Qt.WA_DontShowOnScreen, True)
        guide.show()
        app.processEvents()
        guide.grab().save(str(output / "09-user-guide-japanese.png"))
        guide.close()

        rename = RenameOptionsDialog(repository, window)
        rename.setAttribute(Qt.WA_DontShowOnScreen, True)
        rename.show()
        app.processEvents()
        rename.grab().save(str(output / "06-rename-options-after.png"))
        rename.close()
        window.close()
        app.processEvents()


if __name__ == "__main__":
    main()
