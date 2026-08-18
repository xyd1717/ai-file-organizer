from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

from app.models.schemas import AppSettings, ClassificationRule, OperationRecord, RuleType


LOGGER = logging.getLogger(__name__)
IDENTITY_CHUNK = 64 * 1024


DEFAULT_EXTENSION_RULES = {
    ".jpg,.jpeg,.png,.webp,.gif,.bmp,.heic": "图片",
    ".mp4,.mov,.mkv,.avi,.webm": "视频",
    ".mp3,.wav,.flac,.aac,.m4a": "音频",
    ".pdf,.docx,.doc,.txt,.md,.rtf": "文档",
    ".xlsx,.xls,.csv,.tsv": "表格",
    ".zip,.7z,.rar,.tar,.tar.gz,.tgz": "压缩包",
    ".exe,.msi,.dmg,.pkg": "安装包",
    ".py,.js,.ts,.tsx,.cpp,.c,.java,.go,.rs": "代码",
}


@dataclass(frozen=True)
class StoredOperation:
    """A persisted move with the safety metadata needed for a guarded undo."""

    row_id: int
    operation_id: str
    timestamp: datetime
    source_path: Path
    target_path: Path
    original_name: str
    new_name: str
    action: str
    status: str
    source_root: Path | None = None
    target_root: Path | None = None
    expected_size: int | None = None
    expected_mtime_ns: int | None = None
    expected_fingerprint: str | None = None
    partial_path: Path | None = None
    error: str = ""


