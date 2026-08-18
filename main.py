from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from app.core.logging_setup import configure_logging
from app.database.repository import Repository
from app.ui.main_window import MainWindow
from app.utils.paths import ensure_app_dirs


def main() -> int:
    paths = ensure_app_dirs()
    configure_logging(paths.logs)
    app = QApplication(sys.argv)
    app.setApplicationName("AI File Organizer")
    app.setOrganizationName("LocalTools")
    instance_lock = QLockFile(str(paths.data / "application.lock"))
    if not instance_lock.tryLock(100):
        QMessageBox.information(None, "AI File Organizer", "应用已经在运行。请切换到现有窗口。")
        return 0
    app._aifo_instance_lock = instance_lock  # keep the lock alive for the whole process
    repository = Repository(paths.database)
    recovery_warnings = repository.initialize()
    frozen = bool(getattr(sys, "frozen", False))
    excluded_roots = [paths.data, paths.logs] if frozen else [paths.root]
    excluded_files = [Path(sys.executable), paths.root / "USAGE.md"] if frozen else []
    window = MainWindow(repository, paths.root, data_dir=paths.data,
                        scanner_excluded_roots=excluded_roots, scanner_excluded_files=excluded_files)
    for warning in recovery_warnings or []:
        window.append_log(f"历史恢复提示：{warning}")
    window.show()
    if "--smoke-test" in sys.argv:
        QTimer.singleShot(1500, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
