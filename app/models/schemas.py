from __future__ import annotations

from datetime import datetime
from enum import Enum
import ipaddress
import re
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _is_loopback_host(hostname: str) -> bool:
    host = hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


class RuleType(str, Enum):
    MANUAL = "manual"
    PREFIX = "prefix"
    EXTENSION = "extension"


class ArchiveStatus(str, Enum):
    NONE = "无需解压"
    WAITING = "等待解压"
    EXTRACTING = "正在解压"
    SUCCESS = "解压成功"
    # These are user-facing status labels, never credentials.
    NEED_PASSWORD = "需要密码"  # nosec B105
    BAD_PASSWORD = "密码错误"  # nosec B105
    UNSUPPORTED = "格式不支持"
    FAILED = "解压失败"
    BLOCKED = "安全拦截"


class FileRecord(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    path: Path
    name: str
    suffix: str = ""
    size: int = 0
    created_at: datetime
    modified_at: datetime
    prefix: str = ""
    mime_type: str = "application/octet-stream"
    category: str = "待确认"
    subcategory: str = ""
    confidence: float = 0.0
    reason: str = ""
    suggested_name: str = ""
    target_path: Path | None = None
    selected: bool = True
    status: str = "待处理"
    source: str = "待确认"
    archive_status: ArchiveStatus = ArchiveStatus.NONE
    archive_format: str = ""
    archive_encrypted: bool | None = None
    archive_file_count: int | None = None
    archive_unpacked_size: int | None = None
    archive_password_index: int | None = None
    archive_output: Path | None = None
    archive_depth: int = 0
    scan_root: Path | None = None
    relative_parent: Path | None = None


class ClassificationRule(BaseModel):
    id: int | None = None
    rule_type: RuleType = RuleType.PREFIX
    pattern: str
    category: str
    enabled: bool = True
    priority: int = 100
    case_sensitive: bool = False
    builtin: bool = False

    @field_validator("pattern", "category")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("不能为空")
        return value.strip()


class AIResult(BaseModel):
    category: str = Field(min_length=1, max_length=128)
    subcategory: str = Field(default="", max_length=128)
    suggested_name: str = Field(default="", max_length=255)
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(default="", max_length=2000)

    @field_validator("category", "subcategory", "suggested_name", "reason", mode="before")
    @classmethod
    def normalize_ai_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class AppSettings(BaseModel):
    ui_language: str = "zh_CN"
    material_pack: str = "default"
    api_base_url: str = "https://api.openai.com/v1"
    api_model: str = "gpt-5.6-luna"
    api_timeout: int = Field(30, ge=3, le=300)
    api_concurrency: int = Field(3, ge=1, le=20)
    api_max_retries: int = Field(2, ge=0, le=5)
    api_max_batch_chars: int = Field(40_000, ge=8_000, le=200_000)
    api_max_response_bytes: int = Field(4 * 1024**2, ge=64 * 1024, le=16 * 1024**2)
    input_cost_per_million: float = Field(0.0, ge=0)
    output_cost_per_million: float = Field(0.0, ge=0)
    temperature: float = Field(0.1, ge=0, le=2)
    high_confidence: float = Field(0.8, ge=0, le=1)
    low_confidence: float = Field(0.5, ge=0, le=1)
    allow_vision: bool = False
    ai_send_text_content: bool = True
    ai_send_full_path: bool = False
    vision_max_dimension: int = Field(1024, ge=256, le=2048)
    vision_max_source_bytes: int = Field(5 * 1024**2, ge=64 * 1024, le=25 * 1024**2)
    max_text_chars: int = Field(5000, ge=100, le=100000)
    recursive_scan: bool = True
    scan_hidden: bool = False
    keep_structure: bool = False
    allow_rename: bool = True
    rename_template: str = "{date}_{category}_{original_name}"
    require_confirmation: bool = True
    history_enabled: bool = True
    undo_enabled: bool = True
    auto_detect_archives: bool = True
    auto_extract: bool = False
    rescan_extracted: bool = True
    keep_archive: bool = True
    archive_after_extract: str = "keep"  # keep | move | trash
    extract_mode: str = "beside"  # beside | unified | temporary
    extract_directory: str = ""
    create_named_folder: bool = True
    max_extract_depth: int = Field(3, ge=0, le=5)
    max_archive_unpacked_bytes: int = Field(5 * 1024**3, ge=1024)
    max_archive_files: int = Field(10000, ge=1)
    max_compression_ratio: float = Field(200.0, ge=1)
    max_task_extract_bytes: int = Field(20 * 1024**3, ge=1024)

    @field_validator("api_base_url")
    @classmethod
    def valid_api_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("API 地址必须是有效的 http:// 或 https:// 地址")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("API 地址不能包含账号、密码、查询参数或片段")
        if "\\" in value:
            raise ValueError("API 地址不能包含反斜杠")
        if parsed.scheme == "http" and not _is_loopback_host(parsed.hostname):
            raise ValueError("非本机 API 必须使用 HTTPS；HTTP 仅允许 localhost/回环地址")
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("API 地址端口无效") from exc
        return value

    @field_validator("api_model")
    @classmethod
    def nonempty_model(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("模型名称不能为空")
        return value.strip()

    @field_validator("ui_language")
    @classmethod
    def valid_ui_language(cls, value: str) -> str:
        if value not in {"zh_CN", "en", "ja", "ko"}:
            raise ValueError("不支持的界面语言")
        return value

    @field_validator("material_pack")
    @classmethod
    def valid_material_pack_id(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value):
            raise ValueError("材质包标识无效")
        return value

    @model_validator(mode="after")
    def coherent_settings(self):
        if self.low_confidence > self.high_confidence:
            raise ValueError("待确认阈值不能高于自动建议阈值")
        if self.extract_mode == "unified":
            if not self.extract_directory.strip():
                raise ValueError("统一解压模式必须填写解压目录")
            # Settings can also be loaded from SQLite, so this boundary must
            # be enforced by the model rather than relying only on the GUI.
            from app.utils.paths import application_state_root, is_protected_location

            destination = Path(self.extract_directory).expanduser()
            if is_protected_location(destination, (application_state_root(),)):
                raise ValueError("统一解压目录不能位于系统目录、磁盘根目录或应用数据目录")
            self.extract_directory = str(destination)
        return self


class OperationRecord(BaseModel):
    operation_id: str
    timestamp: datetime
    source_path: Path
    target_path: Path
    original_name: str
    new_name: str
    action: str = "move"
    status: str


class ExtractionResult(BaseModel):
    archive: Path
    status: ArchiveStatus
    output_dir: Path | None = None
    files: list[Path] = Field(default_factory=list)
    format: str = ""
    encrypted: bool | None = None
    file_count: int = 0
    unpacked_size: int = 0
    password_index: int | None = None
    depth: int = 0
    extracted_bytes: int = 0
    warnings: list[str] = Field(default_factory=list)
    error: str = ""
