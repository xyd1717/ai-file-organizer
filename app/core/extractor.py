from __future__ import annotations

import logging
import hashlib
import json
import ctypes
import errno
import os
import shutil
import stat
import sys
import tarfile
import tempfile
import threading
import unicodedata
import zipfile
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.core.organizer import FileIdentity, file_identity, identity_matches
from app.core.scanner import ARCHIVE_SUFFIXES, compound_suffix
from app.models.schemas import AppSettings, ArchiveStatus, ExtractionResult
from app.utils.paths import application_state_root, is_protected_location

LOGGER = logging.getLogger(__name__)
COPY_CHUNK_SIZE = 1024 * 1024
FINGERPRINT_SAMPLE_SIZE = 64 * 1024
MAX_MARKER_BYTES = 1024 * 1024
MAX_MEMBER_PATH_CHARS = 32_000
MAX_MEMBER_PART_CHARS = 255
MAX_MEMBER_PARTS = 256
MAX_TOTAL_MEMBER_NAME_CHARS = 4 * 1024 * 1024
MAX_RECURSIVE_ARCHIVES = 10_000
WINDOWS_FORBIDDEN_FILENAME_CHARS = set('<>"|?*')
WINDOWS_DEVICE_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}

try:
    import py7zr
except ImportError:  # pragma: no cover - optional dependency
    py7zr = None
try:
    import rarfile
except ImportError:  # pragma: no cover - optional dependency
    rarfile = None


class ExtractionBlocked(Exception):
    """The archive failed a security or resource-limit check."""


class ExtractionCancelled(Exception):
    """The user cancelled extraction between two bounded writes."""


@dataclass(frozen=True)
class ArchiveSourceBinding:
    """Identity and lexical safety boundary captured before extraction starts."""

    source_root: Path
    archive_path: Path
    identity: FileIdentity


@dataclass(frozen=True)
class _Member:
    name: str
    size: int
    is_dir: bool
    is_file: bool
    is_special: bool = False


class _RuntimeBudget:
    def __init__(self, byte_limit: int, file_limit: int, stopped: Callable[[], bool] | None):
        self.byte_limit = max(int(byte_limit), 0)
        self.file_limit = max(int(file_limit), 0)
        self.stopped = stopped
        self.bytes_written = 0
        self.files_created = 0
        self._lock = threading.Lock()

    def check_cancelled(self) -> None:
        if self.stopped and self.stopped():
            raise ExtractionCancelled("用户已取消")

    def register_file(self) -> None:
        self.check_cancelled()
        with self._lock:
            if self.files_created + 1 > self.file_limit:
                raise ExtractionBlocked("实际解压文件数量超过安全限制")
            self.files_created += 1

    def reserve_growth(self, amount: int) -> None:
        self.check_cancelled()
        if amount <= 0:
            return
        with self._lock:
            if self.bytes_written + amount > self.byte_limit:
                raise ExtractionBlocked("实际解压数据超过安全容量限制")
            self.bytes_written += amount


def find_7zip() -> Path | None:
    """Find a trusted 7-Zip installation without consulting the process PATH."""
    for variable in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(variable)
        if not base:
            continue
        try:
            program_files = Path(base).expanduser()
            if not program_files.is_absolute():
                continue
            resolved_base = program_files.resolve(strict=True)
            candidate = (resolved_base / "7-Zip" / "7z.exe").resolve(strict=True)
            if (
                resolved_base in candidate.parents
                and candidate.is_file()
                and not candidate.is_symlink()
                and not _path_is_reparse(candidate)
            ):
                return candidate
        except (OSError, RuntimeError, ValueError):
            continue
    return None


def _path_is_reparse(path: Path) -> bool:
    try:
        attrs = getattr(path.lstat(), "st_file_attributes", 0)
        return path.is_symlink() or bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    except OSError:
        return True


def _member_parts(member_name: str) -> tuple[str, ...] | None:
    if not isinstance(member_name, str) or not member_name or "\x00" in member_name:
        return None
    normalized = member_name.replace("\\", "/")
    if len(normalized) > MAX_MEMBER_PATH_CHARS:
        return None
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or not pure.parts or len(pure.parts) > MAX_MEMBER_PARTS:
        return None
    parts: list[str] = []
    for part in pure.parts:
        if part in ("", ".", ".."):
            if part == "..":
                return None
            continue
        # Win32 aliases trailing dots/spaces, accepts NTFS ADS after a colon,
        # and treats device names specially. Reject those names everywhere.
        if len(part) > MAX_MEMBER_PART_CHARS or part.rstrip(" .") != part or ":" in part:
            return None
        if any(ord(character) < 32 or character in WINDOWS_FORBIDDEN_FILENAME_CHARS for character in part):
            return None
        device_stem = part.split(".", 1)[0].rstrip(" .").upper()
        if device_stem in WINDOWS_DEVICE_NAMES:
            return None
        parts.append(part)
    return tuple(parts) if parts else None


def safe_member_path(base: Path, member_name: str) -> Path | None:
    parts = _member_parts(member_name)
    if not parts:
        return None
    try:
        resolved_base = base.resolve()
        target = resolved_base.joinpath(*parts).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    return target if resolved_base in target.parents else None


def _collision_key(member_name: str) -> str | None:
    parts = _member_parts(member_name)
    if not parts:
        return None
    return "/".join(unicodedata.normalize("NFC", part).casefold() for part in parts)


def unique_directory(path: Path) -> Path:
    if not os.path.lexists(path):
        return path
    for index in range(1, 10_000):
        candidate = path.with_name(f"{path.name} ({index})")
        if not os.path.lexists(candidate):
            return candidate
    raise OSError("无法生成不重名的解压目录")


def _remove_tree(path: Path) -> None:
    if not os.path.lexists(path):
        return
    if _path_is_reparse(path):
        try:
            if path.is_dir() and not path.is_symlink():
                path.rmdir()
            else:
                path.unlink(missing_ok=True)
        except OSError:
            pass
        return
    if path.is_file():
        try:
            path.chmod(stat.S_IWRITE)
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return

    def make_writeable(function, filename, _error):
        try:
            os.chmod(filename, stat.S_IWRITE)
            function(filename)
        except OSError:
            pass

    shutil.rmtree(path, onerror=make_writeable)


