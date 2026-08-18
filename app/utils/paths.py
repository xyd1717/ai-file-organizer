from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
import sys


@dataclass(frozen=True)
class AppPaths:
    root: Path
    data: Path
    logs: Path
    database: Path
    protected_roots: tuple[Path, ...] = ()


def application_state_root() -> Path:
    """Return the per-user writable root reserved for application state."""
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return (base / "AI File Organizer").expanduser().resolve()


def _is_reparse_or_link(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(
            getattr(path.lstat(), "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
    except FileNotFoundError:
        return False
    except OSError:
        return True


def _ensure_state_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if _is_reparse_or_link(path) or not path.is_dir():
        raise OSError(f"应用数据目录不安全：{path}")
    if os.name != "nt":
        path.chmod(0o700)


def system_protected_roots() -> tuple[Path, ...]:
    """Return OS-owned roots that must never be used as an organize source."""
    candidates: list[Path] = []
    if os.name == "nt":
        for name in ("SystemRoot", "WINDIR", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
            value = os.environ.get(name)
            if value:
                candidates.append(Path(value))
    else:
        candidates.extend(Path(item) for item in (
            "/bin", "/boot", "/dev", "/etc", "/lib", "/lib64", "/proc",
            "/root", "/sbin", "/sys", "/usr", "/var",
        ))
    unique: dict[str, Path] = {}
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        unique[os.path.normcase(str(resolved))] = resolved
    return tuple(unique.values())


def is_protected_location(path: Path, extra_roots: tuple[Path, ...] = ()) -> bool:
    """Check a location against drive/filesystem roots and protected subtrees."""
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        return True
    anchor = Path(resolved.anchor).resolve() if resolved.anchor else None
    if anchor is not None and resolved == anchor:
        return True
    for root in (*system_protected_roots(), *extra_roots):
        try:
            protected = Path(root).expanduser().resolve()
            if resolved == protected or protected in resolved.parents:
                return True
        except OSError:
            return True
    return False


def ensure_app_dirs(root: Path | None = None) -> AppPaths:
    frozen = bool(getattr(sys, "frozen", False))
    if root is None:
        root = Path(sys.executable).resolve().parent if frozen else Path(__file__).resolve().parents[2]
    else:
        root = Path(root).expanduser().resolve()
    # A packaged executable may live in Downloads or another shared/writable
    # directory. Keep history/config/logs in the current user's profile even
    # when the EXE directory happens to be writable.
    state_root = application_state_root() if frozen else root
    data, logs = state_root / "data", state_root / "logs"
    try:
        _ensure_state_dir(data)
        _ensure_state_dir(logs)
        probe = data / f".write_test_{os.getpid()}"
        with probe.open("x", encoding="utf-8") as handle:
            handle.write("ok")
        probe.unlink(missing_ok=True)
    except OSError:
        state_root = application_state_root()
        data, logs = state_root / "data", state_root / "logs"
        _ensure_state_dir(data)
        _ensure_state_dir(logs)
    protected = (*system_protected_roots(), data.resolve(), logs.resolve())
    return AppPaths(root, data, logs, data / "organizer.db", protected)
