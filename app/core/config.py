from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - python-dotenv is optional outside uvicorn[standard]
    load_dotenv = None

if load_dotenv:
    load_dotenv()


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


def _parse_inbounds(raw: str, fallback_id: int) -> tuple[tuple[int, str], ...]:
    entries: list[tuple[int, str]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            inbound_id_raw, label = part.split(":", 1)
        else:
            inbound_id_raw, label = part, part
        inbound_id = int(inbound_id_raw.strip())
        label = label.strip() or f"Inbound {inbound_id}"
        entries.append((inbound_id, label))
    if entries:
        return tuple(entries)
    if fallback_id:
        return ((fallback_id, f"Inbound {fallback_id}"),)
    return ()


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "VPN Client Admin")
    app_secret_key: str = os.getenv("APP_SECRET_KEY", "dev-secret-change-me")
    public_app_url: str = os.getenv("PUBLIC_APP_URL", "http://localhost:8000")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./vpn_admin.sqlite3")

    admin_username: str = os.getenv("ADMIN_USERNAME", "admin")
    admin_password_hash: str = os.getenv("ADMIN_PASSWORD_HASH", "")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "admin")
    admin_ip_allowlist: str = os.getenv("ADMIN_IP_ALLOWLIST", "127.0.0.1/32,::1/128")
    trust_proxy_headers: bool = _as_bool(os.getenv("TRUST_PROXY_HEADERS"), False)
    cookie_secure: bool = _as_bool(os.getenv("COOKIE_SECURE"), False)
    session_ttl_seconds: int = _as_int(os.getenv("SESSION_TTL_SECONDS"), 60 * 60 * 12)

    xui_base_url: str = os.getenv("XUI_BASE_URL", "")
    xui_api_token: str = os.getenv("XUI_API_TOKEN", "")
    xui_inbound_id: int = _as_int(os.getenv("XUI_INBOUND_ID"), 0)
    xui_inbounds: str = os.getenv("XUI_INBOUNDS", "")
    xui_subscription_base_url: str = os.getenv("XUI_SUBSCRIPTION_BASE_URL", "")
    xui_client_flow: str = os.getenv("XUI_CLIENT_FLOW", "")
    xui_tls_verify: bool = _as_bool(os.getenv("XUI_TLS_VERIFY"), True)

    happ_crypto_api_url: str = os.getenv("HAPP_CRYPTO_API_URL", "https://crypto.happ.su/api-v2.php")
    happ_crypto_mode: str = os.getenv("HAPP_CRYPTO_MODE", "api")
    happ_profile_title: str = os.getenv("HAPP_PROFILE_TITLE", "VPN")
    happ_support_url: str = os.getenv("HAPP_SUPPORT_URL", "https://t.me/kmplzzz")
    happ_profile_web_page_url: str = os.getenv("HAPP_PROFILE_WEB_PAGE_URL", "https://t.me/kmplzzz")

    @property
    def is_xui_configured(self) -> bool:
        return bool(self.xui_base_url and self.xui_api_token and self.xui_inbound_options)

    @property
    def xui_inbound_options(self) -> tuple[tuple[int, str], ...]:
        return _parse_inbounds(self.xui_inbounds, self.xui_inbound_id)

    def xui_inbound_label(self, inbound_id: int) -> str:
        for option_id, label in self.xui_inbound_options:
            if option_id == inbound_id:
                return label
        return f"Inbound {inbound_id}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
