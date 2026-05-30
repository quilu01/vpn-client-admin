from __future__ import annotations

from datetime import datetime, timezone

from app.core.config import Settings
from app.models.client import VpnClient
from app.web.routes import happ_subscription_headers


def test_happ_subscription_headers_include_profile_expiry_and_links() -> None:
    expires_at = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
    client = VpnClient(
        display_name="Nikita",
        status="active",
        xui_inbound_id=6,
        xui_client_id="uuid-nikita",
        xui_email="nikita",
        xui_sub_id="sub-nikita",
        expires_at=expires_at,
        traffic_limit_bytes=10_000,
        traffic_used_bytes=1_234,
    )
    settings = Settings(
        happ_profile_title="VPN",
        happ_support_url="https://t.me/kmplzzz",
        happ_profile_web_page_url="https://t.me/kmplzzz",
    )

    headers = happ_subscription_headers(client, settings)

    assert headers["profile-title"] == "VPN"
    assert headers["subscription-userinfo"] == (
        f"upload=0; download=1234; total=10000; expire={int(expires_at.timestamp())}"
    )
    assert headers["support-url"] == "https://t.me/kmplzzz"
    assert headers["profile-web-page-url"] == "https://t.me/kmplzzz"
    assert headers["content-disposition"] == 'attachment; filename="VPN"'
