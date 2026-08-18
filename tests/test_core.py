from __future__ import annotations

import zipfile
import io
import tarfile
import errno
from datetime import datetime
from pathlib import Path

from app.core.classifier import RuleClassifier
from app.core.extractor import ArchiveExtractor, safe_member_path
import app.core.organizer as organizer_module
from app.core.organizer import Organizer, file_identity, move_file_no_overwrite, sanitize_filename, unique_path
from app.core.scanner import FileScanner, compound_suffix, filename_prefix
from app.api.client import parse_ai_json
from app.database.repository import Repository
from app.models.schemas import AppSettings, ArchiveStatus, ClassificationRule, FileRecord, OperationRecord, RuleType
from app.utils.paths import application_state_root, ensure_app_dirs, system_protected_roots


def test_scan_and_rule_priority(tmp_path: Path):
    root = tmp_path / "inbox"; root.mkdir()
    (root / "IMG_trip.jpg").write_bytes(b"image")
    (root / "report.pdf").write_bytes(b"pdf")
    records = FileScanner(tmp_path / "application").scan(root)
    rules = [
        ClassificationRule(rule_type=RuleType.EXTENSION, pattern=".jpg", category="扩展图片", priority=500),
        ClassificationRule(rule_type=RuleType.PREFIX, pattern="IMG_", category="旅行照片", priority=100),
    ]
    RuleClassifier(rules).classify_all(records)
    result = {r.name: r for r in records}
    assert result["IMG_trip.jpg"].category == "旅行照片"
    assert result["report.pdf"].category == "待确认"


def test_builtin_rules_and_settings_roundtrip(tmp_path: Path):
    repo = Repository(tmp_path / "db.sqlite"); repo.initialize()
    assert any(r.category == "图片" for r in repo.get_rules())
    settings = AppSettings(recursive_scan=False, auto_extract=True, max_extract_depth=2)
    repo.save_settings(settings)
    assert repo.load_settings().auto_extract is True
    assert repo.load_settings().max_extract_depth == 2


def test_case_sensitive_extension_rule_preserves_case():
    upper = ClassificationRule(
        rule_type=RuleType.EXTENSION,
        pattern=".PDF",
        category="Upper PDF",
        case_sensitive=True,
    )

    assert RuleClassifier.matches(upper, "REPORT.PDF") is True
    assert RuleClassifier.matches(upper, "REPORT.pdf") is False


def test_safe_zip_extract_and_zip_slip_block(tmp_path: Path):
    good = tmp_path / "good.zip"
    with zipfile.ZipFile(good, "w") as archive:
        archive.writestr("folder/IMG_1.txt", "hello")
    extractor = ArchiveExtractor(AppSettings())
    result = extractor.extract(good, [])
    assert result.status == ArchiveStatus.SUCCESS
    assert result.files[0].read_text() == "hello"

    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("../../escape.txt", "bad")
    blocked = extractor.extract(bad, [])
    assert blocked.status == ArchiveStatus.BLOCKED
    assert not (tmp_path / "escape.txt").exists()


def test_organize_and_undo(tmp_path: Path):
    repo = Repository(tmp_path / "db.sqlite"); repo.initialize()
    root = tmp_path / "inbox"; root.mkdir(); source = root / "invoice_1.pdf"; source.write_text("x")
    now = datetime.now()
    record = FileRecord(path=source, name=source.name, suffix=".pdf", size=1, created_at=now, modified_at=now, category="财务", confidence=1)
    organizer = Organizer(repo, AppSettings(rename_template="{category}_{original_name}"))
    plan = organizer.build_plan([record], root, True)
    _, history = organizer.execute(plan, root=root)
    assert history[0].status == "success" and plan[0][1].exists()
    restored, errors = organizer.undo_last()
    assert restored == 1 and not errors and source.exists()


def test_name_and_suffix_helpers(tmp_path: Path):
    assert sanitize_filename('a<b>:c?.txt') == "a_b__c_.txt"
    assert compound_suffix(Path("a.tar.gz")) == ".tar.gz"
    assert safe_member_path(tmp_path, "../outside") is None
    existing = tmp_path / "a.txt"; existing.write_text("x")
    assert unique_path(existing).name == "a (1).txt"
    assert filename_prefix("ABC123_invoice.pdf") == "ABC123_"


def test_scanner_rejects_links_and_preserves_resolved_source_root(tmp_path: Path):
    root = tmp_path / "inbox"; root.mkdir()
    file = root / "normal.txt"; file.write_text("safe")
    records = FileScanner().records_for_paths([file.resolve()], root.resolve())
    assert [record.name for record in records] == ["normal.txt"]
    outside = tmp_path / "outside.txt"; outside.write_text("important")
    link = root / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        return
    assert FileScanner().records_for_paths([link], root) == []