def _rename_directory_no_replace(source: Path, target: Path) -> None:
    """Atomically rename a directory while refusing to replace any target."""
    if os.name == "nt":
        os.rename(source, target)
        return
    source_bytes, target_bytes = os.fsencode(source), os.fsencode(target)
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux"):
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise OSError(errno.ENOTSUP, "系统不支持安全的无覆盖目录发布")
        renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        renameat2.restype = ctypes.c_int
        if renameat2(-100, source_bytes, -100, target_bytes, 1) != 0:  # RENAME_NOREPLACE
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(target))
        return
    if sys.platform == "darwin":
        renamex = getattr(libc, "renamex_np", None)
        if renamex is None:
            raise OSError(errno.ENOTSUP, "系统不支持安全的无覆盖目录发布")
        renamex.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex.restype = ctypes.c_int
        if renamex(source_bytes, target_bytes, 0x00000004) != 0:  # RENAME_EXCL
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(target))
        return
    raise OSError(errno.ENOTSUP, "当前平台不支持安全的无覆盖目录发布")


def _safe_error(error: BaseException, passwords: list[tuple[int, str]]) -> str:
    message = str(error) or type(error).__name__
    for _, password in passwords:
        if password:
            message = message.replace(password, "******")
    return message


def _call_bool(value) -> bool:
    try:
        return bool(value() if callable(value) else value)
    except Exception:
        return False


def _configure_rar_tool() -> Path:
    if rarfile is None:
        raise NotImplementedError("缺少 .rar 解压组件")
    seven_zip = find_7zip()
    if seven_zip is None:
        raise NotImplementedError("未在 Program Files 中检测到可信任的 7-Zip，无法解压 RAR")
    try:
        rarfile.SEVENZIP_TOOL = str(seven_zip)
        rarfile.SEVENZIP2_TOOL = str(seven_zip)
        rarfile.CURRENT_SETUP = rarfile.tool_setup(
            unrar=False,
            unar=False,
            bsdtar=False,
            sevenzip=True,
            sevenzip2=False,
            force=True,
        )
    except Exception as exc:
        raise NotImplementedError("Program Files 中的 7-Zip 不可用，无法解压 RAR") from exc
    return seven_zip


_Py7zIOBase = py7zr.Py7zIO if py7zr is not None else object
_WriterFactoryBase = py7zr.WriterFactory if py7zr is not None else object


class _SafePy7zWriter(_Py7zIOBase):
    def __init__(self, path: Path, budget: _RuntimeBudget):
        self.path = path
        self.budget = budget
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.budget.register_file()
        try:
            self._file = self.path.open("x+b")
        except FileExistsError as exc:
            raise ExtractionBlocked(f"归档成员目标发生重名冲突：{self.path.name}") from exc
        self._maximum_size = 0

    def write(self, data: bytes | bytearray) -> int:
        self.budget.check_cancelled()
        position = self._file.tell()
        growth = max(0, position + len(data) - self._maximum_size)
        self.budget.reserve_growth(growth)
        written = self._file.write(data)
        self._maximum_size = max(self._maximum_size, position + written)
        return written

    def read(self, size: int | None = None) -> bytes:
        return self._file.read(-1 if size is None else size)

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._file.seek(offset, whence)

    def flush(self) -> None:
        self._file.flush()

    def size(self) -> int:
        return self._maximum_size

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()


class _SafePy7zFactory(_WriterFactoryBase):
    def __init__(self, target: Path, budget: _RuntimeBudget):
        self.target = target.resolve()
        self.budget = budget
        self.writers: list[_SafePy7zWriter] = []
        self._lock = threading.Lock()

    def create(self, filename: str):
        candidate = Path(filename)
        if not candidate.is_absolute():
            candidate = self.target / candidate
        try:
            destination = candidate.resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise ExtractionBlocked("7z 成员目标路径无效") from exc
        if self.target not in destination.parents:
            raise ExtractionBlocked("7z 成员试图写出解压目录")
        writer = _SafePy7zWriter(destination, self.budget)
        with self._lock:
            self.writers.append(writer)
        return writer

    def close_all(self) -> None:
        with self._lock:
            writers = list(self.writers)
        for writer in writers:
            try:
                writer.close()
            except OSError:
                pass


