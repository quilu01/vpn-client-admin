from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import hashlib
import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.client import ActionAudit, TrafficSnapshot, VpnClient, as_utc, utc_now
from app.services.happ import HappCryptoClient, HappCryptoError
from app.services.xui import XuiClient, XuiError


class ClientServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class CreateClientResult:
    client: VpnClient
    warning: str | None = None


def bytes_from_gb(value: int | None) -> int | None:
    if value is None or value <= 0:
        return None
    return value * 1024 * 1024 * 1024


def gb_from_bytes(value: int | None) -> float | None:
    if value is None:
        return None
    return round(value / 1024 / 1024 / 1024, 2)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ClientService:
    def __init__(self, *, xui: XuiClient, happ: HappCryptoClient, public_app_url: str):
        self.xui = xui
        self.happ = happ
        self.public_app_url = public_app_url.rstrip("/")

    async def create_client(
        self,
        db: Session,
        *,
        display_name: str,
        inbound_ids: list[int],
        duration_days: int,
        traffic_limit_gb: int | None,
        actor: str = "admin",
    ) -> CreateClientResult:
        display_name = display_name.strip()
        if not display_name:
            raise ClientServiceError("Client name is required")
        if duration_days <= 0:
            raise ClientServiceError("Duration must be positive")

        expires_at = utc_now() + timedelta(days=duration_days)
        traffic_limit_bytes = bytes_from_gb(traffic_limit_gb)
        try:
            created = await self.xui.create_client(
                display_name=display_name,
                inbound_ids=inbound_ids,
                expires_at=expires_at,
                traffic_limit_bytes=traffic_limit_bytes,
            )
        except XuiError as exc:
            raise ClientServiceError(str(exc)) from exc
        client = VpnClient(
            display_name=display_name,
            status="active",
            xui_inbound_id=inbound_ids[0],
            xui_inbound_ids=",".join(str(inbound_id) for inbound_id in inbound_ids),
            xui_client_id=created.client_id,
            xui_email=created.email,
            xui_sub_id=created.sub_id,
            expires_at=expires_at,
            traffic_limit_bytes=traffic_limit_bytes,
        )
        db.add(client)
        db.flush()
        self._audit(db, client=client, actor=actor, action="create", details="Created in 3x-ui")

        warning = await self.issue_happ_link(db, client, actor=actor, raise_on_error=False)
        db.commit()
        db.refresh(client)
        return CreateClientResult(client=client, warning=warning)

    async def issue_happ_link(
        self,
        db: Session,
        client: VpnClient,
        *,
        actor: str = "admin",
        raise_on_error: bool = True,
    ) -> str | None:
        token = secrets.token_urlsafe(32)
        source_url = f"{self.public_app_url}/sub/{token}"
        try:
            encrypted = await self.happ.encrypt_url(source_url)
        except HappCryptoError as exc:
            self._audit(db, client=client, actor=actor, action="happ_encrypt_failed", details=str(exc))
            if raise_on_error:
                raise ClientServiceError(str(exc)) from exc
            return str(exc)

        client.subscription_token_hash = token_hash(token)
        client.happ_link = encrypted
        client.happ_encrypted_at = utc_now()
        self._audit(db, client=client, actor=actor, action="issue_link", details="Issued Happ link")
        return None

    async def block_client(self, db: Session, client: VpnClient, *, actor: str = "admin") -> None:
        try:
            await self.xui.set_client_enabled(
                client_id=client.xui_client_id,
                email=client.xui_email,
                sub_id=client.xui_sub_id,
                expires_at=as_utc(client.expires_at),
                traffic_limit_bytes=client.traffic_limit_bytes,
                enabled=False,
            )
        except XuiError as exc:
            raise ClientServiceError(str(exc)) from exc
        client.status = "blocked"
        client.blocked_at = utc_now()
        self._audit(db, client=client, actor=actor, action="block", details="Disabled in 3x-ui")
        db.commit()

    async def extend_client(
        self,
        db: Session,
        client: VpnClient,
        *,
        extra_days: int,
        actor: str = "admin",
    ) -> None:
        if extra_days <= 0:
            raise ClientServiceError("Extension days must be positive")
        current_expires_at = as_utc(client.expires_at)
        base = current_expires_at if current_expires_at > utc_now() else utc_now()
        client.expires_at = base + timedelta(days=extra_days)
        client.status = "active"
        client.blocked_at = None
        try:
            await self.xui.update_client_expiry(
                client_id=client.xui_client_id,
                email=client.xui_email,
                sub_id=client.xui_sub_id,
                expires_at=as_utc(client.expires_at),
                traffic_limit_bytes=client.traffic_limit_bytes,
                enabled=True,
            )
        except XuiError as exc:
            raise ClientServiceError(str(exc)) from exc
        self._audit(db, client=client, actor=actor, action="extend", details=f"+{extra_days} days")
        db.commit()

    async def sync_traffic(self, db: Session, client: VpnClient, *, actor: str = "admin") -> None:
        try:
            traffic = await self.xui.get_client_traffic(client.xui_email)
        except XuiError as exc:
            raise ClientServiceError(str(exc)) from exc
        client.traffic_used_bytes = traffic.used_bytes
        client.last_sync_at = utc_now()
        if traffic.limit_bytes is not None:
            client.traffic_limit_bytes = traffic.limit_bytes
        db.add(
            TrafficSnapshot(
                client=client,
                used_bytes=client.traffic_used_bytes,
                limit_bytes=client.traffic_limit_bytes,
            )
        )
        self._audit(db, client=client, actor=actor, action="sync_traffic", details=None)
        db.commit()

    def find_by_subscription_token(self, db: Session, token: str) -> VpnClient | None:
        return db.scalar(
            select(VpnClient).where(VpnClient.subscription_token_hash == token_hash(token))
        )

    async def fetch_subscription(self, db: Session, token: str) -> tuple[VpnClient, str, str]:
        client = self.find_by_subscription_token(db, token)
        if not client or not client.is_subscription_available:
            raise ClientServiceError("Subscription is not available")
        try:
            body, content_type = await self.xui.fetch_subscription(client.xui_sub_id)
        except XuiError as exc:
            raise ClientServiceError(str(exc)) from exc
        return client, body, content_type

    @staticmethod
    def dashboard_stats(db: Session) -> dict[str, int]:
        now = utc_now()
        active = db.scalar(
            select(func.count(VpnClient.id)).where(
                VpnClient.status == "active",
                VpnClient.expires_at > now,
            )
        )
        expiring = db.scalar(
            select(func.count(VpnClient.id)).where(
                VpnClient.status == "active",
                VpnClient.expires_at > now,
                VpnClient.expires_at <= now + timedelta(days=7),
            )
        )
        blocked = db.scalar(select(func.count(VpnClient.id)).where(VpnClient.status == "blocked"))
        total_traffic = db.scalar(select(func.coalesce(func.sum(VpnClient.traffic_used_bytes), 0)))
        return {
            "active": int(active or 0),
            "expiring": int(expiring or 0),
            "blocked": int(blocked or 0),
            "total_traffic": int(total_traffic or 0),
        }

    @staticmethod
    def _audit(
        db: Session,
        *,
        client: VpnClient | None,
        actor: str,
        action: str,
        details: str | None,
    ) -> None:
        db.add(ActionAudit(client=client, actor=actor, action=action, details=details))
