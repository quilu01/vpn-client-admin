from __future__ import annotations

from datetime import timedelta
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models.client import VpnClient, utc_now
from app.services.client_service import ClientService, ClientServiceError, token_hash
from app.services.happ import HappCryptoError
from app.services.xui import CreatedXuiClient, XuiTraffic


class FakeXui:
    inbound_id = 42

    def __init__(self) -> None:
        self.created = []
        self.enabled_calls = []
        self.subscription_body = "vless://example"

    async def create_client(self, **kwargs) -> CreatedXuiClient:
        self.created.append(kwargs)
        return CreatedXuiClient(client_id="uuid-1", email="client-1", sub_id="sub-1")

    async def set_client_enabled(self, **kwargs) -> None:
        self.enabled_calls.append(kwargs)

    async def update_client_expiry(self, **kwargs) -> None:
        self.enabled_calls.append(kwargs)

    async def get_client_traffic(self, email: str) -> XuiTraffic:
        return XuiTraffic(used_bytes=1234, limit_bytes=2048, enabled=True)

    async def fetch_subscription(self, sub_id: str) -> tuple[str, str]:
        return self.subscription_body, "text/plain"


class FakeHapp:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.urls: list[str] = []

    async def encrypt_url(self, url: str) -> str:
        self.urls.append(url)
        if self.fail:
            raise HappCryptoError("crypto unavailable")
        return f"happ://crypt5/{len(self.urls)}"


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = local_session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.mark.asyncio
async def test_create_client_creates_xui_client_and_happ_link(db: Session) -> None:
    xui = FakeXui()
    happ = FakeHapp()
    service = ClientService(xui=xui, happ=happ, public_app_url="https://admin.example")

    result = await service.create_client(
        db,
        display_name="Ivan",
        inbound_ids=[42, 43],
        duration_days=30,
        traffic_limit_gb=10,
    )

    assert result.warning is None
    assert result.client.happ_link == "happ://crypt5/1"
    assert result.client.inbound_id_list == [42, 43]
    assert result.client.subscription_token_hash is not None
    assert xui.created[0]["display_name"] == "Ivan"
    assert xui.created[0]["inbound_ids"] == [42, 43]
    assert xui.created[0]["traffic_limit_bytes"] == 10 * 1024 * 1024 * 1024
    assert urlparse(happ.urls[0]).path.startswith("/sub/")


@pytest.mark.asyncio
async def test_happ_failure_keeps_client_for_retry_without_link(db: Session) -> None:
    service = ClientService(
        xui=FakeXui(),
        happ=FakeHapp(fail=True),
        public_app_url="https://admin.example",
    )

    result = await service.create_client(
        db,
        display_name="Ivan",
        inbound_ids=[42],
        duration_days=30,
        traffic_limit_gb=None,
    )

    assert "crypto unavailable" in (result.warning or "")
    assert result.client.happ_link is None
    assert db.query(VpnClient).count() == 1


@pytest.mark.asyncio
async def test_subscription_endpoint_logic_denies_blocked_and_expired(db: Session) -> None:
    xui = FakeXui()
    service = ClientService(xui=xui, happ=FakeHapp(), public_app_url="https://admin.example")
    active = VpnClient(
        display_name="Active",
        status="active",
        xui_inbound_id=42,
        xui_client_id="uuid-active",
        xui_email="active",
        xui_sub_id="sub-active",
        subscription_token_hash=token_hash("active-token"),
        expires_at=utc_now() + timedelta(days=1),
    )
    blocked = VpnClient(
        display_name="Blocked",
        status="blocked",
        xui_inbound_id=42,
        xui_client_id="uuid-blocked",
        xui_email="blocked",
        xui_sub_id="sub-blocked",
        subscription_token_hash=token_hash("blocked-token"),
        expires_at=utc_now() + timedelta(days=1),
    )
    expired = VpnClient(
        display_name="Expired",
        status="active",
        xui_inbound_id=42,
        xui_client_id="uuid-expired",
        xui_email="expired",
        xui_sub_id="sub-expired",
        subscription_token_hash=token_hash("expired-token"),
        expires_at=utc_now() - timedelta(days=1),
    )
    db.add_all([active, blocked, expired])
    db.commit()

    _, body, content_type = await service.fetch_subscription(db, "active-token")

    assert body == "vless://example"
    assert content_type == "text/plain"
    with pytest.raises(ClientServiceError):
        await service.fetch_subscription(db, "blocked-token")
    with pytest.raises(ClientServiceError):
        await service.fetch_subscription(db, "expired-token")


@pytest.mark.asyncio
async def test_reissue_link_invalidates_previous_token_hash(db: Session) -> None:
    client = VpnClient(
        display_name="Client",
        status="active",
        xui_inbound_id=42,
        xui_client_id="uuid-client",
        xui_email="client",
        xui_sub_id="sub-client",
        subscription_token_hash=token_hash("old-token"),
        expires_at=utc_now() + timedelta(days=1),
    )
    db.add(client)
    db.commit()
    old_hash = client.subscription_token_hash
    service = ClientService(xui=FakeXui(), happ=FakeHapp(), public_app_url="https://admin.example")

    await service.issue_happ_link(db, client)

    assert client.subscription_token_hash != old_hash
    assert client.happ_link == "happ://crypt5/1"
