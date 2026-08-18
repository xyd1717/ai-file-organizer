from __future__ import annotations

import os
import time
import zipfile
from datetime import datetime
from pathlib import Path
from threading import Event

import pytest
import send2trash

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QMessageBox

from app.database.repository import Repository
from app.core.extractor import ArchiveExtractor, ExtractionBlocked
from app.core.scanner import FileScanner
from app.core.password_store import PasswordStore
from app.ui.dialogs import PasswordManagerDialog, RenameOptionsDialog, RuleManagerDialog, SettingsDialog
from app.ui.main_window import MainWindow
from app.models.schemas import AppSettings, ArchiveStatus, ClassificationRule, ExtractionResult, FileRecord, RuleType
from app.api.client import AIClient, AIRequestCancelled
from app.i18n import set_language


def test_main_window_and_settings_construct(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    repo = Repository(tmp_path / "data" / "test.db"); repo.initialize()
    window = MainWindow(repo, tmp_path / "application")
    window.set_folder(tmp_path)
    assert window.windowTitle() == "AI File Organizer"
    assert window.rename_box.isChecked() is False
    assert window.table.columnCount() == 11
    assert "API：" in window.api_status.text()
    assert window.api_button.text() == "API 配置…"
    dialog = SettingsDialog(repo, window.password_store, window)
    assert dialog.windowTitle() == "设置"
    tabs = dialog.findChild(__import__("PySide6.QtWidgets", fromlist=["QTabWidget"]).QTabWidget)
    assert tabs.count() == 6
    assert dialog.language.currentData() == "zh_CN"
    assert dialog.material.currentData() == "default"
    assert {dialog.material.itemData(index) for index in range(dialog.material.count())} >= {"default", "dark", "ocean", "warm"}
    assert dialog.confirm.isChecked() and not dialog.confirm.isEnabled()
    assert dialog.key.echoMode() == QLineEdit.Password
    assert dialog.provider.currentData() == "openai"
    assert dialog.model.currentText()
    rename = RenameOptionsDialog(repo, window); assert "重命名选项" in rename.windowTitle()
    rename.close(); dialog.close(); window.close(); app.processEvents()


def test_appearance_selection_and_translated_controls_use_item_data(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    repo = Repository(tmp_path / "data" / "test.db"); repo.initialize()
    repo.save_rule(ClassificationRule(rule_type=RuleType.PREFIX, pattern="IMG_", category="图片", enabled=True, case_sensitive=False))
    password_store = PasswordStore(tmp_path / "passwords.json")
    try:
        set_language("en")
        settings = SettingsDialog(repo, password_store)
        settings.language.setCurrentIndex(settings.language.findData("ja"))
        settings.material.setCurrentIndex(settings.material.findData("dark"))
        settings.extract_mode.setCurrentIndex(settings.extract_mode.findData("temporary"))
        collected = settings.collect()
        assert collected.ui_language == "ja"
        assert collected.material_pack == "dark"
        assert collected.extract_mode == "temporary"
        assert settings.extract_mode.currentText() == "Temporary Folder"

        rename = RenameOptionsDialog(repo)
        preset_index = rename.preset.findData("{category}_{ai_title}")
        rename.preset.setCurrentIndex(preset_index)
        assert rename.template.text() == "{category}_{ai_title}"
        assert rename.preset.currentText() == "Category_AI-Title"

        rules = RuleManagerDialog(repo)
        enabled = rules.table.item(0, 4)
        case_sensitive = rules.table.item(0, 6)
        assert enabled.data(Qt.ItemDataRole.UserRole) is True
        assert case_sensitive.data(Qt.ItemDataRole.UserRole) is False
        # Display text is localized, while persistence logic reads bool roles.
        enabled.setText("not-a-boolean")
        assert rules._item_boolean(enabled) is True

        entry = password_store.add("test-password", "test", persist=False)
        passwords = PasswordManagerDialog(password_store)
        enabled_cell = passwords.table.item(0, 3)
        assert enabled_cell.data(Qt.ItemDataRole.UserRole) is True
        assert entry.id == passwords.table.item(0, 0).text()

        passwords.close(); rules.close(); rename.close(); settings.close(); app.processEvents()
    finally:
        set_language("zh_CN")


def test_scan_to_auto_extract_pipeline(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    inbox = tmp_path / "inbox"; nested = inbox / "one" / "two"; nested.mkdir(parents=True)
    with zipfile.ZipFile(nested / "package.zip", "w") as archive:
        archive.writestr("IMG_inside.txt", "hello")
    repo = Repository(tmp_path / "data" / "test.db"); repo.initialize()
    repo.save_settings(AppSettings(auto_extract=True, rescan_extracted=True, recursive_scan=False))
    window = MainWindow(repo, tmp_path / "application"); window.set_folder(inbox)
    loop = QEventLoop(); poll = QTimer(); poll.setInterval(20)
    def finished():
        if window.thread is None and any(r.archive_status == ArchiveStatus.SUCCESS for r in window.records):
            loop.quit()
    poll.timeout.connect(finished); poll.start(); QTimer.singleShot(5000, loop.quit)
    window.start_scan(); loop.exec(); poll.stop()
    assert any(r.name == "IMG_inside.txt" for r in window.records)
    assert any(r.archive_status == ArchiveStatus.SUCCESS for r in window.records)
    window.close()
    close_loop=QEventLoop();close_poll=QTimer();close_poll.setInterval(20);close_poll.timeout.connect(lambda:close_loop.quit() if window.thread is None else None);close_poll.start();QTimer.singleShot(3000,close_loop.quit);close_loop.exec();close_poll.stop();app.processEvents()


def test_main_window_language_and_material_switch_are_persistent(tmp_path: Path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    repo = Repository(tmp_path / "data" / "test.db"); repo.initialize()
    repo.save_settings(AppSettings(ui_language="en", material_pack="dark"))
    window = MainWindow(repo, tmp_path / "application")
    assert window.action_buttons["扫描"].text() == "Scan"
    assert window.table.horizontalHeaderItem(1).text() == "Original Name"
    assert "#171A1F" in app.styleSheet()

    window.switch_language("ja")
    assert window.action_buttons["扫描"].text() == "スキャン"
    assert repo.load_settings().ui_language == "ja"
    messages=[];monkeypatch.setattr(QMessageBox,"information",lambda _parent,title,message:messages.append((title,message)))
    window.start_scan();assert messages[-1] == ("スキャン","先にフォルダーを選択してください。")
    window.switch_material("ocean")
    assert repo.load_settings().material_pack == "ocean"
    assert "#EAF4F8" in app.styleSheet()

    window.switch_language("zh_CN"); window.switch_material("default")
    window.close(); app.processEvents()


def test_organize_preview_is_mandatory_for_legacy_disabled_setting(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    repo = Repository(tmp_path / "data" / "test.db"); repo.initialize()
    window = MainWindow(repo, tmp_path / "application")
    window.settings.require_confirmation = False
    planned = [(object(), tmp_path / "target.txt")]
    calls = []
    window.build_plan = lambda: planned
    window.preview_dialog = lambda received: calls.append(received) or []
    window.run_task = lambda *_args, **_kwargs: pytest.fail("取消预览后不应执行整理")

    window.execute_organize()

    assert calls == [planned]
    window.close(); app.processEvents()


def test_menu_rebuild_releases_old_actions(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    repo = Repository(tmp_path / "data" / "test.db"); repo.initialize()
    window = MainWindow(repo, tmp_path / "application")
    baseline = len(window.findChildren(__import__("PySide6.QtGui", fromlist=["QAction"]).QAction))
    for index in range(8):
        window.switch_language("en" if index % 2 else "ja")
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete); app.processEvents()
    assert len(window.findChildren(__import__("PySide6.QtGui", fromlist=["QAction"]).QAction)) <= baseline + 2
    window.switch_language("zh_CN"); window.close(); app.processEvents()


def test_scan_and_extract_completion_use_start_settings_snapshot(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    repo = Repository(tmp_path / "data" / "test.db"); repo.initialize()
    window = MainWindow(repo, tmp_path / "application")
    root = tmp_path / "inbox"; root.mkdir(); archive = root / "sample.zip"; archive.write_bytes(b"snapshot")
    now = datetime.now(); record = FileRecord(path=archive,name=archive.name,suffix=".zip",created_at=now,modified_at=now,archive_status=ArchiveStatus.WAITING,scan_root=root)
    binding = ArchiveExtractor.capture_source_binding(archive, root)
    window.task_root=root;window.task_source_roots=[root];window.records=[record]
    window.archive_source_bindings={ArchiveExtractor.source_key(archive):binding}

    repo.save_settings(AppSettings(auto_extract=True,archive_after_extract="move"))
    window.scan_done(([record],False,window.archive_source_bindings,AppSettings(auto_extract=False)))
    assert window.next_task is None

    result=ExtractionResult(archive=archive,status=ArchiveStatus.SUCCESS,format="zip")
    window.extract_done([result],ArchiveExtractor(AppSettings()),AppSettings(archive_after_extract="keep"))
    assert archive.exists() and not (root/"已解压压缩包"/archive.name).exists()
    window.close();app.processEvents()


def test_archive_move_marks_store_so_next_recursive_discovery_skips_it(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    repo = Repository(tmp_path / "data" / "test.db"); repo.initialize()
    window = MainWindow(repo, tmp_path / "application")
    root = tmp_path / "inbox"; nested = root / "a" / "b"; nested.mkdir(parents=True)
    archive = nested / "sample.zip"; archive.write_bytes(b"archive identity")
    binding = ArchiveExtractor.capture_source_binding(archive, root)
    window.task_root = root.resolve(); window.task_source_roots = [root.resolve()]

    moved = window.handle_extracted_archive(
        archive,
        binding,
        AppSettings(archive_after_extract="move"),
    )

    assert moved is not None and moved.exists()
    assert (moved.parent / ".aifo-archive-store").is_file()
    assert FileScanner(protected_roots=[]).discover_archives(root, include_hidden=True) == []
    window.close(); app.processEvents()


def test_archive_move_does_not_take_over_same_named_user_folder(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    repo = Repository(tmp_path / "data" / "test.db"); repo.initialize()
    window = MainWindow(repo, tmp_path / "application")
    root = tmp_path / "inbox"; root.mkdir()
    archive = root / "new.zip"; archive.write_bytes(b"new archive")
    user_folder = root / "已解压压缩包"; user_folder.mkdir()
    user_archive = user_folder / "user-owned.zip"; user_archive.write_bytes(b"user data")
    binding = ArchiveExtractor.capture_source_binding(archive, root)
    window.task_root = root.resolve(); window.task_source_roots = [root.resolve()]

    moved = window.handle_extracted_archive(
        archive,
        binding,
        AppSettings(archive_after_extract="move"),
    )

    assert moved is not None and moved.parent.name == "已解压压缩包 (1)"
    assert user_archive.exists()
    assert not (user_folder / ".aifo-archive-store").exists()
    assert [record.path for record in FileScanner(protected_roots=[]).discover_archives(root)] == [
        user_archive.resolve()
    ]
    window.close(); app.processEvents()


def test_api_configuration_and_async_connection_feedback(tmp_path: Path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    repo = Repository(tmp_path / "data" / "test.db"); repo.initialize()
    dialog = SettingsDialog(repo, PasswordStore(tmp_path / "passwords.json"))
    assert dialog.base.text().startswith("https://")
    assert dialog.model.currentText()
    assert dialog.key.echoMode() == QLineEdit.Password
    dialog.key.setText("test-only-key")
    monkeypatch.setattr(AIClient, "test_connection", lambda _self: ("mock-model", 12))
    loop = QEventLoop(); poll = QTimer(); poll.setInterval(10)
    poll.timeout.connect(lambda: loop.quit() if dialog.test_thread is None else None)
    poll.start(); QTimer.singleShot(2000, loop.quit); dialog.test_api(); loop.exec(); poll.stop()
    assert dialog.test_thread is None
    assert "连接成功" in dialog.api_result.text() and "mock-model" in dialog.api_result.text()
    dialog.close(); app.processEvents()


def test_api_provider_presets_fill_endpoint_and_models(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    repo = Repository(tmp_path / "data" / "test.db"); repo.initialize()
    dialog = SettingsDialog(repo, PasswordStore(tmp_path / "passwords.json"))
    dialog.key.setText("temporary-key")

    deepseek_index = dialog.provider.findData("deepseek")
    dialog.provider.setCurrentIndex(deepseek_index)
    assert dialog.base.text() == "https://api.deepseek.com"
    assert dialog.model.currentText() == "deepseek-v4-flash"
    assert dialog.model.findText("deepseek-v4-pro") >= 0
    assert dialog.key.text() == ""
    assert dialog.provider_docs.isEnabled()

    kimi_index = dialog.provider.findData("kimi_cn")
    dialog.provider.setCurrentIndex(kimi_index)
    assert dialog.base.text() == "https://api.moonshot.cn/v1"
    assert dialog.model.currentText() == "kimi-k2.6"

    dialog.base.setText("http://localhost:11434/v1")
    dialog.base.textEdited.emit(dialog.base.text())
    assert dialog.provider.currentData() == "custom"
    assert dialog.collect().api_base_url == "http://localhost:11434/v1"
    dialog.close(); app.processEvents()


def test_closing_settings_cancels_connection_test_immediately(tmp_path: Path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    repo = Repository(tmp_path / "data" / "test.db"); repo.initialize()
    dialog = SettingsDialog(repo, PasswordStore(tmp_path / "passwords.json"))
    dialog.key.setText("test-only-key")
    started = Event()

    def blocking_test(client):
        started.set()
        while not client._cancel_event.wait(0.01):
            pass
        raise AIRequestCancelled("AI 分析已停止")

    monkeypatch.setattr(AIClient, "test_connection", blocking_test)
    loop = QEventLoop();poll = QTimer();poll.setInterval(10);close_requested = [False]

    def observe():
        if started.is_set() and not close_requested[0]:
            close_requested[0] = True
            dialog.reject()
        if close_requested[0] and dialog.test_thread is None:
            loop.quit()

    poll.timeout.connect(observe);poll.start();QTimer.singleShot(2000,loop.quit)
    before = time.perf_counter();dialog.test_api();loop.exec();elapsed = time.perf_counter() - before
    poll.stop()
    assert close_requested[0] and dialog.test_thread is None and dialog.test_client is None
    assert elapsed < 1
    assert dialog.result() == QDialog.Rejected
    dialog.close();app.processEvents()


def test_main_stop_button_cancels_active_ai_client(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    repo = Repository(tmp_path / "data" / "test.db");repo.initialize()
    window = MainWindow(repo, tmp_path / "application")
    client = AIClient(AppSettings(), "test-key")
    window.active_ai_client = client
    window.stop_task()
    assert client._cancel_event.is_set()
    window.active_ai_client = None
    window.close();app.processEvents()


def test_archive_postprocess_rejects_parent_redirect_before_trash(tmp_path: Path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    repo = Repository(tmp_path / "data" / "test.db");repo.initialize()
    scan_root = tmp_path / "scan";parent = scan_root / "incoming";external = tmp_path / "external"
    parent.mkdir(parents=True);external.mkdir()
    archive = parent / "payload.zip";archive.write_bytes(b"same archive bytes")
    binding = ArchiveExtractor.capture_source_binding(archive, scan_root)
    parent.rename(scan_root / "incoming-original")
    external_archive = external / archive.name;external_archive.write_bytes(b"same archive bytes")
    try:
        os.symlink(external, parent, target_is_directory=True)
    except OSError:
        pytest.skip("当前系统不允许创建目录符号链接")

    called = []
    monkeypatch.setattr(send2trash, "send2trash", lambda _path: called.append(True))
    window = MainWindow(repo, tmp_path / "application")
    window.task_root = scan_root.resolve();window.task_source_roots = [scan_root.resolve()]
    window.settings.archive_after_extract = "trash"
    with pytest.raises(ExtractionBlocked):
        window.handle_extracted_archive(archive, binding)
    assert external_archive.exists() and not called
    window.close();app.processEvents()
