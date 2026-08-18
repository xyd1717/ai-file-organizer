from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

try:
    import keyring
except ImportError:  # pragma: no cover
    keyring = None

LOGGER = logging.getLogger(__name__)
SERVICE = "AIFileOrganizer.ArchivePasswords"


@dataclass
class PasswordEntry:
    id: str
    note: str = ""
    enabled: bool = True
    priority: int = 100


class PasswordStore:
    """Stores only metadata on disk; secrets live in the OS credential backend."""

    def __init__(self, metadata_path: Path):
        self.metadata_path = metadata_path
        self._session_secrets: dict[str, str] = {}

    def list_entries(self) -> list[PasswordEntry]:
        try:
            raw = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            return sorted([PasswordEntry(**item) for item in raw], key=lambda x: x.priority)
        except (FileNotFoundError, ValueError, TypeError):
            return []

    def _save_metadata(self, entries: list[PasswordEntry]) -> None:
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.metadata_path.with_name(f".{self.metadata_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                json.dump([asdict(x) for x in entries], handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            if os.name != "nt":
                temporary.chmod(0o600)
            os.replace(temporary, self.metadata_path)
        finally:
            temporary.unlink(missing_ok=True)

    def backend_available(self) -> bool:
        if keyring is None:
            return False
        try:
            return keyring.get_keyring().priority > 0
        except Exception:
            return False

    def add(self, password: str, note: str = "", enabled: bool = True, priority: int | None = None, persist: bool = True) -> PasswordEntry:
        entries = self.list_entries()
        entry = PasswordEntry(str(uuid.uuid4()), note, enabled, priority if priority is not None else (max([x.priority for x in entries], default=0) + 10))
        stored = False
        if persist and self.backend_available():
            try:
                keyring.set_password(SERVICE, entry.id, password)
                stored = True
            except Exception as exc:
                LOGGER.warning("系统凭据存储无法保存解压密码：%s", exc)
        if not stored:
            self._session_secrets[entry.id] = password
            if persist:
                LOGGER.warning("系统凭据存储不可用；解压密码仅保留到本次运行结束")
        entries.append(entry)
        self._save_metadata(entries)
        return entry

    def update(self, entry: PasswordEntry, new_password: str | None = None) -> None:
        entries = [entry if x.id == entry.id else x for x in self.list_entries()]
        self._save_metadata(entries)
        if new_password is not None:
            if self.backend_available():
                try:
                    keyring.set_password(SERVICE, entry.id, new_password)
                    self._session_secrets.pop(entry.id, None)
                except Exception as exc:
                    self._session_secrets[entry.id] = new_password
                    LOGGER.warning("系统凭据存储无法更新解压密码：%s", exc)
            else:
                self._session_secrets[entry.id] = new_password

    def delete(self, entry_id: str) -> None:
        self._save_metadata([x for x in self.list_entries() if x.id != entry_id])
        self._session_secrets.pop(entry_id, None)
        if self.backend_available():
            try:
                keyring.delete_password(SERVICE, entry_id)
            except Exception as exc:
                LOGGER.debug("系统凭据条目删除失败：%s", type(exc).__name__)

    def enabled_passwords(self) -> list[tuple[int, str]]:
        result: list[tuple[int, str]] = []
        for index, entry in enumerate((x for x in self.list_entries() if x.enabled), start=1):
            secret = self.get_secret(entry.id)
            if secret:
                result.append((index, secret))
        return result

    def get_secret(self, entry_id: str) -> str | None:
        secret = self._session_secrets.get(entry_id)
        if secret is None and self.backend_available():
            try:
                secret = keyring.get_password(SERVICE, entry_id)
            except Exception:
                secret = None
        return secret
