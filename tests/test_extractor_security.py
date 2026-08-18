from __future__ import annotations

import io
import os
import tarfile
import warnings
import zipfile
from dataclasses import replace
from pathlib import Path

import py7zr
import pytest

import app.core.extractor as extractor_module
from app.core.extractor import ArchiveExtractor, find_7zip, safe_member_path
from app.models.schemas import AppSettings, ArchiveStatus


def _zip(path: Path, members: list[tuple[str, bytes]], compression=zipfile.ZIP_STORED) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w", compression=compression) as archive:
            for name, payload in members:
                archive.writestr(name, payload)


def test_bound_archive_rejects_parent_reparse_swap(tmp_path: Path):
    scan_root = tmp_path / "scan"
    original_parent = scan_root / "incoming"
    external_parent = tmp_path / "external"
    original_parent.mkdir(parents=True)
    external_parent.mkdir()
    original_archive = original_parent / "payload.zip"
    _zip(original_archive, [("original.txt", b"original")])
    binding = ArchiveExtractor.capture_source_binding(original_archive, scan_root)

    original_parent.rename(scan_root / "incoming-original")
    external_archive = external_parent / original_archive.name
    _zip(external_archive, [("outside.txt", b"outside")])
    try:
        os.symlink(external_parent, original_parent, target_is_directory=True)
    except OSError:
        pytest.skip("当前系统不允许创建目录符号链接")

    result = ArchiveExtractor(AppSettings()).extract_recursive(
        [original_archive],
        [],
        allowed_source_roots=[scan_root],
        expected_bindings={original_archive: binding},
    )[0]
    assert result.status == ArchiveStatus.BLOCKED
    assert "重解析点" in result.error or "重定向" in result.error
    assert not (external_parent / "payload").exists()


def test_bound_archive_rejects_replacement_after_identity_capture(tmp_path: Path):
    archive = tmp_path / "payload.zip"
    _zip(archive, [("first.txt", b"first")])
    binding = ArchiveExtractor.capture_source_binding(archive, tmp_path)
    archive.unlink()
    _zip(archive, [("other.txt", b"other")])

    result = ArchiveExtractor(AppSettings()).extract_recursive(
        [archive],
        [],
        allowed_source_roots=[tmp_path],
        expected_bindings={archive: binding},
    )[0]
    assert result.status == ArchiveStatus.BLOCKED
    assert "扫描后发生变化" in result.error
    assert not (tmp_path / "payload").exists()


@pytest.mark.parametrize(
    "name",
    [
        "../escape.txt",
        "..\\escape.txt",
        "/absolute.txt",
        "C:\\absolute.txt",
        "dir/file.txt:payload",
        "dir/file.txt::$DATA",
        "dir/NUL.txt",
        "dir/COM1.log",
        "dir/trailing.",
        "dir/trailing ",
    ],
)
def test_member_path_rejects_traversal_ads_devices_and_aliases(tmp_path: Path, name: str):
    assert safe_member_path(tmp_path / "target", name) is None


@pytest.mark.parametrize(
    "names",
    [
        ["same.txt", "same.txt"],
        ["Name.txt", "name.txt"],
        ["dir/", "dir/"],
        ["node", "node/child.txt"],
    ],
)
def test_zip_blocks_duplicate_and_file_directory_conflicts(tmp_path: Path, names: list[str]):
    archive = tmp_path / "conflict.zip"
    _zip(archive, [(name, b"payload") for name in names])

    result = ArchiveExtractor(AppSettings()).extract(archive, [])

    assert result.status == ArchiveStatus.BLOCKED
    assert result.output_dir is None
    assert not (tmp_path / "conflict").exists()