class Repository:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> list[str]:
        recovery_warnings: list[str] = []
        with self.connect() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS rules(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  rule_type TEXT NOT NULL, pattern TEXT NOT NULL, category TEXT NOT NULL,
                  enabled INTEGER NOT NULL DEFAULT 1, priority INTEGER NOT NULL DEFAULT 100,
                  case_sensitive INTEGER NOT NULL DEFAULT 0, builtin INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS settings(
                  key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operations(
                  id INTEGER PRIMARY KEY AUTOINCREMENT, operation_id TEXT NOT NULL,
                  timestamp TEXT NOT NULL, source_path TEXT NOT NULL, target_path TEXT NOT NULL,
                  original_name TEXT NOT NULL, new_name TEXT NOT NULL,
                  action TEXT NOT NULL, status TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_operations_id ON operations(operation_id);
                CREATE TABLE IF NOT EXISTS manual_choices(
                  id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL,
                  prefix TEXT NOT NULL, category TEXT NOT NULL, timestamp TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS api_usage(
                  id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
                  files INTEGER NOT NULL, input_tokens INTEGER, output_tokens INTEGER,
                  estimated_cost REAL
                );
                CREATE TABLE IF NOT EXISTS learning_dismissals(
                  prefix TEXT NOT NULL, category TEXT NOT NULL, timestamp TEXT NOT NULL,
                  PRIMARY KEY(prefix,category)
                );
                """
            )
            self._migrate_operations(db)
            recovery_warnings.extend(self._recover_pending_operations(db))
            db.execute(
                """
                DELETE FROM manual_choices
                WHERE id NOT IN (
                  SELECT MIN(id) FROM manual_choices GROUP BY filename,prefix,category
                )
                """
            )
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_manual_choice_unique "
                "ON manual_choices(filename,prefix,category)"
            )
            seeded = db.execute("SELECT 1 FROM settings WHERE key='builtin_rules_seeded_v1'").fetchone()
            count = db.execute("SELECT COUNT(*) FROM rules").fetchone()[0]
            if not seeded and count == 0:
                for index, (pattern, category) in enumerate(DEFAULT_EXTENSION_RULES.items()):
                    db.execute(
                        "INSERT INTO rules(rule_type,pattern,category,enabled,priority,case_sensitive,builtin) VALUES(?,?,?,?,?,?,?)",
                        (RuleType.EXTENSION.value, pattern, category, 1, 500 + index, 0, 1),
                    )
            if not seeded:
                db.execute("INSERT INTO settings(key,value) VALUES('builtin_rules_seeded_v1','1')")
        for warning in recovery_warnings:
            LOGGER.warning(warning)
        return recovery_warnings

    @staticmethod
    def _migrate_operations(db: sqlite3.Connection) -> None:
        """Add safety fields without invalidating databases created by earlier V1 builds."""
        existing = {row["name"] for row in db.execute("PRAGMA table_info(operations)")}
        columns = {
            "source_root": "TEXT",
            "target_root": "TEXT",
            "expected_size": "INTEGER",
            "expected_mtime_ns": "INTEGER",
            "expected_fingerprint": "TEXT",
            "partial_path": "TEXT",
            "error": "TEXT NOT NULL DEFAULT ''",
        }
        for name, declaration in columns.items():
            if name not in existing:
                db.execute(f"ALTER TABLE operations ADD COLUMN {name} {declaration}")
        db.execute("CREATE INDEX IF NOT EXISTS idx_operations_status ON operations(status,id)")

    @staticmethod
    def _fingerprint(path: Path) -> tuple[int, str]:
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
        return size, digest.hexdigest()

    @classmethod
    def _matches_expected(cls, path: Path, row: sqlite3.Row) -> bool:
        if row["expected_size"] is None or not row["expected_fingerprint"]:
            return False
        try:
            size, fingerprint = cls._fingerprint(path)
            return size == row["expected_size"] and fingerprint == row["expected_fingerprint"]
        except OSError:
            return False

    @staticmethod
    def _safe_partial(partial: Path | None, root: Path | None) -> bool:
        if partial is None or root is None or not partial.name.startswith(".aifo-") or not partial.name.endswith(".partial"):
            return False
        try:
            resolved, resolved_root = partial.resolve(), root.resolve()
            return (
                partial.is_file()
                and not partial.is_symlink()
                and (resolved == resolved_root or resolved_root in resolved.parents)
            )
        except OSError:
            return False

    @classmethod
    def _recover_pending_operations(cls, db: sqlite3.Connection) -> list[str]:
        """Reconcile interrupted rows without moving user files or guessing ownership."""
        warnings: list[str] = []
        rows = db.execute(
            "SELECT * FROM operations WHERE status IN ('pending','undo_pending') ORDER BY id"
        ).fetchall()
        for row in rows:
            source = Path(row["source_path"])
            target = Path(row["target_path"])
            source_ok = source.is_file() and not source.is_symlink() and cls._matches_expected(source, row)
            target_ok = target.is_file() and not target.is_symlink() and cls._matches_expected(target, row)
            source_exists, target_exists = source.exists(), target.exists()
            identity_not_recorded = row["expected_size"] is None or not row["expected_fingerprint"]
            status, message = "recovery_required", "启动恢复无法安全判断文件状态，需要人工检查"
            if row["status"] == "pending":
                if source_exists and not target_exists and (source_ok or identity_not_recorded):
                    status, message = "failed", "启动恢复：源文件仍在，整理未完成"
                elif not source_exists and target_exists and target_ok:
                    status, message = "success", "启动恢复：确认整理已完成"
                elif source_exists and target_exists:
                    message = "启动恢复发现源和目标同时存在，未自动删除任何文件"
                elif not source_exists and not target_exists:
                    message = "启动恢复发现源和目标均不存在，保留残留文件供人工检查"
                else:
                    message = "启动恢复发现文件身份不匹配，需要人工检查"
                authoritative_copy = source_ok or (source_exists and identity_not_recorded) or target_ok
                partial_root = Path(row["target_root"]) if row["target_root"] else None
            else:
                if source_exists and source_ok and not target_exists:
                    status, message = "undone", "启动恢复：确认撤销已完成"
                elif not source_exists and target_exists and target_ok:
                    status, message = "success", "启动恢复：撤销未发生，原整理记录仍有效"
                elif source_exists and target_exists:
                    message = "启动恢复发现撤销前后文件同时存在，未自动删除任何文件"
                elif not source_exists and not target_exists:
                    message = "启动恢复发现撤销前后文件均不存在，需要人工检查"
                else:
                    message = "启动恢复发现撤销文件身份不匹配，需要人工检查"
                authoritative_copy = source_ok or target_ok
                partial_root = Path(row["source_root"]) if row["source_root"] else None

            partial = Path(row["partial_path"]) if row["partial_path"] else None
            if authoritative_copy and cls._safe_partial(partial, partial_root):
                try:
                    partial.unlink()
                except OSError as exc:
                    message += f"；残留临时文件无法删除：{exc}"
            db.execute("UPDATE operations SET status=?,error=? WHERE id=?", (status, message, row["id"]))
            warnings.append(f"操作 {row['operation_id']} / {row['original_name']}：{message}")
        return warnings

    def get_rules(self) -> list[ClassificationRule]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM rules ORDER BY priority ASC,id ASC").fetchall()
        return [ClassificationRule(id=r["id"], rule_type=r["rule_type"], pattern=r["pattern"], category=r["category"], enabled=bool(r["enabled"]), priority=r["priority"], case_sensitive=bool(r["case_sensitive"]), builtin=bool(r["builtin"])) for r in rows]

    def save_rule(self, rule: ClassificationRule) -> int:
        with self.connect() as db:
            values = (rule.rule_type.value, rule.pattern, rule.category, int(rule.enabled), rule.priority, int(rule.case_sensitive), int(rule.builtin))
            if rule.id:
                db.execute("UPDATE rules SET rule_type=?,pattern=?,category=?,enabled=?,priority=?,case_sensitive=?,builtin=? WHERE id=?", values + (rule.id,))
                return rule.id
            cursor = db.execute("INSERT INTO rules(rule_type,pattern,category,enabled,priority,case_sensitive,builtin) VALUES(?,?,?,?,?,?,?)", values)
            return int(cursor.lastrowid)

    def delete_rule(self, rule_id: int) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM rules WHERE id=?", (rule_id,))

    def load_settings(self) -> AppSettings:
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key='app'").fetchone()
        if not row:
            return AppSettings()
        try:
            return AppSettings.model_validate_json(row[0])
        except Exception:
            return AppSettings()

    def save_settings(self, settings: AppSettings) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO settings(key,value) VALUES('app',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (settings.model_dump_json(),))

    def add_operations(self, records: list[OperationRecord]) -> None:
        if not records:
            return
        with self.connect() as db:
            db.executemany(
                "INSERT INTO operations(operation_id,timestamp,source_path,target_path,original_name,new_name,action,status) VALUES(?,?,?,?,?,?,?,?)",
                [(r.operation_id, r.timestamp.isoformat(), str(r.source_path), str(r.target_path), r.original_name, r.new_name, r.action, r.status) for r in records],
            )

    def begin_operation_item(
        self,
        record: OperationRecord,
        *,
        source_root: Path | None,
        target_root: Path | None,
        expected_size: int | None = None,
        expected_mtime_ns: int | None = None,
        expected_fingerprint: str | None = None,
        partial_path: Path | None = None,
    ) -> int:
        """Durably write a pending row before the corresponding filesystem mutation."""
        with self.connect() as db:
            cursor = db.execute(
                """
                INSERT INTO operations(
                  operation_id,timestamp,source_path,target_path,original_name,new_name,action,status,
                  source_root,target_root,expected_size,expected_mtime_ns,expected_fingerprint,partial_path,error
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    record.operation_id,
                    record.timestamp.isoformat(),
                    str(record.source_path),
                    str(record.target_path),
                    record.original_name,
                    record.new_name,
                    record.action,
                    "pending",
                    str(source_root) if source_root else None,
                    str(target_root) if target_root else None,
                    expected_size,
                    expected_mtime_ns,
                    expected_fingerprint,
                    str(partial_path) if partial_path else None,
                    "",
                ),
            )
            return int(cursor.lastrowid)

    def update_operation_item(
        self,
        row_id: int,
        *,
        status: str | None = None,
        target_path: Path | None = None,
        new_name: str | None = None,
        expected_size: int | None = None,
        expected_mtime_ns: int | None = None,
        expected_fingerprint: str | None = None,
        partial_path: Path | None = None,
        error: str | None = None,
    ) -> None:
        fields = {
            "status": status,
            "target_path": str(target_path) if target_path is not None else None,
            "new_name": new_name,
            "expected_size": expected_size,
            "expected_mtime_ns": expected_mtime_ns,
            "expected_fingerprint": expected_fingerprint,
            "partial_path": str(partial_path) if partial_path is not None else None,
            "error": error,
        }
        selected = [(name, value) for name, value in fields.items() if value is not None]
        if not selected:
            return
        statements = {
            "status": "UPDATE operations SET status=? WHERE id=?",
            "target_path": "UPDATE operations SET target_path=? WHERE id=?",
            "new_name": "UPDATE operations SET new_name=? WHERE id=?",
            "expected_size": "UPDATE operations SET expected_size=? WHERE id=?",
            "expected_mtime_ns": "UPDATE operations SET expected_mtime_ns=? WHERE id=?",
            "expected_fingerprint": "UPDATE operations SET expected_fingerprint=? WHERE id=?",
            "partial_path": "UPDATE operations SET partial_path=? WHERE id=?",
            "error": "UPDATE operations SET error=? WHERE id=?",
        }
        with self.connect() as db:
            for name, value in selected:
                db.execute(statements[name], (value, row_id))

    def set_operation_item_status_by_id(self, row_id: int, status: str, error: str = "") -> None:
        with self.connect() as db:
            db.execute("UPDATE operations SET status=?,error=? WHERE id=?", (status, error, row_id))

    @staticmethod
    def _stored_operation(row: sqlite3.Row) -> StoredOperation:
        return StoredOperation(
            row_id=int(row["id"]),
            operation_id=row["operation_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            source_path=Path(row["source_path"]),
            target_path=Path(row["target_path"]),
            original_name=row["original_name"],
            new_name=row["new_name"],
            action=row["action"],
            status=row["status"],
            source_root=Path(row["source_root"]) if row["source_root"] else None,
            target_root=Path(row["target_root"]) if row["target_root"] else None,
            expected_size=row["expected_size"],
            expected_mtime_ns=row["expected_mtime_ns"],
            expected_fingerprint=row["expected_fingerprint"],
            partial_path=Path(row["partial_path"]) if row["partial_path"] else None,
            error=row["error"] or "",
        )

    def last_successful_operation_entries(self) -> list[StoredOperation]:
        with self.connect() as db:
            row = db.execute("SELECT operation_id FROM operations WHERE status='success' ORDER BY id DESC LIMIT 1").fetchone()
            if not row:
                return []
            rows = db.execute(
                "SELECT * FROM operations WHERE operation_id=? AND status='success' ORDER BY id DESC",
                (row[0],),
            ).fetchall()
        return [self._stored_operation(item) for item in rows]

    def last_successful_operation(self) -> list[OperationRecord]:
        return [
            OperationRecord(
                operation_id=row.operation_id,
                timestamp=row.timestamp,
                source_path=row.source_path,
                target_path=row.target_path,
                original_name=row.original_name,
                new_name=row.new_name,
                action=row.action,
                status=row.status,
            )
            for row in self.last_successful_operation_entries()
        ]

    def update_operation_status(self, operation_id: str, status: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE operations SET status=? WHERE operation_id=?", (status, operation_id))

    def update_operation_item_status(self, operation_id: str, target_path: Path, status: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE operations SET status=? WHERE operation_id=? AND target_path=?", (status, operation_id, str(target_path)))

    def record_manual_choice(self, filename: str, prefix: str, category: str) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO manual_choices(filename,prefix,category,timestamp) VALUES(?,?,?,?)",
                (filename, prefix, category, datetime.now().isoformat()),
            )

    def learning_suggestion(self, minimum: int = 3) -> tuple[str, str, int] | None:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT m.prefix,m.category,COUNT(DISTINCT m.filename) n
                FROM manual_choices m
                WHERE m.prefix<>'' AND NOT EXISTS(
                  SELECT 1 FROM learning_dismissals d
                  WHERE lower(d.prefix)=lower(m.prefix) AND d.category=m.category
                )
                GROUP BY lower(m.prefix),m.category
                HAVING COUNT(DISTINCT m.filename)>=?
                ORDER BY n DESC,MIN(m.id) ASC
                LIMIT 1
                """,
                (minimum,),
            ).fetchone()
        return (row["prefix"], row["category"], row["n"]) if row else None

    def dismiss_learning_suggestion(self, prefix: str, category: str) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO learning_dismissals(prefix,category,timestamp) VALUES(?,?,?)
                ON CONFLICT(prefix,category) DO UPDATE SET timestamp=excluded.timestamp
                """,
                (prefix, category, datetime.now().isoformat()),
            )

    def record_usage(self, files: int, input_tokens: int | None, output_tokens: int | None, cost: float | None) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO api_usage(timestamp,files,input_tokens,output_tokens,estimated_cost) VALUES(?,?,?,?,?)", (datetime.now().isoformat(), files, input_tokens, output_tokens, cost))
