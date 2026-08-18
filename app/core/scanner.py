from __future__ import annotations

import ctypes
import mimetypes
import os
import re
import stat as stat_module
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from app.models.schemas import ArchiveStatus, FileRecord

ARCHIVE_SUFFIXES = (".zip", ".7z", ".rar", ".tar", ".tar.gz", ".tgz")
AIFO_ARCHIVE_STORE_MARKER = ".aifo-archive-store"
LOGGER = logging.getLogger(__name__)


def compound_suffix(path: Path) -> str:
    lower = path.name.lower()
    for suffix in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if lower.endswith(suffix):
            return suffix
    return path.suffix.lower()


def filename_prefix(name: str) -> str:
    stem = name
    match = re.match(r"^([A-Za-z0-9\u4e00-\u9fff]+[_\- ]+)", stem)
    return match.group(1) if match else ""


def protected_system_roots() -> list[Path]:
    """Return operating-system locations that must never be organized.

    Hidden/system file filtering is only a convenience setting.  These roots are
    an immutable safety boundary, including when the user enables hidden files.
    """
    if os.name == "nt":
        values = [
            os.environ.get("SystemRoot"),
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
            os.environ.get("ProgramData"),
        ]
    else:
        values = ["/bin", "/boot", "/dev", "/etc", "/lib", "/lib64", "/proc", "/root", "/sbin", "/sys", "/usr", "/var"]
    roots: list[Path] = []
    for value in values:
        if not value:
            continue
        try:
            resolved = Path(value).resolve()
        except OSError:
            continue
        if resolved not in roots:
            roots.append(resolved)
    return roots


def is_hidden_or_system(path: Path) -> bool:
    if path.name.startswith("."):
        return True
    if os.name == "nt":
        try:
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            return attrs != -1 and bool(attrs & (0x2 | 0x4))
        except Exception:
            return False
    return False


def is_aifo_internal_path(path: Path, root: Path | None = None) -> bool:
    """Return whether a path is an unfinished/private AIFO work artifact.

    These names are reserved by the organizer and must never re-enter a scan,
    even when the user explicitly enables hidden/system files.  Otherwise a
    crash during extraction or a cross-volume move could expose a partial file
    as if it were a normal source file.
    """
    try:
        parts = path.relative_to(root).parts if root is not None else path.parts
    except ValueError:
        parts = path.parts
    for part in parts:
        name = part.casefold()
        if (
            name.startswith(".aifo_stage_")
            or name == ".aifo_validation"
            or name.startswith("aifo_extract_")
            or name.startswith(".aifo-extracted-")
            or name == AIFO_ARCHIVE_STORE_MARKER
            or (name.startswith(".aifo-") and name.endswith(".partial"))
        ):
            return True
    return False


def is_aifo_archive_store(directory: Path) -> bool:
    marker = directory / AIFO_ARCHIVE_STORE_MARKER
    try:
        return marker.is_file() and not is_link_or_reparse(marker)
    except OSError:
        return False


def mark_aifo_archive_store(directory: Path, allowed_root: Path) -> Path:
    """Create or validate the private marker used to exclude archived originals."""
    resolved_directory, resolved_root = directory.resolve(), allowed_root.resolve()
    if (
        not directory.is_dir()
        or is_link_or_reparse(directory)
        or not is_within(resolved_directory, resolved_root)
    ):
        raise OSError("原压缩包归档目录不安全")
    marker = directory / AIFO_ARCHIVE_STORE_MARKER
    try:
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if not marker.is_file() or is_link_or_reparse(marker) or marker.resolve().parent != resolved_directory:
            raise OSError("原压缩包归档标记不安全")
    else:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(b"AI File Organizer archive store v1\n")
            handle.flush(); os.fsync(handle.fileno())
    if not is_aifo_archive_store(directory) or directory.resolve() != resolved_directory:
        raise OSError("原压缩包归档目录在创建标记时发生变化")
    return marker