def test_tar_and_7z_links_are_blocked(tmp_path: Path):
    tar_path = tmp_path / "link.tar"
    with tarfile.open(tar_path, "w") as archive:
        link = tarfile.TarInfo("external-link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside"
        archive.addfile(link)
    tar_result = ArchiveExtractor(AppSettings()).extract(tar_path, [])
    assert tar_result.status == ArchiveStatus.BLOCKED

    source = tmp_path / "source.txt"
    source.write_text("safe", encoding="utf-8")
    symlink = tmp_path / "source-link"
    try:
        os.symlink(source, symlink)
    except OSError:
        pytest.skip("当前系统不允许创建符号链接")
    seven_path = tmp_path / "link.7z"
    with py7zr.SevenZipFile(seven_path, "w") as archive:
        archive.write(symlink, "external-link")
    seven_result = ArchiveExtractor(AppSettings()).extract(seven_path, [])
    assert seven_result.status == ArchiveStatus.BLOCKED


def test_invalid_7z_and_rar_do_not_abort_remaining_archives(tmp_path: Path):
    bad_7z = tmp_path / "invalid.7z"
    bad_rar = tmp_path / "invalid.rar"
    bad_7z.write_bytes(b"not a 7z")
    bad_rar.write_bytes(b"not a rar")
    good_zip = tmp_path / "good.zip"
    _zip(good_zip, [("good.txt", b"ok")])

    results = ArchiveExtractor(AppSettings()).extract_recursive([bad_7z, bad_rar, good_zip], [])

    assert results[0].status == ArchiveStatus.FAILED
    assert results[1].status == ArchiveStatus.UNSUPPORTED
    assert "7-Zip" in results[1].error
    assert results[2].status == ArchiveStatus.SUCCESS
    assert results[2].files[0].read_bytes() == b"ok"


def test_7z_encrypted_header_uses_password_list_without_escaping(tmp_path: Path):
    source = tmp_path / "secret.txt"
    source.write_text("secret", encoding="utf-8")
    archive = tmp_path / "encrypted.7z"
    with py7zr.SevenZipFile(archive, "w", password="correct", header_encryption=True) as seven:
        seven.write(source, "secret.txt")

    missing = ArchiveExtractor(AppSettings()).extract(archive, [])
    wrong = ArchiveExtractor(AppSettings()).extract(archive, [(1, "wrong")])
    correct = ArchiveExtractor(AppSettings()).extract(archive, [(1, "wrong"), (2, "correct")])

    assert missing.status == ArchiveStatus.NEED_PASSWORD
    assert wrong.status == ArchiveStatus.BAD_PASSWORD
    assert correct.status == ArchiveStatus.SUCCESS
    assert correct.password_index == 2
    assert correct.files[0].read_text(encoding="utf-8") == "secret"


def test_cancel_is_polled_during_copy_and_partial_output_is_removed(tmp_path: Path):
    archive = tmp_path / "cancel.zip"
    _zip(archive, [("large.bin", b"x" * (4 * 1024 * 1024))])
    polls = 0

    def stopped() -> bool:
        nonlocal polls
        polls += 1
        return polls >= 7

    result = ArchiveExtractor(AppSettings()).extract(archive, [], stopped)

    assert result.status == ArchiveStatus.FAILED
    assert "取消" in result.error
    assert polls >= 7
    assert not (tmp_path / "cancel").exists()


class _UnderreportingExtractor(ArchiveExtractor):
    def _inspect_members(self, archive: Path, password: str | None = None):
        members, encrypted = super()._inspect_members(archive, password)
        return [replace(member, size=min(member.size, 1)) for member in members], encrypted


@pytest.mark.parametrize("extension", ["zip", "7z"])
def test_runtime_byte_limit_blocks_underreported_output(tmp_path: Path, extension: str):
    source = tmp_path / "payload.bin"
    source.write_bytes(b"0" * 4096)
    archive = tmp_path / f"underreported.{extension}"
    if extension == "zip":
        _zip(archive, [("payload.bin", source.read_bytes())], zipfile.ZIP_DEFLATED)
    else:
        with py7zr.SevenZipFile(archive, "w") as seven:
            seven.write(source, "payload.bin")
    settings = AppSettings(max_archive_unpacked_bytes=1024, max_task_extract_bytes=1024)

    result = _UnderreportingExtractor(settings).extract(archive, [])

    assert result.status == ArchiveStatus.BLOCKED
    assert not (tmp_path / "underreported").exists()


def test_no_named_folder_merges_safely_and_completion_marker_is_idempotent(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    existing = inbox / "same.txt"
    existing.write_text("old", encoding="utf-8")
    archive = inbox / "package.zip"
    _zip(archive, [("same.txt", b"new")])
    settings = AppSettings(create_named_folder=False)

    first = ArchiveExtractor(settings).extract(archive, [])
    second = ArchiveExtractor(settings).extract(archive, [])

    assert first.status == ArchiveStatus.SUCCESS
    assert first.output_dir == inbox.resolve()
    assert first.files[0].name == "same (1).txt"
    assert existing.read_text(encoding="utf-8") == "old"
    assert not (tmp_path / "inbox (1)").exists()
    assert second.status == ArchiveStatus.SUCCESS
    assert second.output_dir == first.output_dir
    assert "跳过重复解压" in second.warnings[0]
    assert not (inbox / "same (2).txt").exists()

    # Organized files may have moved away; the atomic receipt still prevents
    # the retained archive from being unpacked again on every rescan.
    first.files[0].unlink()
    third = ArchiveExtractor(settings).extract(archive, [])
    assert third.status == ArchiveStatus.SUCCESS
    assert not (inbox / "same (1).txt").exists()
    assert any("已移动" in warning for warning in third.warnings)


def test_named_folder_completion_marker_requires_same_archive_fingerprint(tmp_path: Path):
    archive = tmp_path / "package.zip"
    _zip(archive, [("one.txt", b"one")])

    first = ArchiveExtractor(AppSettings()).extract(archive, [])
    second = ArchiveExtractor(AppSettings()).extract(archive, [])
    assert first.output_dir == second.output_dir
    assert not (tmp_path / "package (1)").exists()

    _zip(archive, [("two.txt", b"different")])
    changed = ArchiveExtractor(AppSettings()).extract(archive, [])
    assert changed.status == ArchiveStatus.SUCCESS
    assert changed.output_dir != first.output_dir
    assert changed.files[0].name == "two.txt"


def test_temporary_root_is_lazy_and_explicitly_cleanupable(tmp_path: Path):
    archive = tmp_path / "package.zip"
    _zip(archive, [("file.txt", b"data")])
    beside = ArchiveExtractor(AppSettings())
    assert beside.task_temp_root is None
    assert beside.extract(archive, []).status == ArchiveStatus.SUCCESS
    assert beside.task_temp_root is None

    temporary = ArchiveExtractor(AppSettings(extract_mode="temporary"))
    result = temporary.extract(archive, [])
    root = temporary.task_temp_root
    assert result.status == ArchiveStatus.SUCCESS
    assert root is not None and root.exists()
    temporary.cleanup_temp()
    assert temporary.task_temp_root is None
    assert not root.exists()


def test_7zip_discovery_never_uses_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake_path_tool = tmp_path / "bin" / "7z.exe"
    fake_path_tool.parent.mkdir()
    fake_path_tool.write_bytes(b"untrusted")
    monkeypatch.setenv("PATH", str(fake_path_tool.parent))
    for variable in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        monkeypatch.setenv(variable, str(tmp_path / f"missing-{variable}"))
    assert find_7zip() is None

    trusted_root = tmp_path / "Program Files"
    trusted_tool = trusted_root / "7-Zip" / "7z.exe"
    trusted_tool.parent.mkdir(parents=True)
    trusted_tool.write_bytes(b"trusted-location")
    monkeypatch.setenv("ProgramW6432", str(trusted_root))
    assert find_7zip() == trusted_tool.resolve()


def test_runtime_budget_includes_current_disk_space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    archive = tmp_path / "disk.zip"
    _zip(archive, [("payload.bin", b"0" * 4096)], zipfile.ZIP_DEFLATED)

    class TinyDisk:
        total = 100
        used = 0
        free = 100

    monkeypatch.setattr(extractor_module.shutil, "disk_usage", lambda _path: TinyDisk())
    result = _UnderreportingExtractor(
        AppSettings(max_archive_unpacked_bytes=1024, max_task_extract_bytes=1024)
    ).extract(archive, [])
    assert result.status == ArchiveStatus.BLOCKED
    assert "容量" in result.error
    assert not (tmp_path / "disk").exists()


def test_no_named_folder_publish_retries_without_overwriting_racer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    archive = inbox / "race.zip"
    _zip(archive, [("result.txt", b"archive-data")])
    original = ArchiveExtractor._publish_file_no_replace
    raced = False

    def publish(source: Path, target: Path, stopped):
        nonlocal raced
        if not raced:
            target.write_text("concurrent-user-data", encoding="utf-8")
            raced = True
        return original(source, target, stopped)

    monkeypatch.setattr(ArchiveExtractor, "_publish_file_no_replace", staticmethod(publish))
    result = ArchiveExtractor(AppSettings(create_named_folder=False)).extract(archive, [])
    assert result.status == ArchiveStatus.SUCCESS
    assert (inbox / "result.txt").read_text(encoding="utf-8") == "concurrent-user-data"
    assert result.files[0].name == "result (1).txt"
    assert result.files[0].read_bytes() == b"archive-data"


def test_marker_fingerprint_detects_same_size_same_mtime_replacement(tmp_path: Path):
    archive = tmp_path / "same.zip"
    _zip(archive, [("one.txt", b"111")])
    first = ArchiveExtractor(AppSettings()).extract(archive, [])
    original_stat = archive.stat()

    _zip(archive, [("two.txt", b"222")])
    assert archive.stat().st_size == original_stat.st_size
    os.utime(archive, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    changed = ArchiveExtractor(AppSettings()).extract(archive, [])

    assert first.status == changed.status == ArchiveStatus.SUCCESS
    assert changed.output_dir != first.output_dir
    assert changed.files[0].name == "two.txt"


def test_recursive_results_report_depth_and_actual_bytes(tmp_path: Path):
    inner_buffer = io.BytesIO()
    with zipfile.ZipFile(inner_buffer, "w", zipfile.ZIP_DEFLATED) as inner:
        inner.writestr("payload.txt", b"nested payload")
    outer = tmp_path / "outer.zip"
    _zip(outer, [("inner.zip", inner_buffer.getvalue())], zipfile.ZIP_DEFLATED)

    results = ArchiveExtractor(AppSettings(max_extract_depth=1)).extract_recursive([outer], [])
    assert [result.depth for result in results] == [0, 1]
    assert all(result.status == ArchiveStatus.SUCCESS for result in results)
    assert all(result.extracted_bytes > 0 for result in results)

    shallow = ArchiveExtractor(AppSettings(max_extract_depth=0)).extract_recursive([outer], [])
    assert len(shallow) == 1 and shallow[0].depth == 0