def test_scanner_always_prunes_internal_staging_artifacts(tmp_path: Path):
    root = tmp_path / "inbox"; root.mkdir()
    stage = root / ".aifo_stage_crash"; stage.mkdir()
    (stage / "partial.txt").write_text("unfinished")
    (root / ".aifo-test.partial").write_text("unfinished")
    (root / "normal.txt").write_text("ready")
    records = FileScanner().scan(root, include_hidden=True)
    assert [record.name for record in records] == ["normal.txt"]


def test_excluded_application_roots_are_not_selectable(tmp_path: Path):
    protected = tmp_path / "app-data"; protected.mkdir()
    scanner = FileScanner(excluded_roots=[protected])
    assert scanner.folder_is_protected(protected)
    assert scanner.folder_is_protected(protected / "nested")


def test_tar_7z_and_bomb_limits(tmp_path: Path):
    tar_path = tmp_path / "docs.tar.gz"
    with tarfile.open(tar_path, "w:gz") as archive:
        payload = b"document"
        info = tarfile.TarInfo("inside/readme.txt"); info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    tar_result = ArchiveExtractor(AppSettings()).extract(tar_path, [])
    assert tar_result.status == ArchiveStatus.SUCCESS

    import py7zr
    source = tmp_path / "seven.txt"; source.write_text("seven")
    seven_path = tmp_path / "sample.7z"
    with py7zr.SevenZipFile(seven_path, "w") as archive:
        archive.write(source, "nested/seven.txt")
    seven_result = ArchiveExtractor(AppSettings()).extract(seven_path, [])
    assert seven_result.status == ArchiveStatus.SUCCESS

    bomb = tmp_path / "bomb.zip"
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("zeros.bin", b"0" * 100_000)
    blocked = ArchiveExtractor(AppSettings(max_compression_ratio=2)).extract(bomb, [])
    assert blocked.status == ArchiveStatus.BLOCKED


def test_ai_json_validation():
    result = parse_ai_json('```json\n{"category":"财务","subcategory":"发票","suggested_name":"invoice.pdf","confidence":0.94,"reason":"金额"}\n```')
    assert result.category == "财务" and result.confidence == 0.94


def test_runtime_directories(tmp_path: Path):
    paths = ensure_app_dirs(tmp_path / "portable")
    assert paths.root == tmp_path / "portable"
    assert paths.database.parent.is_dir() and paths.logs.is_dir()


def test_api_settings_validation():
    import pytest
    with pytest.raises(ValueError): AppSettings(api_base_url="file:///tmp/server")
    with pytest.raises(ValueError): AppSettings(api_base_url="https://user:pass@example.com/v1")
    with pytest.raises(ValueError): AppSettings(low_confidence=.9,high_confidence=.5)
    with pytest.raises(ValueError):
        AppSettings(extract_mode="unified", extract_directory=str(application_state_root()))
    protected_roots = system_protected_roots()
    if protected_roots:
        with pytest.raises(ValueError):
            AppSettings(extract_mode="unified", extract_directory=str(protected_roots[0]))


def test_extractor_rechecks_mutated_protected_destination(tmp_path: Path):
    archive = tmp_path / "safe.zip"
    with zipfile.ZipFile(archive, "w") as value:
        value.writestr("inside.txt", "content")
    settings = AppSettings()
    settings.extract_mode = "unified"
    settings.extract_directory = str(application_state_root())
    result = ArchiveExtractor(settings).extract(archive, [])
    assert result.status == ArchiveStatus.BLOCKED


def test_operation_journal_updates_record_and_guards_replacement(tmp_path: Path):
    repo = Repository(tmp_path / "db.sqlite"); repo.initialize()
    root = tmp_path / "inbox"; root.mkdir(); source = root / "report.txt"; source.write_text("trusted")
    now = datetime.now()
    record = FileRecord(path=source, name=source.name, suffix=".txt", size=7,
        created_at=now, modified_at=now, category="文档", confidence=1,
        scan_root=root, relative_parent=Path("."))
    organizer = Organizer(repo, AppSettings())
    _, history = organizer.execute(organizer.build_plan([record], root, False), root=root)
    assert history[0].status == "success"
    assert record.path == history[0].target_path and record.path.exists() and not source.exists()
    stored = repo.last_successful_operation_entries()[0]
    assert stored.status == "success" and stored.expected_size == 7
    assert stored.expected_fingerprint and stored.source_root == root.resolve()

    record.path.write_text("altered")
    restored, errors = organizer.undo_last()
    assert restored == 0 and errors
    assert record.path.read_text() == "altered" and not source.exists()