class ArchiveExtractor:
    def __init__(self, settings: AppSettings, task_temp_root: Path | None = None):
        self.settings = settings
        self.task_temp_root = task_temp_root
        self._owns_temp_root = task_temp_root is None
        self.task_unpacked = 0
        self.source_bindings: dict[str, ArchiveSourceBinding] = {}

    @staticmethod
    def source_key(path: Path) -> str:
        """Return a case-normalized lexical key without following links."""
        return os.path.normcase(os.path.abspath(os.fspath(path)))

    @classmethod
    def _normalized_allowed_root(cls, source_root: Path) -> Path:
        lexical_root = Path(os.path.abspath(os.fspath(source_root)))
        try:
            if _path_is_reparse(lexical_root) or not lexical_root.is_dir():
                raise ExtractionBlocked("压缩包源根目录是链接、重解析点或已不存在")
            return lexical_root.resolve(strict=True)
        except ExtractionBlocked:
            raise
        except (OSError, RuntimeError) as error:
            raise ExtractionBlocked(f"无法验证压缩包源根目录：{error}") from error

    @classmethod
    def _safe_source_path(cls, archive: Path, source_root: Path) -> tuple[Path, Path]:
        """Validate every component from a bound root to an archive.

        Matching is deliberately lexical first. Resolving ``archive`` before
        containment would let a parent junction redirect a previously scanned
        path into an unrelated directory.
        """
        lexical_root = Path(os.path.abspath(os.fspath(source_root)))
        lexical_archive = Path(os.path.abspath(os.fspath(archive)))
        try:
            relative = lexical_archive.relative_to(lexical_root)
        except ValueError as error:
            raise ExtractionBlocked("压缩包不在允许的扫描目录内") from error
        if not relative.parts:
            raise ExtractionBlocked("压缩包路径不能等于扫描根目录")
        try:
            if _path_is_reparse(lexical_root) or not lexical_root.is_dir():
                raise ExtractionBlocked("压缩包源根目录是链接、重解析点或已不存在")
            resolved_root = lexical_root.resolve(strict=True)
            if cls.source_key(resolved_root) != cls.source_key(lexical_root):
                raise ExtractionBlocked("压缩包源根目录已被重定向")
            current = lexical_root
            for index, part in enumerate(relative.parts):
                current = current / part
                metadata = current.lstat()
                if _path_is_reparse(current):
                    raise ExtractionBlocked("压缩包父目录链包含链接或重解析点")
                if index < len(relative.parts) - 1:
                    if not stat.S_ISDIR(metadata.st_mode):
                        raise ExtractionBlocked("压缩包父路径不是普通目录")
                elif not stat.S_ISREG(metadata.st_mode):
                    raise ExtractionBlocked("压缩包不是安全的普通文件")
            resolved_archive = lexical_archive.resolve(strict=True)
        except ExtractionBlocked:
            raise
        except (OSError, RuntimeError) as error:
            raise ExtractionBlocked(f"无法验证压缩包源路径：{error}") from error
        if cls.source_key(resolved_archive) != cls.source_key(lexical_archive):
            raise ExtractionBlocked("压缩包路径已被父目录链接重定向")
        try:
            resolved_archive.relative_to(resolved_root)
        except ValueError as error:
            raise ExtractionBlocked("压缩包解析后越出允许的扫描目录") from error
        return lexical_archive, lexical_root

    @classmethod
    def capture_source_binding(cls, archive: Path, source_root: Path) -> ArchiveSourceBinding:
        """Capture a stable sampled identity while the lexical path is safe."""
        safe_archive, safe_root = cls._safe_source_path(archive, cls._normalized_allowed_root(source_root))
        try:
            first = file_identity(safe_archive)
            second_archive, second_root = cls._safe_source_path(safe_archive, safe_root)
            second = file_identity(second_archive)
        except ExtractionBlocked:
            raise
        except OSError as error:
            raise ExtractionBlocked(f"无法记录压缩包扫描身份：{error}") from error
        if first != second or cls.source_key(second_root) != cls.source_key(safe_root):
            raise ExtractionBlocked("记录扫描身份期间压缩包发生变化")
        return ArchiveSourceBinding(safe_root, second_archive, second)

    @classmethod
    def validate_source_binding(
        cls,
        binding: ArchiveSourceBinding,
        allowed_source_roots: list[Path] | tuple[Path, ...],
    ) -> Path:
        """Revalidate containment, parent chain, and scan-time identity."""
        lexical_archive = Path(os.path.abspath(os.fspath(binding.archive_path)))
        matching: list[Path] = []
        for candidate in allowed_source_roots:
            lexical_root = cls._normalized_allowed_root(candidate)
            try:
                lexical_archive.relative_to(lexical_root)
            except ValueError:
                continue
            matching.append(lexical_root)
        if not matching:
            raise ExtractionBlocked("压缩包不匹配任何允许的源目录")
        allowed_root = max(matching, key=lambda item: len(item.parts))
        if cls.source_key(allowed_root) != cls.source_key(binding.source_root):
            raise ExtractionBlocked("压缩包绑定的源目录与当前任务不一致")
        safe_archive, safe_root = cls._safe_source_path(binding.archive_path, allowed_root)
        if cls.source_key(safe_archive) != cls.source_key(binding.archive_path):
            raise ExtractionBlocked("压缩包路径与扫描记录不一致")
        if not identity_matches(safe_archive, binding.identity):
            raise ExtractionBlocked("压缩包内容已在扫描后发生变化，请重新扫描")
        return safe_root

    @classmethod
    def binding_for_allowed_roots(
        cls,
        archive: Path,
        allowed_source_roots: list[Path] | tuple[Path, ...],
    ) -> ArchiveSourceBinding:
        """Capture an identity using the longest lexical allowed-root match."""
        lexical_archive = Path(os.path.abspath(os.fspath(archive)))
        matches: list[Path] = []
        for candidate in allowed_source_roots:
            lexical_root = cls._normalized_allowed_root(candidate)
            try:
                lexical_archive.relative_to(lexical_root)
            except ValueError:
                continue
            matches.append(lexical_root)
        if not matches:
            raise ExtractionBlocked("压缩包不匹配任何允许的源目录")
        return cls.capture_source_binding(lexical_archive, max(matches, key=lambda item: len(item.parts)))

    def _temporary_root(self) -> Path:
        if self.task_temp_root is None:
            self.task_temp_root = Path(tempfile.mkdtemp(prefix="aifo_extract_"))
        else:
            self.task_temp_root.mkdir(parents=True, exist_ok=True)
        return self.task_temp_root

    def cleanup_temp(self) -> None:
        """Remove a temporary extraction root owned by this extractor."""
        if self._owns_temp_root and self.task_temp_root is not None:
            _remove_tree(self.task_temp_root)
            self.task_temp_root = None

    def _base_directory(self, archive: Path) -> Path:
        if self.settings.extract_mode == "unified" and self.settings.extract_directory:
            base = Path(self.settings.extract_directory)
        elif self.settings.extract_mode == "temporary":
            base = self._temporary_root()
        else:
            base = archive.parent
        if is_protected_location(base, (application_state_root(),)):
            raise ExtractionBlocked("解压目标位于系统目录、磁盘根目录或应用数据目录")
        base.mkdir(parents=True, exist_ok=True)
        return base.resolve()

    @staticmethod
    def _archive_base_name(archive: Path) -> str:
        base_name = archive.name
        for suffix in sorted(ARCHIVE_SUFFIXES, key=len, reverse=True):
            if base_name.lower().endswith(suffix):
                base_name = base_name[:-len(suffix)]
                break
        return base_name.strip(" .") or "已解压文件"

    def output_directory(self, archive: Path) -> Path:
        base = self._base_directory(archive)
        if not self.settings.create_named_folder:
            return base
        base_name = self._archive_base_name(archive)
        target = base / base_name
        return unique_directory(target) if target.exists() else target

    @staticmethod
    def _archive_fingerprint(archive: Path) -> dict[str, int | str]:
        stat_result = archive.stat()
        size = int(stat_result.st_size)
        sample = hashlib.sha256()
        positions = sorted({
            0,
            max(0, size // 2 - FINGERPRINT_SAMPLE_SIZE // 2),
            max(0, size - FINGERPRINT_SAMPLE_SIZE),
        })
        with archive.open("rb") as stream:
            for position in positions:
                stream.seek(position)
                chunk = stream.read(FINGERPRINT_SAMPLE_SIZE)
                sample.update(position.to_bytes(8, "big", signed=False))
                sample.update(len(chunk).to_bytes(8, "big", signed=False))
                sample.update(chunk)
        final_stat = archive.stat()
        if (
            int(final_stat.st_size) != size
            or int(final_stat.st_mtime_ns) != int(stat_result.st_mtime_ns)
            or int(getattr(final_stat, "st_ino", 0)) != int(getattr(stat_result, "st_ino", 0))
        ):
            raise OSError("读取指纹期间压缩包发生变化")
        return {
            "path": os.path.normcase(str(archive.resolve())),
            "size": size,
            "mtime_ns": int(stat_result.st_mtime_ns),
            "device": int(getattr(stat_result, "st_dev", 0)),
            "inode": int(getattr(stat_result, "st_ino", 0)),
            "sample_sha256": sample.hexdigest(),
        }

    @staticmethod
    def _marker_name(archive: Path) -> str:
        identity = os.path.normcase(str(archive.resolve())).encode("utf-8", "surrogatepass")
        digest = hashlib.sha256(identity).hexdigest()[:24]
        return f".aifo-extracted-{digest}.json"

    @staticmethod
    def _is_reparse(path: Path) -> bool:
        return _path_is_reparse(path)

    def _reuse_marker_candidates(self, archive: Path) -> list[tuple[Path, Path]]:
        base = self._base_directory(archive)
        marker_name = self._marker_name(archive)
        if not self.settings.create_named_folder:
            return [(base / marker_name, base)]
        base_name = self._archive_base_name(archive)
        candidates: list[tuple[Path, Path]] = []
        try:
            children = list(base.iterdir())
        except OSError:
            return candidates
        for child in children:
            if self._is_reparse(child) or not child.is_dir():
                continue
            if child.name == base_name or child.name.startswith(base_name + " ("):
                candidates.append((child / marker_name, child))
        return candidates

    def _reuse_completed(self, archive: Path) -> ExtractionResult | None:
        try:
            fingerprint = self._archive_fingerprint(archive)
        except OSError:
            return None
        for marker, output_dir in self._reuse_marker_candidates(archive):
            try:
                if self._is_reparse(marker):
                    continue
                if marker.stat().st_size > MAX_MARKER_BYTES:
                    continue
                with marker.open("r", encoding="utf-8") as stream:
                    payload = json.loads(stream.read(MAX_MARKER_BYTES + 1))
                if payload.get("version") != 1 or payload.get("archive") != fingerprint:
                    continue
                manifest = payload.get("files")
                if not isinstance(manifest, list) or len(manifest) > self.settings.max_archive_files:
                    continue
                files: list[Path] = []
                valid = True
                unavailable = 0
                for item in manifest:
                    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                        valid = False
                        break
                    path = safe_member_path(output_dir, item["path"])
                    if path is None:
                        valid = False
                        break
                    if not path.exists():
                        unavailable += 1
                        continue
                    if self._is_reparse(path) or not path.is_file():
                        valid = False
                        break
                    if path.stat().st_size == int(item.get("size", -1)):
                        files.append(path)
                    else:
                        unavailable += 1
                if not valid:
                    continue
                warnings = ["检测到相同压缩包的完整解压标记，已跳过重复解压"]
                if unavailable:
                    warnings.append(f"先前解压结果中有 {unavailable} 个文件已移动、缺失或发生变化")
                return ExtractionResult(
                    archive=archive,
                    status=ArchiveStatus.SUCCESS,
                    output_dir=output_dir,
                    files=files,
                    format=str(payload.get("format", compound_suffix(archive).lstrip("."))),
                    encrypted=payload.get("encrypted"),
                    file_count=int(payload.get("file_count", len(files))),
                    unpacked_size=int(payload.get("unpacked_size", sum(path.stat().st_size for path in files))),
                    password_index=payload.get("password_index"),
                    extracted_bytes=int(payload.get("extracted_bytes", 0)),
                    warnings=warnings,
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return None

    def _write_completion_marker(
        self,
        archive: Path,
        output_dir: Path,
        files: list[Path],
        result: ExtractionResult,
        fingerprint: dict[str, int | str],
    ) -> None:
        manifest = []
        resolved_output = output_dir.resolve()
        for path in files:
            resolved = path.resolve()
            if resolved_output not in resolved.parents or self._is_reparse(path) or not path.is_file():
                raise ExtractionBlocked("无法为不安全的解压结果写入完成标记")
            manifest.append({"path": resolved.relative_to(resolved_output).as_posix(), "size": path.stat().st_size})
        payload = {
            "version": 1,
            "archive": fingerprint,
            "format": result.format,
            "encrypted": result.encrypted,
            "file_count": result.file_count,
            "unpacked_size": result.unpacked_size,
            "password_index": result.password_index,
            "extracted_bytes": result.extracted_bytes,
            "files": manifest,
        }
        marker = output_dir / self._marker_name(archive)
        descriptor, temporary_name = tempfile.mkstemp(prefix=marker.name + ".", suffix=".tmp", dir=output_dir)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, marker)
        finally:
            temporary.unlink(missing_ok=True)

    def _check_archive_input(self, archive: Path) -> int:
        try:
            metadata = archive.lstat()
        except OSError:
            raise
        if _path_is_reparse(archive) or not stat.S_ISREG(metadata.st_mode):
            raise ExtractionBlocked("拒绝解压链接、重解析点或非普通文件")
        compressed = int(metadata.st_size)
        if compressed > self.settings.max_task_extract_bytes:
            raise ExtractionBlocked("压缩包本身大小超过整个任务安全限制")
        return compressed

    def _check_limits(self, archive: Path, count: int, unpacked: int) -> None:
        compressed = max(self._check_archive_input(archive), 1)
        if count > self.settings.max_archive_files:
            raise ExtractionBlocked(f"文件数量 {count} 超过限制")
        if unpacked < 0 or unpacked > self.settings.max_archive_unpacked_bytes:
            raise ExtractionBlocked("声明解压大小超过单包限制")
        if unpacked / compressed > self.settings.max_compression_ratio:
            raise ExtractionBlocked("压缩比超过安全限制")
        if self.task_unpacked + unpacked > self.settings.max_task_extract_bytes:
            raise ExtractionBlocked("整个任务预计解压容量超过限制")
        free = shutil.disk_usage(self._base_directory(archive)).free
        if unpacked > free * 0.9:
            raise ExtractionBlocked("可用磁盘空间不足")

    def _inspect_members(self, archive: Path, password: str | None = None) -> tuple[list[_Member], bool | None]:
        suffix = compound_suffix(archive)
        if suffix == ".zip":
            with zipfile.ZipFile(archive) as zf:
                members: list[_Member] = []
                encrypted = False
                for info in zf.infolist():
                    encrypted = encrypted or bool(info.flag_bits & 1)
                    mode = (info.external_attr >> 16) & 0xFFFF
                    is_link = bool(mode and stat.S_ISLNK(mode))
                    special_mode = stat.S_IFMT(mode) if mode else 0
                    is_special = is_link or bool(special_mode and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)))
                    members.append(_Member(info.filename, int(info.file_size), info.is_dir(), not info.is_dir() and not is_special, is_special))
                return members, encrypted
        if suffix in (".tar", ".tar.gz", ".tgz"):
            with tarfile.open(archive, "r:*") as tf:
                members = [
                    _Member(info.name, int(info.size), info.isdir(), info.isfile(), not (info.isdir() or info.isfile()))
                    for info in tf.getmembers()
                ]
                return members, False
        if suffix == ".7z":
            if py7zr is None:
                raise NotImplementedError("缺少 .7z 解压组件")
            with py7zr.SevenZipFile(archive, mode="r", password=password) as zf:
                files = list(zf.files)
                encrypted = _call_bool(getattr(zf, "needs_password", False)) or bool(getattr(zf, "password_protected", False))
                members = []
                for info in files:
                    is_dir = _call_bool(getattr(info, "is_directory", False))
                    special = any(
                        _call_bool(getattr(info, attribute, False))
                        for attribute in ("is_symlink", "is_junction", "is_socket")
                    )
                    is_file = _call_bool(getattr(info, "is_file", not is_dir and not special)) and not special
                    members.append(_Member(str(info.filename), int(getattr(info, "uncompressed", 0) or 0), is_dir, is_file, special or not (is_dir or is_file)))
                return members, encrypted
        if suffix == ".rar":
            _configure_rar_tool()
            with rarfile.RarFile(archive) as rf:
                if password:
                    rf.setpassword(password)
                members = []
                for info in rf.infolist():
                    is_dir = _call_bool(getattr(info, "is_dir", False))
                    is_link = _call_bool(getattr(info, "is_symlink", False)) or bool(getattr(info, "file_redir", None))
                    is_file = _call_bool(getattr(info, "is_file", not is_dir)) and not is_link
                    members.append(_Member(str(info.filename), int(getattr(info, "file_size", 0) or 0), is_dir, is_file, is_link or not (is_dir or is_file)))
                return members, bool(rf.needs_password())
        raise NotImplementedError(f"缺少 {suffix or '未知格式'} 解压组件")

    def inspect(self, archive: Path) -> tuple[int, int, bool | None, list[str]]:
        members, encrypted = self._inspect_members(archive)
        return len(members), sum(member.size for member in members), encrypted, [member.name for member in members]

    @staticmethod
    def _password_required(error: BaseException) -> bool:
        classes: list[type[BaseException]] = []
        if py7zr is not None:
            value = getattr(getattr(py7zr, "exceptions", None), "PasswordRequired", None)
            if isinstance(value, type):
                classes.append(value)
        if rarfile is not None:
            value = getattr(rarfile, "PasswordRequired", None)
            if isinstance(value, type):
                classes.append(value)
        return bool(classes) and isinstance(error, tuple(classes))

    def _inspect_for_extract(
        self, archive: Path, passwords: list[tuple[int, str]], result: ExtractionResult
    ) -> tuple[list[_Member], bool | None, tuple[int | None, str | None] | None] | None:
        try:
            members, encrypted = self._inspect_members(archive)
            return members, encrypted, None
        except Exception as error:
            if not self._password_required(error):
                raise
        result.encrypted = True
        if not passwords:
            result.status, result.error = ArchiveStatus.NEED_PASSWORD, "压缩包需要密码"
            return None
        for password_index, password in passwords:
            try:
                members, encrypted = self._inspect_members(archive, password)
                return members, True if encrypted is None else encrypted, (password_index, password)
            # A header-encrypted archive may reject each configured password;
            # every user-supplied value is intentionally attempted exactly once.
            except Exception:  # nosec B112
                continue
        result.status, result.error = ArchiveStatus.BAD_PASSWORD, "所有已提供密码均失败"
        return None

    def _validate_members(self, target: Path, members: list[_Member]) -> None:
        seen: dict[str, _Member] = {}
        file_keys: set[str] = set()
        total_name_chars = 0
        for member in members:
            total_name_chars += len(member.name)
            if total_name_chars > MAX_TOTAL_MEMBER_NAME_CHARS:
                raise ExtractionBlocked("归档成员名称总长度超过安全限制")
            if member.size < 0:
                raise ExtractionBlocked("归档成员声明了负数大小")
            if member.is_special or not (member.is_dir or member.is_file):
                raise ExtractionBlocked(f"归档包含链接或特殊成员：{member.name}")
            if safe_member_path(target, member.name) is None:
                raise ExtractionBlocked(f"归档包含非法路径：{member.name}")
            key = _collision_key(member.name)
            if key is None:
                raise ExtractionBlocked(f"归档包含非法文件名：{member.name}")
            if key in seen:
                raise ExtractionBlocked(f"归档成员发生重名冲突：{member.name}")
            seen[key] = member
            if member.is_file:
                file_keys.add(key)
        for key, member in seen.items():
            parts = key.split("/")
            for index in range(1, len(parts)):
                if "/".join(parts[:index]) in file_keys:
                    raise ExtractionBlocked(f"归档成员文件/目录冲突：{member.name}")
            if member.is_file and any(other.startswith(key + "/") for other in seen if other != key):
                raise ExtractionBlocked(f"归档成员文件/目录冲突：{member.name}")

    def _runtime_budget(
        self,
        archive: Path,
        target: Path,
        stopped: Callable[[], bool] | None,
    ) -> _RuntimeBudget:
        remaining = max(self.settings.max_task_extract_bytes - self.task_unpacked, 0)
        compressed = max(self._check_archive_input(archive), 1)
        ratio_limit = int(compressed * self.settings.max_compression_ratio)
        try:
            disk_limit = max(0, int(shutil.disk_usage(target).free * 0.9))
        except OSError as exc:
            raise ExtractionBlocked("无法确认解压目标的可用磁盘空间") from exc
        byte_limit = min(
            self.settings.max_archive_unpacked_bytes,
            remaining,
            ratio_limit,
            disk_limit,
        )
        return _RuntimeBudget(byte_limit, self.settings.max_archive_files, stopped)

    @staticmethod
    def _copy_bounded(source, output, budget: _RuntimeBudget) -> None:
        while True:
            budget.check_cancelled()
            chunk = source.read(COPY_CHUNK_SIZE)
            if not chunk:
                return
            budget.reserve_growth(len(chunk))
            output.write(chunk)

    def _extract_once(self, archive: Path, target: Path, password: str | None, budget: _RuntimeBudget) -> None:
        suffix = compound_suffix(archive)
        if suffix == ".zip":
            with zipfile.ZipFile(archive) as zf:
                for info in zf.infolist():
                    budget.check_cancelled()
                    destination = safe_member_path(target, info.filename)
                    if destination is None:
                        raise ExtractionBlocked(f"ZIP 成员路径无效：{info.filename}")
                    if info.is_dir():
                        destination.mkdir(parents=True, exist_ok=True)
                        continue
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    budget.register_file()
                    try:
                        with zf.open(info, pwd=password.encode() if password else None) as source, destination.open("xb") as output:
                            self._copy_bounded(source, output, budget)
                    except FileExistsError as exc:
                        raise ExtractionBlocked(f"ZIP 成员重名：{info.filename}") from exc
            return
        if suffix in (".tar", ".tar.gz", ".tgz"):
            with tarfile.open(archive, "r:*") as tf:
                for info in tf.getmembers():
                    budget.check_cancelled()
                    destination = safe_member_path(target, info.name)
                    if destination is None:
                        raise ExtractionBlocked(f"TAR 成员路径无效：{info.name}")
                    if info.isdir():
                        destination.mkdir(parents=True, exist_ok=True)
                        continue
                    if not info.isfile():
                        raise ExtractionBlocked(f"TAR 包含链接或特殊成员：{info.name}")
                    source = tf.extractfile(info)
                    if source is None:
                        raise tarfile.ExtractError(f"无法读取 TAR 成员：{info.name}")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    budget.register_file()
                    try:
                        with source, destination.open("xb") as output:
                            self._copy_bounded(source, output, budget)
                    except FileExistsError as exc:
                        raise ExtractionBlocked(f"TAR 成员重名：{info.name}") from exc
            return
        if suffix == ".7z" and py7zr is not None:
            for member in self._inspect_members(archive, password)[0]:
                if member.is_dir:
                    destination = safe_member_path(target, member.name)
                    if destination is None:
                        raise ExtractionBlocked(f"7z 成员路径无效：{member.name}")
                    destination.mkdir(parents=True, exist_ok=True)
            factory = _SafePy7zFactory(target, budget)
            try:
                try:
                    with py7zr.SevenZipFile(archive, mode="r", password=password, max_extract_size=budget.byte_limit) as zf:
                        # Every member was validated above and the custom factory
                        # exclusively creates bounded regular files inside target.
                        zf.extractall(path=target, factory=factory)  # nosec B202
                except Exception as error:
                    bomb_error = getattr(getattr(py7zr, "exceptions", None), "DecompressionBombError", None)
                    if isinstance(bomb_error, type) and isinstance(error, bomb_error):
                        raise ExtractionBlocked("7z 实际解压数据超过安全容量限制") from error
                    raise
            finally:
                factory.close_all()
            return
        if suffix == ".rar" and rarfile is not None:
            _configure_rar_tool()
            with rarfile.RarFile(archive) as rf:
                if password:
                    rf.setpassword(password)
                for info in rf.infolist():
                    budget.check_cancelled()
                    destination = safe_member_path(target, str(info.filename))
                    if destination is None:
                        raise ExtractionBlocked(f"RAR 成员路径无效：{info.filename}")
                    if _call_bool(getattr(info, "is_dir", False)):
                        destination.mkdir(parents=True, exist_ok=True)
                        continue
                    if _call_bool(getattr(info, "is_symlink", False)) or bool(getattr(info, "file_redir", None)) or not _call_bool(getattr(info, "is_file", True)):
                        raise ExtractionBlocked(f"RAR 包含链接或特殊成员：{info.filename}")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    budget.register_file()
                    try:
                        with rf.open(info, pwd=password) as source, destination.open("xb") as output:
                            self._copy_bounded(source, output, budget)
                    except FileExistsError as exc:
                        raise ExtractionBlocked(f"RAR 成员重名：{info.filename}") from exc
            return
        raise NotImplementedError(f"缺少 {suffix or '未知格式'} 解压组件")

    @staticmethod
    def _collect_safe_files(target: Path) -> list[Path]:
        resolved_target = target.resolve()
        files: list[Path] = []
        for path in target.rglob("*"):
            try:
                attrs = getattr(path.lstat(), "st_file_attributes", 0)
                reparse = bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
                if path.is_symlink() or reparse:
                    raise ExtractionBlocked(f"解压结果包含链接或重解析点：{path.name}")
                resolved = path.resolve()
                if resolved_target not in resolved.parents:
                    raise ExtractionBlocked("解压结果越出目标目录")
                if path.is_file():
                    files.append(path)
            except OSError as exc:
                raise ExtractionBlocked(f"无法验证解压结果：{path.name}") from exc
        return files

    @staticmethod
    def _unique_merge_target(destination: Path, source: Path) -> Path:
        candidate = destination / source.name
        if not os.path.lexists(candidate):
            return candidate
        for index in range(1, 10_000):
            if source.is_dir():
                candidate = destination / f"{source.name} ({index})"
            else:
                candidate = destination / f"{source.stem} ({index}){source.suffix}"
            if not os.path.lexists(candidate):
                return candidate
        raise OSError(f"无法为 {source.name} 生成安全的不重名路径")

    @staticmethod
    def _published_identity(path: Path) -> tuple[int, int, int]:
        metadata = path.lstat()
        return int(metadata.st_dev), int(metadata.st_ino), int(metadata.st_size)

    @staticmethod
    def _publish_file_no_replace(
        source: Path,
        target: Path,
        stopped: Callable[[], bool] | None,
    ) -> tuple[int, int, int]:
        try:
            os.link(source, target, follow_symlinks=False)
        except FileExistsError:
            raise
        except (OSError, NotImplementedError):
            try:
                source_size = source.stat().st_size
                if source_size > shutil.disk_usage(target.parent).free * 0.9:
                    raise ExtractionBlocked("发布解压结果时可用磁盘空间不足")
                with source.open("rb") as input_stream, target.open("xb") as output_stream:
                    while True:
                        if stopped and stopped():
                            raise ExtractionCancelled("用户已取消")
                        chunk = input_stream.read(COPY_CHUNK_SIZE)
                        if not chunk:
                            break
                        output_stream.write(chunk)
                    output_stream.flush()
                    os.fsync(output_stream.fileno())
            except Exception:
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass
                raise
        return ArchiveExtractor._published_identity(target)

    @staticmethod
    def _rollback_published(entries: list[tuple[str, Path, Path, tuple[int, int, int]]]) -> None:
        for kind, source, target, identity in reversed(entries):
            try:
                if ArchiveExtractor._published_identity(target) != identity:
                    continue
                if kind == "directory":
                    if not os.path.lexists(source):
                        _rename_directory_no_replace(target, source)
                else:
                    target.unlink()
            except OSError:
                # Never delete or overwrite an object whose identity changed.
                continue

    def _merge_staging(
        self,
        staging: Path,
        destination: Path,
        stopped: Callable[[], bool] | None,
    ) -> list[Path]:
        if _path_is_reparse(destination) or not destination.is_dir():
            raise ExtractionBlocked("解压发布目录不是安全的普通目录")
        published: list[tuple[str, Path, Path, tuple[int, int, int]]] = []
        try:
            for source in list(staging.iterdir()):
                for _ in range(10_000):
                    if stopped and stopped():
                        raise ExtractionCancelled("用户已取消")
                    target = self._unique_merge_target(destination, source)
                    try:
                        if source.is_dir() and not _path_is_reparse(source):
                            _rename_directory_no_replace(source, target)
                            published.append(("directory", source, target, self._published_identity(target)))
                        elif source.is_file() and not _path_is_reparse(source):
                            identity = self._publish_file_no_replace(source, target, stopped)
                            published.append(("file", source, target, identity))
                        else:
                            raise ExtractionBlocked("暂存结果包含链接、重解析点或特殊文件")
                        break
                    except FileExistsError:
                        continue
                else:
                    raise OSError(f"无法移动解压结果：{source.name}")
        except Exception:
            self._rollback_published(published)
            raise
        files: list[Path] = []
        try:
            for _, _, target, _ in published:
                if target.is_file():
                    files.append(target)
                elif target.is_dir():
                    files.extend(self._collect_safe_files(target))
                else:
                    raise ExtractionBlocked("发布后的解压结果发生变化")
        except Exception:
            self._rollback_published(published)
            raise
        _remove_tree(staging)
        return files

    def _publish_named_staging(
        self,
        staging: Path,
        desired: Path,
        stopped: Callable[[], bool] | None,
    ) -> tuple[Path, list[Path]]:
        for index in range(10_000):
            if stopped and stopped():
                raise ExtractionCancelled("用户已取消")
            target = desired if index == 0 else desired.with_name(f"{desired.name} ({index})")
            try:
                identity = self._published_identity(staging)
                _rename_directory_no_replace(staging, target)
                try:
                    return target, self._collect_safe_files(target)
                except Exception:
                    if self._published_identity(target) == identity and not os.path.lexists(staging):
                        _rename_directory_no_replace(target, staging)
                    raise
            except FileExistsError:
                continue
        raise OSError("无法生成不重名的解压目录")

    def extract(
        self,
        archive: Path,
        passwords: list[tuple[int, str]],
        stopped: Callable[[], bool] | None = None,
        progress: Callable[[str], None] | None = None,
        *,
        source_binding: ArchiveSourceBinding | None = None,
        allowed_source_roots: list[Path] | tuple[Path, ...] | None = None,
    ) -> ExtractionResult:
        archive = Path(archive)
        suffix = compound_suffix(archive)
        result = ExtractionResult(archive=archive, status=ArchiveStatus.EXTRACTING, format=suffix.lstrip("."))
        working: Path | None = None
        merge_into_base = not self.settings.create_named_folder
        try:
            if stopped and stopped():
                raise ExtractionCancelled("用户已取消")
            roots = tuple(allowed_source_roots or ())
            if source_binding is None:
                roots = roots or (archive.parent,)
                source_binding = self.binding_for_allowed_roots(archive, roots)
            elif self.source_key(archive) != self.source_key(source_binding.archive_path):
                raise ExtractionBlocked("压缩包路径与扫描身份记录不一致")
            roots = roots or (source_binding.source_root,)
            self.validate_source_binding(source_binding, roots)
            archive = source_binding.archive_path
            result.archive = archive
            self.source_bindings[self.source_key(archive)] = source_binding
            reusable = self._reuse_completed(archive)
            if reusable is not None:
                return reusable
            self._check_archive_input(archive)
            initial_fingerprint = self._archive_fingerprint(archive)
            inspected = self._inspect_for_extract(archive, passwords, result)
            if inspected is None:
                return result
            members, encrypted, header_password = inspected
            result.encrypted = encrypted
            count, unpacked = len(members), sum(member.size for member in members)
            result.file_count, result.unpacked_size = count, unpacked
            self._check_limits(archive, count, unpacked)
            self.validate_source_binding(source_binding, roots)
            final_target = self.output_directory(archive)
            base_directory = self._base_directory(archive)
            validation_root = base_directory / ".aifo_validation"
            self._validate_members(validation_root, members)
            # Always extract into an unpredictable same-volume staging
            # directory. Publication is a separate no-replace operation, so
            # failed/cancelled extraction never exposes a partial named folder.
            working = Path(tempfile.mkdtemp(prefix=".aifo_stage_", dir=base_directory))

            if header_password is not None:
                attempts: list[tuple[int | None, str | None]] = [header_password]
            elif encrypted:
                attempts = [(None, None)] + [(index, password) for index, password in passwords]
            else:
                attempts = [(None, None)]

            last_error: BaseException | None = None
            for attempt_no, (password_index, password) in enumerate(attempts, start=1):
                if stopped and stopped():
                    raise ExtractionCancelled("用户已取消")
                if progress:
                    progress(f"密码尝试：{attempt_no} / {len(attempts)}")
                budget = self._runtime_budget(archive, working, stopped)
                try:
                    self._extract_once(archive, working, password, budget)
                    self._collect_safe_files(working)
                    self.validate_source_binding(source_binding, roots)
                    if self._archive_fingerprint(archive) != initial_fingerprint:
                        raise ExtractionBlocked("解压期间压缩包发生变化，已放弃本次结果")
                    if merge_into_base:
                        files = self._merge_staging(working, final_target, stopped)
                    else:
                        final_target, files = self._publish_named_staging(working, final_target, stopped)
                    working = None
                    result.status = ArchiveStatus.SUCCESS
                    result.output_dir = final_target
                    result.password_index = password_index
                    result.files = files
                    result.extracted_bytes = budget.bytes_written
                    self.task_unpacked += budget.bytes_written
                    if budget.bytes_written != unpacked:
                        result.warnings.append(f"声明大小 {unpacked} 字节，实际写入 {budget.bytes_written} 字节")
                    try:
                        self._write_completion_marker(archive, final_target, files, result, initial_fingerprint)
                    except (OSError, ValueError, TypeError, ExtractionBlocked) as marker_error:
                        result.warnings.append(f"无法写入完整解压标记：{marker_error}")
                    LOGGER.info(
                        "压缩包解压成功：%s；使用密码：%s",
                        archive.name,
                        "无密码" if password_index is None else f"密码 #{password_index}",
                    )
                    return result
                except (ExtractionBlocked, ExtractionCancelled):
                    raise
                except Exception as error:
                    last_error = error
                    _remove_tree(working)
                    working = Path(tempfile.mkdtemp(prefix=".aifo_stage_", dir=base_directory))

            _remove_tree(working)
            working = None
            if encrypted:
                result.status = ArchiveStatus.BAD_PASSWORD if passwords else ArchiveStatus.NEED_PASSWORD
                result.error = "所有已提供密码均失败" if passwords else "压缩包需要密码"
            else:
                result.status = ArchiveStatus.FAILED
                result.error = _safe_error(last_error or RuntimeError("解压失败"), passwords)
        except ExtractionCancelled as error:
            if working is not None:
                _remove_tree(working)
            result.status, result.error = ArchiveStatus.FAILED, str(error)
        except ExtractionBlocked as error:
            if working is not None:
                _remove_tree(working)
            result.status, result.error = ArchiveStatus.BLOCKED, str(error)
            result.warnings.append(str(error))
        except NotImplementedError as error:
            if working is not None:
                _remove_tree(working)
            result.status, result.error = ArchiveStatus.UNSUPPORTED, str(error)
        except Exception as error:
            if working is not None:
                _remove_tree(working)
            if rarfile is not None and isinstance(error, getattr(rarfile, "RarCannotExec", ())):
                result.status = ArchiveStatus.UNSUPPORTED
            else:
                result.status = ArchiveStatus.FAILED
            result.error = _safe_error(error, passwords)
        return result

    def extract_recursive(
        self,
        archives: list[Path],
        passwords: list[tuple[int, str]],
        stopped: Callable[[], bool] | None = None,
        progress: Callable[[int, int, str], None] | None = None,
        *,
        allowed_source_roots: list[Path] | tuple[Path, ...] | None = None,
        expected_bindings: dict[Path | str, ArchiveSourceBinding] | None = None,
    ) -> list[ExtractionResult]:
        strict_bindings = expected_bindings is not None or allowed_source_roots is not None
        provided = {
            self.source_key(Path(path)): binding
            for path, binding in (expected_bindings or {}).items()
        }
        initial_roots = tuple(allowed_source_roots or ())
        queue = deque((Path(path), 0, provided.get(self.source_key(Path(path)))) for path in archives)
        results: list[ExtractionResult] = []
        seen: set[str] = set()
        discovered = len(queue)
        while queue:
            if stopped and stopped():
                break
            archive, depth, source_binding = queue.popleft()
            archive_key = self.source_key(archive)
            if archive_key in seen:
                continue
            seen.add(archive_key)
            if progress:
                progress(len(results) + 1, len(results) + len(queue) + 1, archive.name)

            def attempt_progress(message: str, name=archive.name):
                if progress:
                    progress(len(results) + 1, len(results) + len(queue) + 1, f"{name} · {message}")

            try:
                if strict_bindings and source_binding is None:
                    raise ExtractionBlocked("缺少扫描时压缩包身份，已拒绝解压；请重新扫描")
                item_roots: tuple[Path, ...] | None
                if source_binding is not None:
                    if depth == 0 and initial_roots:
                        self.validate_source_binding(source_binding, initial_roots)
                    item_roots = (source_binding.source_root,)
                else:
                    item_roots = None
                result = self.extract(
                    archive,
                    passwords,
                    stopped,
                    attempt_progress,
                    source_binding=source_binding,
                    allowed_source_roots=item_roots,
                )
            except ExtractionBlocked as error:
                result = ExtractionResult(
                    archive=archive,
                    status=ArchiveStatus.BLOCKED,
                    format=compound_suffix(archive).lstrip("."),
                    error=str(error),
                    warnings=[str(error)],
                )
            except Exception as error:  # Last-resort per-archive isolation.
                result = ExtractionResult(
                    archive=archive,
                    status=ArchiveStatus.FAILED,
                    format=compound_suffix(archive).lstrip("."),
                    error=_safe_error(error, passwords),
                )
            result.depth = depth
            results.append(result)
            if result.status != ArchiveStatus.SUCCESS or result.output_dir is None:
                continue
            nested_candidates = [
                path for path in result.files
                if not path.is_symlink() and path.is_file() and compound_suffix(path) in ARCHIVE_SUFFIXES
            ]
            nested: list[tuple[Path, ArchiveSourceBinding]] = []
            for path in nested_candidates:
                try:
                    binding = self.capture_source_binding(path, result.output_dir)
                except (ExtractionBlocked, OSError) as error:
                    result.warnings.append(f"嵌套压缩包身份记录失败：{path.name} - {error}")
                    continue
                self.source_bindings[self.source_key(path)] = binding
                nested.append((path, binding))
            if depth >= self.settings.max_extract_depth:
                continue
            room = max(MAX_RECURSIVE_ARCHIVES - discovered, 0)
            if len(nested) > room:
                result.warnings.append("递归压缩包数量超过安全上限，已停止加入更多嵌套压缩包")
                nested = nested[:room]
            queue.extend((path, depth + 1, binding) for path, binding in nested)
            discovered += len(nested)
        return results
