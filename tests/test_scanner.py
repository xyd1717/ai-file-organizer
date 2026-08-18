from __future__ import annotations

from pathlib import Path

from app.core.scanner import FileScanner, mark_aifo_archive_store


def test_archive_discovery_is_recursive_when_normal_scan_is_not(tmp_path: Path):
    root = tmp_path / "inbox"
    nested = root / "one" / "two"
    nested.mkdir(parents=True)
    (root / "top.zip").write_bytes(b"not relevant to discovery")
    (nested / "deep.tar.gz").write_bytes(b"not relevant to discovery")
    (nested / "ordinary.txt").write_text("plain")

    scanner = FileScanner(protected_roots=[])
    shallow_names = {record.name for record in scanner.scan(root, recursive=False)}
    archive_names = {record.name for record in scanner.discover_archives(root)}

    assert shallow_names == {"top.zip"}
    assert archive_names == {"top.zip", "deep.tar.gz"}


def test_archive_discovery_respects_hidden_and_internal_staging(tmp_path: Path):
    root = tmp_path / "inbox"
    hidden_dir = root / ".private"
    stage_dir = root / ".aifo_stage_interrupted"
    hidden_dir.mkdir(parents=True)
    stage_dir.mkdir(parents=True)
    (root / ".hidden.zip").write_bytes(b"x")
    (hidden_dir / "inside.7z").write_bytes(b"x")
    (stage_dir / "partial.rar").write_bytes(b"x")
    (root / "visible.tgz").write_bytes(b"x")

    scanner = FileScanner(protected_roots=[])
    assert {r.name for r in scanner.discover_archives(root)} == {"visible.tgz"}
    assert {r.name for r in scanner.discover_archives(root, include_hidden=True)} == {
        ".hidden.zip",
        "inside.7z",
        "visible.tgz",
    }


def test_archive_discovery_prunes_excluded_and_protected_subtrees(tmp_path: Path):
    root = tmp_path / "inbox"
    excluded = root / "excluded"
    protected = root / "protected"
    allowed = root / "allowed"
    for directory in (excluded, protected, allowed):
        directory.mkdir(parents=True)
        (directory / f"{directory.name}.zip").write_bytes(b"x")

    scanner = FileScanner(excluded_roots=[excluded], protected_roots=[protected])
    records = scanner.discover_archives(root)

    assert [record.name for record in records] == ["allowed.zip"]
    assert records[0].scan_root == root.resolve()
    assert records[0].relative_parent == Path("allowed")


def test_archive_discovery_is_cancellable(tmp_path: Path):
    root = tmp_path / "inbox"
    root.mkdir()
    for index in range(10):
        (root / f"{index}.zip").write_bytes(b"x")

    assert FileScanner(protected_roots=[]).discover_archives(root, stopped=lambda: True) == []


def test_archive_discovery_does_not_follow_directory_links(tmp_path: Path):
    root = tmp_path / "inbox"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "escape.rar").write_bytes(b"x")
    link = root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        return

    assert FileScanner(protected_roots=[]).discover_archives(root) == []


def test_marked_archive_store_is_pruned_but_same_named_user_folder_is_not(tmp_path: Path):
    root = tmp_path / "inbox"
    user_folder = root / "已解压压缩包"
    user_folder.mkdir(parents=True)
    archived = user_folder / "already-processed.zip"
    archived.write_bytes(b"x")
    scanner = FileScanner(protected_roots=[])

    # A folder name alone is never reserved; only the private marker opts it out.
    assert [record.path for record in scanner.discover_archives(root)] == [archived.resolve()]

    marker = mark_aifo_archive_store(user_folder, root)
    assert marker.is_file()
    assert scanner.discover_archives(root) == []
    assert scanner.scan(root, recursive=True, include_hidden=True) == []
    assert scanner.scan(user_folder, recursive=True, include_hidden=True) == []


def test_scanner_excludes_packaged_executable_and_usage_guide(tmp_path: Path):
    root = tmp_path / "delivery"
    root.mkdir()
    executable = root / "AI File Organizer.exe"; executable.write_bytes(b"exe")
    usage = root / "USAGE.md"; usage.write_text("guide", encoding="utf-8")
    user_file = root / "notes.txt"; user_file.write_text("keep", encoding="utf-8")
    scanner = FileScanner(excluded_files=[executable, usage], protected_roots=[])

    assert [record.path for record in scanner.scan(root)] == [user_file.resolve()]
