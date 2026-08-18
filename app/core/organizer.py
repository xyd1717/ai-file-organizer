from __future__ import annotations

import hashlib
import re
import os
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from collections.abc import Callable

from app.database.repository import Repository
from app.models.schemas import AppSettings, FileRecord, OperationRecord
from app.core.scanner import compound_suffix, is_link_or_reparse, is_within

INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
IDENTITY_CHUNK = 64 * 1024


class OperationCancelled(OSError):
    pass


@dataclass(frozen=True)
class FileIdentity:
    size: int
    mtime_ns: int
    fingerprint: str


def file_identity(path: Path) -> FileIdentity:
    """Cheap replacement detection using size plus samples across the file."""
    stat = path.stat()
    size = stat.st_size
    digest = hashlib.sha256()
    digest.update(size.to_bytes(16, "big", signed=False))
    offsets = [0]
    if size > IDENTITY_CHUNK * 2:
        offsets.append(max(0, size // 2 - IDENTITY_CHUNK // 2))
    if size > IDENTITY_CHUNK:
        offsets.append(max(0, size - IDENTITY_CHUNK))
    with path.open("rb") as stream:
        for offset in dict.fromkeys(offsets):
            stream.seek(offset)
            digest.update(offset.to_bytes(16, "big", signed=False))
            digest.update(stream.read(IDENTITY_CHUNK))
    return FileIdentity(size=size, mtime_ns=stat.st_mtime_ns, fingerprint=digest.hexdigest())


def identity_matches(path: Path, expected: FileIdentity) -> bool:
    try:
        actual = file_identity(path)
        return actual.size == expected.size and actual.fingerprint == expected.fingerprint
    except OSError:
        return False


def sanitize_filename(name: str, fallback: str = "file") -> str:
    name = INVALID.sub("_", Path(name).name).strip().rstrip(". ")
    if not name:
        name = fallback
    stem, suffix = Path(name).stem, Path(name).suffix
    if stem.upper() in RESERVED:
        stem = "_" + stem
    return (stem[:180] + suffix[:20]) if len(stem + suffix) > 200 else stem + suffix


def unique_path(path: Path, reserved: set[Path] | None = None) -> Path:
    reserved = reserved or set()
    if not path.exists() and path not in reserved:
        return path
    for index in range(1, 10000):
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists() and candidate not in reserved:
            return candidate
    raise OSError("无法生成不重名的目标文件名")


def original_stem(record: FileRecord) -> str:
    return record.name[:-len(record.suffix)] if record.suffix and record.name.lower().endswith(record.suffix.lower()) else Path(record.name).stem


def _copy_stream(source, target, stopped: Callable[[], bool] | None = None) -> None:
    while True:
        if stopped and stopped():
            raise OperationCancelled("用户已取消")
        chunk = source.read(1024 * 1024)
        if not chunk:
            return
        target.write(chunk)


def _publish_partial(partial: Path, target: Path, stopped: Callable[[], bool] | None = None) -> None:
    """Publish a complete temporary file without replacing an existing target."""
    try:
        os.link(partial, target)
    except FileExistsError:
        raise
    except OSError:
        # Filesystems without hard links still get exclusive creation. This second
        # copy is slower, but it preserves the never-overwrite guarantee.
        created = False
        try:
            with partial.open("rb") as src, target.open("xb") as dst:
                created = True
                _copy_stream(src, dst, stopped)
                dst.flush()
                os.fsync(dst.fileno())
            shutil.copystat(partial, target, follow_symlinks=False)
            partial.unlink()
        except Exception:
            if created:
                target.unlink(missing_ok=True)
            raise
    else:
        try:
            partial.unlink()
        except OSError:
            target.unlink(missing_ok=True)
            raise


def move_file_no_overwrite(
    source: Path,
    target: Path,
    *,
    stopped: Callable[[], bool] | None = None,
    partial_path: Path | None = None,
    expected_identity: FileIdentity | None = None,
) -> None:
    """Move a regular file without overwrite; cross-volume copies use a partial."""
    if is_link_or_reparse(source) or not source.is_file():
        raise OSError("源文件不是安全的普通文件")
    if target.exists() or is_link_or_reparse(target):
        raise FileExistsError(f"目标已存在：{target}")
    try:
        os.link(source, target)
        if expected_identity and not identity_matches(target, expected_identity):
            target.unlink(missing_ok=True)
            raise OSError("源文件在整理期间发生变化")
        try:
            source.unlink()
        except OSError:
            target.unlink(missing_ok=True)
            raise
        return
    except FileExistsError:
        raise
    except OSError:
        pass
    partial = partial_path or target.with_name(f".aifo-{uuid.uuid4().hex}.partial")
    if partial.exists() or is_link_or_reparse(partial):
        raise FileExistsError(f"临时目标已存在：{partial}")
    created_partial = False
    published = False
    try:
        with source.open("rb") as src, partial.open("xb") as dst:
            created_partial = True
            _copy_stream(src, dst, stopped)
            dst.flush()
            os.fsync(dst.fileno())
        shutil.copystat(source, partial, follow_symlinks=False)
        if expected_identity and not identity_matches(partial, expected_identity):
            raise OSError("源文件在复制期间发生变化")
        _publish_partial(partial, target, stopped)
        created_partial = False
        published = True
        if expected_identity and not identity_matches(target, expected_identity):
            raise OSError("目标文件完整性校验失败")
        source.unlink()
    except Exception:
        if published:
            target.unlink(missing_ok=True)
        if created_partial:
            partial.unlink(missing_ok=True)
        raise


def ensure_safe_directory(path: Path, root: Path) -> None:
    root = root.resolve()
    if not is_within(path, root):
        raise PermissionError("目标目录超出允许范围")
    relative = path.resolve(strict=False).relative_to(root)
    current = root
    if is_link_or_reparse(current):
        raise PermissionError("目标根目录是链接或重解析点")
    for part in relative.parts:
        current = current / part
        try:
            current.mkdir()
        except FileExistsError:
            pass
        if is_link_or_reparse(current) or not current.is_dir():
            raise PermissionError(f"不安全的目标目录：{current}")
    if not is_within(current, root):
        raise PermissionError("创建目标目录后检测到路径越界")
class Organizer:
    def __init__(self, repository: Repository, settings: AppSettings):
        self.repository, self.settings = repository, settings

    def rendered_name(self, record: FileRecord, rename: bool) -> str:
        if not rename or not self.settings.allow_rename:
            return sanitize_filename(record.name)
        ai_title = Path(record.suggested_name).stem if record.suggested_name else original_stem(record)
        values = {
            "date": record.modified_at.strftime("%Y-%m-%d"), "year": record.modified_at.strftime("%Y"),
            "month": record.modified_at.strftime("%m"), "category": record.category,
            "original_name": original_stem(record), "ai_title": ai_title, "title": ai_title,
        }
        try:
            stem = self.settings.rename_template.format(**values)
        except (KeyError, ValueError):
            stem = Path(record.name).stem
        return sanitize_filename(stem + record.suffix)

    def build_plan(self, records: list[FileRecord], root: Path, rename: bool,
                   source_roots: list[Path] | None = None) -> list[tuple[FileRecord, Path]]:
        plan, reserved = [], set()
        source_roots = [p.resolve() for p in (source_roots or [root])]
        for record in records:
            if not record.selected or record.category == "待确认":
                continue
            if is_link_or_reparse(record.path) or not any(is_within(record.path, source) for source in source_roots):
                record.status = "安全拦截：源文件不在扫描目录内或是链接"
                continue
            destination_dir = root / sanitize_filename(record.category, "待确认")
            if record.subcategory:
                destination_dir /= sanitize_filename(record.subcategory, "")
            if self.settings.keep_structure:
                try:
                    relative = record.relative_parent or record.path.parent.relative_to(record.scan_root or root)
                    parts = list(relative.parts)
                    for prefix in (record.category, record.subcategory):
                        if prefix and parts and parts[0].casefold() == sanitize_filename(prefix).casefold():
                            parts.pop(0)
                    if parts:
                        destination_dir /= Path(*parts)
                except ValueError:
                    pass
            if not is_within(destination_dir, root):
                record.status = "安全拦截：目标目录越界或是链接"
                continue
            rendered = self.rendered_name(record, rename)
            if record.path.parent.resolve() == destination_dir.resolve() and record.name == rendered:
                record.status = "无需移动"
                continue
            destination = unique_path(destination_dir / rendered, reserved)
            reserved.add(destination)
            record.target_path = destination
            plan.append((record, destination))
        return plan

    @staticmethod
    def _matching_source_root(path: Path, roots: list[Path]) -> Path | None:
        matches = [root.resolve() for root in roots if is_within(path, root)]
        return max(matches, key=lambda item: len(item.parts), default=None)

    @staticmethod
    def _partial_path(target: Path, operation_id: str, index: int, label: str = "move") -> Path:
        return target.parent / f".aifo-{label}-{operation_id[:12]}-{index}.partial"

    def execute(self, plan: list[tuple[FileRecord, Path]], stopped=None, progress=None, root: Path | None = None,
                source_roots: list[Path] | None = None) -> tuple[str, list[OperationRecord]]:
        operation_id = str(uuid.uuid4())
        history: list[OperationRecord] = []
        if root is None and plan:
            recorded_roots = {record.scan_root.resolve() for record, _target in plan if record.scan_root is not None}
            if len(recorded_roots) == 1:
                root = recorded_roots.pop()
        allowed_sources = [item.resolve() for item in (source_roots or ([root] if root else []))]
        for index, (record, target) in enumerate(plan, start=1):
            if stopped and stopped():
                break
            source_path = record.path
            original_name = record.name
            status = "success"
            row_id: int | None = None
            identity: FileIdentity | None = None
            source_root = self._matching_source_root(source_path, allowed_sources)
            partial = self._partial_path(target, operation_id, index)
            cancelled = False
            movement_completed = False
            try:
                pending = OperationRecord(
                    operation_id=operation_id,
                    timestamp=datetime.now(),
                    source_path=source_path,
                    target_path=target,
                    original_name=original_name,
                    new_name=target.name,
                    status="pending",
                )
                if self.settings.history_enabled:
                    row_id = self.repository.begin_operation_item(
                        pending,
                        source_root=source_root,
                        target_root=root,
                        expected_size=record.size,
                        partial_path=partial,
                    )
                if not source_path.exists():
                    raise FileNotFoundError("源文件已不存在")
                if root is None:
                    raise PermissionError("缺少本次整理的安全目标根目录")
                if allowed_sources and source_root is None:
                    raise PermissionError("安全拦截：源文件不在本任务允许范围")
                if root and not is_within(target.parent, root):
                    raise PermissionError("安全拦截：执行时检测到路径越界")
                identity = file_identity(source_path)
                if row_id is not None:
                    self.repository.update_operation_item(
                        row_id,
                        expected_size=identity.size,
                        expected_mtime_ns=identity.mtime_ns,
                        expected_fingerprint=identity.fingerprint,
                    )
                if root:
                    ensure_safe_directory(target.parent, root)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                for _ in range(100):
                    target = unique_path(target)
                    partial = self._partial_path(target, operation_id, index)
                    if row_id is not None:
                        self.repository.update_operation_item(
                            row_id,
                            target_path=target,
                            new_name=target.name,
                            partial_path=partial,
                        )
                    try:
                        move_file_no_overwrite(
                            source_path,
                            target,
                            stopped=stopped,
                            partial_path=partial,
                            expected_identity=identity,
                        )
                        break
                    except FileExistsError:
                        continue
                else:
                    raise FileExistsError("无法生成安全的不重名目标")
                movement_completed = True
                record.status, record.target_path = "整理完成", target
                record.path, record.name, record.suffix = target, target.name, compound_suffix(target)
                try:
                    target_stat = target.stat()
                    record.size = target_stat.st_size
                    record.modified_at = datetime.fromtimestamp(target_stat.st_mtime)
                except OSError:
                    pass
                if root:
                    record.scan_root = root.resolve()
                    try:
                        record.relative_parent = target.parent.resolve().relative_to(root.resolve())
                    except ValueError:
                        record.relative_parent = None
                if row_id is not None:
                    self.repository.update_operation_item(row_id, status="success", error="")
            except (OSError, PermissionError, sqlite3.Error) as exc:
                cancelled = isinstance(exc, OperationCancelled)
                if movement_completed:
                    status, record.status = "pending", f"整理完成，但历史确认失败：{exc}"
                else:
                    status, record.status = "failed", f"失败：{exc}"
                if row_id is not None and not movement_completed:
                    try:
                        self.repository.set_operation_item_status_by_id(row_id, "failed", str(exc))
                    except sqlite3.Error:
                        pass
            history.append(OperationRecord(operation_id=operation_id, timestamp=datetime.now(), source_path=source_path,
                target_path=target, original_name=original_name, new_name=target.name, status=status))
            if progress:
                progress(index, len(plan), original_name)
            if cancelled:
                break
        return operation_id, history

    def undo_preview(self) -> list[tuple[Path, Path]]:
        if not self.settings.history_enabled or not self.settings.undo_enabled:
            return []
        return [(r.target_path, r.source_path) for r in self.repository.last_successful_operation_entries()]

    def undo_last(self, selected_targets: set[Path] | None = None, stopped=None, progress=None) -> tuple[int, list[str]]:
        restored, errors = 0, []
        if not self.settings.history_enabled or not self.settings.undo_enabled:
            return restored, ["操作历史或撤销功能已禁用"]
        records = self.repository.last_successful_operation_entries()
        if not records:
            return restored, errors
        selected_resolved = {path.resolve() for path in selected_targets} if selected_targets is not None else None
        total = len(records)
        for index, record in enumerate(records, start=1):
            if stopped and stopped():
                errors.append("用户已停止撤销；已完成的项目保持已撤销状态")
                break
            if selected_resolved is not None and record.target_path.resolve() not in selected_resolved:
                continue
            undo_started = False
            moved = False
            try:
                if (
                    record.source_root is None
                    or record.target_root is None
                    or record.expected_size is None
                    or not record.expected_fingerprint
                ):
                    raise PermissionError("旧操作缺少安全身份信息，已拒绝自动撤销")
                source_root = record.source_root.resolve()
                target_root = record.target_root.resolve()
                if not source_root.is_dir() or is_link_or_reparse(source_root):
                    raise PermissionError(f"原扫描根目录不安全或已不存在：{source_root}")
                if not target_root.is_dir() or is_link_or_reparse(target_root):
                    raise PermissionError(f"目标根目录不安全或已不存在：{target_root}")
                if not is_within(record.source_path, source_root):
                    raise PermissionError("原位置超出历史记录的源目录")
                if not is_within(record.target_path, target_root):
                    raise PermissionError("当前文件超出历史记录的目标目录")
                if is_link_or_reparse(record.target_path) or not record.target_path.is_file():
                    raise PermissionError("待撤销目标不是安全的普通文件")
                if not record.target_path.exists():
                    raise FileNotFoundError(f"目标已不存在：{record.target_path}")
                if record.source_path.exists():
                    raise FileExistsError(f"原位置已有同名文件：{record.source_path}")
                expected = FileIdentity(
                    size=record.expected_size,
                    mtime_ns=record.expected_mtime_ns or 0,
                    fingerprint=record.expected_fingerprint,
                )
                if not identity_matches(record.target_path, expected):
                    raise PermissionError("目标文件内容已变化，已拒绝撤销以避免移动错误文件")
                ensure_safe_directory(record.source_path.parent, source_root)
                self.repository.set_operation_item_status_by_id(record.row_id, "undo_pending")
                undo_started = True
                partial = self._partial_path(record.source_path, record.operation_id, record.row_id, "undo")
                move_file_no_overwrite(
                    record.target_path,
                    record.source_path,
                    partial_path=partial,
                    expected_identity=expected,
                )
                moved = True
                restored += 1
                self.repository.set_operation_item_status_by_id(record.row_id, "undone")
            except (OSError, sqlite3.Error) as exc:
                errors.append(str(exc))
                if undo_started and not moved:
                    try:
                        self.repository.set_operation_item_status_by_id(record.row_id, "success", str(exc))
                    except sqlite3.Error:
                        pass
            if progress:
                progress(index, total, record.original_name)
        return restored, errors
