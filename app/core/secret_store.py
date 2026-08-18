from __future__ import annotations

import hashlib
import logging
from urllib.parse import urlsplit

try:
    import keyring
except ImportError:  # pragma: no cover
    keyring = None

LOGGER = logging.getLogger(__name__)
SERVICE = "AIFileOrganizer.API"
LEGACY_ACCOUNT = "default"
DEFAULT_API_BASE_URL = "https://api.openai.com/v1"
_SESSION_KEYS: dict[str, str] = {}


def normalized_api_origin(base_url: str | None = None) -> str:
    """Return a stable credential scope without URL paths or user info."""
    parsed = urlsplit((base_url or DEFAULT_API_BASE_URL).strip())
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("API 地址无效，无法确定凭据作用域")
    if parsed.username or parsed.password:
        raise ValueError("API 地址不能包含账号或密码")
    host = parsed.hostname.rstrip(".").lower()
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("API 主机名无效") from exc
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("API 地址端口无效") from exc
    if ":" in host:
        host = f"[{host}]"
    default_port = 443 if scheme == "https" else 80
    return f"{scheme}://{host}" + (f":{port}" if port and port != default_port else "")


def _account_for_origin(origin: str) -> str:
    digest = hashlib.sha256(origin.encode("utf-8")).hexdigest()
    return f"origin-{digest}"


def secure_backend_available() -> bool:
    try:
        return keyring is not None and keyring.get_keyring().priority > 0
    except Exception:
        return False


def get_api_key(base_url: str | None = None) -> str:
    origin = normalized_api_origin(base_url)
    account = _account_for_origin(origin)
    if secure_backend_available():
        try:
            value = keyring.get_password(SERVICE, account) or ""
            if value:
                _SESSION_KEYS[origin] = value
                return value
            # One-time migration for the original OpenAI credential slot. Never
            # migrate that key to a different provider/origin.
            if origin == normalized_api_origin(DEFAULT_API_BASE_URL):
                legacy = keyring.get_password(SERVICE, LEGACY_ACCOUNT) or ""
                if legacy:
                    keyring.set_password(SERVICE, account, legacy)
                    try:
                        keyring.delete_password(SERVICE, LEGACY_ACCOUNT)
                    except Exception:
                        LOGGER.warning("旧 API 凭据迁移后无法删除旧条目")
                    _SESSION_KEYS[origin] = legacy
                    return legacy
        except Exception as exc:
            LOGGER.warning("API Key 无法从系统凭据存储读取：%s", exc)
    return _SESSION_KEYS.get(origin, "")


def set_api_key(value: str, base_url: str | None = None) -> bool:
    origin = normalized_api_origin(base_url)
    account = _account_for_origin(origin)
    value = value.strip()
    if value:
        _SESSION_KEYS[origin] = value
    else:
        _SESSION_KEYS.pop(origin, None)
    if secure_backend_available():
        try:
            if value:
                keyring.set_password(SERVICE, account, value)
            else:
                try:
                    keyring.delete_password(SERVICE, account)
                except keyring.errors.PasswordDeleteError:
                    pass
                if origin == normalized_api_origin(DEFAULT_API_BASE_URL):
                    try:
                        keyring.delete_password(SERVICE, LEGACY_ACCOUNT)
                    except keyring.errors.PasswordDeleteError:
                        pass
            return True
        except Exception as exc:
            LOGGER.warning("API Key 无法写入系统凭据存储：%s", exc)
    return False