def is_link_or_reparse(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        attrs = getattr(path.lstat(), "st_file_attributes", 0)
        return bool(attrs & getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    except FileNotFoundError:
        return False
    except OSError:
        return True


def is_within(path: Path, root: Path) -> bool:
    try:
        resolved, resolved_root = path.resolve(), root.resolve()
        return resolved == resolved_root or resolved_root in resolved.parents
    except OSError:
        return False


class FileScanner:
    def __init__(self, excluded_root: Path | None = None, *, excluded_roots: list[Path] | None = None,
                 excluded_files: list[Path] | None = None, protected_roots: list[Path] | None = None):
        roots = ([excluded_root] if excluded_root else []) + (excluded_roots or [])
        self.excluded_roots = [p.resolve() for p in roots]
        self.excluded_files = {p.resolve() for p in (excluded_files or [])}
        self.protected_roots = [p.resolve() for p in (protected_roots if protected_roots is not None else protected_system_roots())]

    def _excluded(self, path: Path) -> bool:
        return (
            path in self.excluded_files
            or any(path == root or root in path.parents for root in self.excluded_roots)
            or any(path == root or root in path.parents for root in self.protected_roots)
        )

    def folder_is_protected(self, folder: Path) -> bool:
        try:
            resolved = folder.resolve()
        except OSError:
            return True
        anchor = Path(resolved.anchor).resolve() if resolved.anchor else None
        return (
            bool(anchor and resolved == anchor)
            or any(resolved == root or root in resolved.parents for root in self.protected_roots)
            or any(resolved == root or root in resolved.parents for root in self.excluded_roots)
        )

    def _record(self, path: Path, source_root: Path, include_hidden: bool) -> FileRecord | None:
        try:
            resolved_root = source_root.resolve()
            if is_aifo_internal_path(path, resolved_root):
                return None
            resolved = path.resolve()
            if is_link_or_reparse(path) or not path.is_file() or not is_within(resolved, resolved_root) or self._excluded(resolved):
                return None
            relative = resolved.relative_to(resolved_root)
            if not include_hidden and (is_hidden_or_system(path) or any(p.name.startswith(".") for p in relative.parents)):
                return None
            stat = path.stat()
            suffix = compound_suffix(path)
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            record = FileRecord(path=resolved, name=path.name, suffix=suffix, size=stat.st_size,
                created_at=datetime.fromtimestamp(stat.st_ctime), modified_at=datetime.fromtimestamp(stat.st_mtime),
                prefix=filename_prefix(path.stem), mime_type=mime, scan_root=resolved_root,
                relative_parent=resolved.parent.relative_to(resolved_root))
            if suffix in ARCHIVE_SUFFIXES:
                record.archive_status = ArchiveStatus.WAITING
                record.archive_format = suffix.lstrip(".")
            return record
        except (OSError, PermissionError, ValueError):
            return None

    def records_for_paths(self, paths: list[Path], source_root: Path, include_hidden: bool = False) -> list[FileRecord]:
        source_root = source_root.resolve()
        records: list[FileRecord] = []
        for path in paths:
            record = self._record(path, source_root, include_hidden)
            if record:
                records.append(record)
        return records

    def _candidates(
        self,
        folder: Path,
        *,
        recursive: bool,
        include_hidden: bool,
        stopped: Callable[[], bool] | None,
    ):
        """Yield candidate files without following paths outside ``folder``.

        Directory pruning lives here so normal scanning and the independent
        archive-discovery pass have exactly the same safety boundary.
        """
        if not recursive:
            try:
                yield from folder.iterdir()
            except OSError as exc:
                LOGGER.warning("无法读取目录 %s：%s", folder, exc)
            return

        def onerror(error: OSError):
            LOGGER.warning("扫描目录失败：%s", error)

        for current, dirs, files in os.walk(folder, topdown=True, followlinks=False, onerror=onerror):
            if stopped and stopped():
                return
            current_path = Path(current)
            if is_aifo_archive_store(current_path):
                dirs[:] = []
                continue
            safe_dirs: list[str] = []
            for name in dirs:
                candidate = current_path / name
                if is_aifo_internal_path(candidate, folder):
                    continue
                try:
                    resolved = candidate.resolve()
                except OSError:
                    continue
                if (
                    not is_within(resolved, folder)
                    or self._excluded(resolved)
                    or is_link_or_reparse(candidate)
                    or is_aifo_archive_store(candidate)
                ):
                    continue
                if not include_hidden and is_hidden_or_system(candidate):
                    continue
                safe_dirs.append(name)
            dirs[:] = safe_dirs
            for name in files:
                if stopped and stopped():
                    return
                yield current_path / name

    def discover_archives(
        self,
        folder: Path,
        include_hidden: bool = False,
        stopped: Callable[[], bool] | None = None,
        progress: Callable[[int, str], None] | None = None,
    ) -> list[FileRecord]:
        """Recursively discover archives below ``folder``.

        This preprocessing pass is deliberately independent of the ordinary
        file scan's ``recursive`` option: a selected folder always searches all
        of its descendants for supported archives.  It still respects hidden
        file settings, cancellation, application staging exclusions, protected
        roots, and link/reparse-point boundaries.
        """
        try:
            folder = folder.resolve()
        except OSError:
            return []
        if not folder.is_dir() or self.folder_is_protected(folder) or is_aifo_archive_store(folder):
            if self.folder_is_protected(folder):
                LOGGER.warning("安全拦截：禁止扫描系统目录 %s", folder)
            return []

        records: list[FileRecord] = []
        for path in self._candidates(
            folder,
            recursive=True,
            include_hidden=include_hidden,
            stopped=stopped,
        ):
            if stopped and stopped():
                break
            if compound_suffix(path) not in ARCHIVE_SUFFIXES:
                continue
            record = self._record(path, folder, include_hidden)
            if record is None:
                continue
            records.append(record)
            if progress:
                progress(len(records), path.name)
        return records

    def scan(self, folder: Path, recursive: bool = True, include_hidden: bool = False,
             stopped: Callable[[], bool] | None = None, progress: Callable[[int, str], None] | None = None) -> list[FileRecord]:
        folder = folder.resolve()
        records: list[FileRecord] = []
        if not folder.is_dir() or self.folder_is_protected(folder) or is_aifo_archive_store(folder):
            if self.folder_is_protected(folder):
                LOGGER.warning("安全拦截：禁止扫描系统目录 %s", folder)
            return records
        for path in self._candidates(
            folder,
            recursive=recursive,
            include_hidden=include_hidden,
            stopped=stopped,
        ):
            if stopped and stopped():
                break
            try:
                record = self._record(path, folder, include_hidden)
                if not record:
                    continue
                records.append(record)
                if progress and len(records) % 25 == 0:
                    progress(len(records), path.name)
            except (OSError, PermissionError):
                continue
        return records