def test_cross_volume_partial_copy_and_cancel(tmp_path: Path, monkeypatch):
    def no_hard_links(*_args, **_kwargs):
        raise OSError(errno.EXDEV, "simulated cross-volume move")

    monkeypatch.setattr(organizer_module.os, "link", no_hard_links)
    source = tmp_path / "large.bin"; source.write_bytes(b"x" * (2 * 1024 * 1024))
    target = tmp_path / "moved.bin"; partial = tmp_path / ".move.partial"
    move_file_no_overwrite(source, target, partial_path=partial, expected_identity=file_identity(source))
    assert target.stat().st_size == 2 * 1024 * 1024
    assert not source.exists() and not partial.exists()

    cancelled_source = tmp_path / "cancel.bin"; cancelled_source.write_bytes(b"y" * (2 * 1024 * 1024))
    cancelled_target = tmp_path / "cancelled-target.bin"; cancelled_partial = tmp_path / ".cancel.partial"
    import pytest
    with pytest.raises(OSError, match="取消"):
        move_file_no_overwrite(cancelled_source, cancelled_target, stopped=lambda: True,
            partial_path=cancelled_partial, expected_identity=file_identity(cancelled_source))
    assert cancelled_source.exists() and not cancelled_target.exists() and not cancelled_partial.exists()


def test_history_flags_and_keep_structure_are_safe(tmp_path: Path):
    repo = Repository(tmp_path / "db.sqlite"); repo.initialize()
    root = tmp_path / "inbox"; source_dir = root / "文档" / "客户"; source_dir.mkdir(parents=True)
    source = source_dir / "a.txt"; source.write_text("x"); now = datetime.now()
    record = FileRecord(path=source, name=source.name, suffix=".txt", size=1,
        created_at=now, modified_at=now, category="文档", scan_root=root,
        relative_parent=Path("文档") / "客户")
    keep = Organizer(repo, AppSettings(keep_structure=True))
    assert keep.build_plan([record], root, False) == []

    loose = root / "b.txt"; loose.write_text("b")
    second = FileRecord(path=loose, name=loose.name, suffix=".txt", size=1,
        created_at=now, modified_at=now, category="文档", scan_root=root,
        relative_parent=Path("."))
    enabled = Organizer(repo, AppSettings())
    enabled.execute(enabled.build_plan([second], root, False), root=root)
    disabled = Organizer(repo, AppSettings(history_enabled=False, undo_enabled=True))
    restored, errors = disabled.undo_last()
    assert restored == 0 and errors and second.path.exists()


def test_rule_learning_dedup_dismiss_and_builtin_seed_marker(tmp_path: Path):
    repo = Repository(tmp_path / "db.sqlite"); repo.initialize()
    repo.record_manual_choice("ABC_1.pdf", "ABC_", "客户ABC")
    repo.record_manual_choice("ABC_1.pdf", "ABC_", "客户ABC")
    repo.record_manual_choice("ABC_2.pdf", "ABC_", "客户ABC")
    assert repo.learning_suggestion(minimum=3) is None
    repo.record_manual_choice("ABC_3.pdf", "ABC_", "客户ABC")
    assert repo.learning_suggestion(minimum=3) == ("ABC_", "客户ABC", 3)
    repo.dismiss_learning_suggestion("ABC_", "客户ABC")
    assert repo.learning_suggestion(minimum=3) is None

    with repo.connect() as db:
        db.execute("DELETE FROM rules")
    repo.initialize()
    assert repo.get_rules() == []


def test_pending_journal_startup_recovery_is_conservative(tmp_path: Path):
    repo = Repository(tmp_path / "db.sqlite"); repo.initialize()
    root = tmp_path / "inbox"; root.mkdir()
    source = root / "source.txt"; source.write_text("safe")
    target = root / "文档" / "source.txt"
    identity = file_identity(source)
    partial = root / "文档" / ".aifo-test.partial"; partial.parent.mkdir(); partial.write_text("partial")
    pending = OperationRecord(operation_id="pending-1", timestamp=datetime.now(), source_path=source,
        target_path=target, original_name=source.name, new_name=target.name, status="pending")
    repo.begin_operation_item(pending, source_root=root, target_root=root,
        expected_size=identity.size, expected_mtime_ns=identity.mtime_ns,
        expected_fingerprint=identity.fingerprint, partial_path=partial)
    warnings = repo.initialize()
    assert warnings and source.exists() and not target.exists() and not partial.exists()
    with repo.connect() as db:
        assert db.execute("SELECT status FROM operations WHERE operation_id='pending-1'").fetchone()[0] == "failed"

    completed_source = root / "completed.txt"; completed_source.write_text("done")
    completed_target = root / "文档" / "completed.txt"
    completed_identity = file_identity(completed_source)
    completed = OperationRecord(operation_id="pending-2", timestamp=datetime.now(), source_path=completed_source,
        target_path=completed_target, original_name=completed_source.name, new_name=completed_target.name, status="pending")
    repo.begin_operation_item(completed, source_root=root, target_root=root,
        expected_size=completed_identity.size, expected_mtime_ns=completed_identity.mtime_ns,
        expected_fingerprint=completed_identity.fingerprint)
    completed_source.replace(completed_target)
    repo.initialize()
    with repo.connect() as db:
        assert db.execute("SELECT status FROM operations WHERE operation_id='pending-2'").fetchone()[0] == "success"
