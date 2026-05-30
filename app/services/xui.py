from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import secrets
import uuid

import httpx


class XuiError(RuntimeError):
    pass


@dataclass(frozen=True)
class CreatedXuiClient:
    client_id: str
    email: str
    sub_id: str


@dataclass(frozen=True)
class XuiTraffic:
    used_bytes: int
    limit_bytes: int | None
    enabled: bool | None = None


@dataclass(frozen=True)
class XuiInboundOption:
    id: int
    label: str
    enabled: bool
    protocol: str
    port: int


@dataclass(frozen=True)
class XuiClient:
    base_url: str
    api_token: str
    inbound_id: int
    subscription_base_url: str = ""
    client_flow: str = ""
    tls_verify: bool = True
    timeout_seconds: float = 20.0

    async def create_client(
        self,
        *,
        display_name: str,
        inbound_ids: list[int] | tuple[int, ...] | None = None,
        expires_at: datetime,
        traffic_limit_bytes: int | None,
    ) -> CreatedXuiClient:
        self._ensure_configured()
        target_inbound_ids = self._normalize_inbound_ids(inbound_ids)
        client_id = str(uuid.uuid4())
        email = self._make_email(display_name)
        sub_id = secrets.token_urlsafe(12)
        payload = self._client_payload(
            client_id=client_id,
            email=email,
            sub_id=sub_id,
            expires_at=expires_at,
            traffic_limit_bytes=traffic_limit_bytes,
            enable=True,
        )
        await self._post_json(
            "/panel/api/clients/add",
            {
                "client": payload,
                "inboundIds": target_inbound_ids,
            },
        )
        return CreatedXuiClient(client_id=client_id, email=email, sub_id=sub_id)

    async def set_client_enabled(
        self,
        *,
        client_id: str,
        email: str,
        sub_id: str,
        expires_at: datetime,
        traffic_limit_bytes: int | None,
        enabled: bool,
    ) -> None:
        payload = self._client_payload(
            client_id=client_id,
            email=email,
            sub_id=sub_id,
            expires_at=expires_at,
            traffic_limit_bytes=traffic_limit_bytes,
            enable=enabled,
        )
        await self._post_json(
            f"/panel/api/clients/update/{email}",
            payload,
        )

    async def update_client_expiry(
        self,
        *,
        client_id: str,
        email: str,
        sub_id: str,
        expires_at: datetime,
        traffic_limit_bytes: int | None,
        enabled: bool = True,
    ) -> None:
        await self.set_client_enabled(
            client_id=client_id,
            email=email,
            sub_id=sub_id,
            expires_at=expires_at,
            traffic_limit_bytes=traffic_limit_bytes,
            enabled=enabled,
        )

    async def get_client_traffic(self, email: str) -> XuiTraffic:
        payload = await self._get_json(f"/panel/api/inbounds/getClientTraffics/{email}")
        obj = payload.get("obj") if isinstance(payload, dict) else None
        if not isinstance(obj, dict):
            raise XuiError("3x-ui traffic response did not contain obj")
        up = int(obj.get("up") or 0)
        down = int(obj.get("down") or 0)
        total = obj.get("total") if obj.get("total") is not None else obj.get("totalGB")
        enabled = obj.get("enable")
        return XuiTraffic(
            used_bytes=up + down,
            limit_bytes=int(total) if total not in (None, "") else None,
            enabled=bool(enabled) if enabled is not None else None,
        )

    async def list_inbound_options(self) -> list[XuiInboundOption]:
        payload = await self._get_json("/panel/api/inbounds/options")
        obj = payload.get("obj") if isinstance(payload, dict) else None
        if not isinstance(obj, list):
            payload = await self._get_json("/panel/api/inbounds/list")
            obj = payload.get("obj") if isinstance(payload, dict) else None
        if not isinstance(obj, list):
            raise XuiError("3x-ui inbounds response did not contain obj list")

        options: list[XuiInboundOption] = []
        for item in obj:
            if not isinstance(item, dict):
                continue
            inbound_id = item.get("id")
            if inbound_id is None:
                continue
            remark = str(item.get("remark") or "").strip()
            protocol = str(item.get("protocol") or "").strip()
            port = int(item.get("port") or 0)
            label_parts = [remark or f"Inbound {inbound_id}"]
            if port:
                label_parts.append(str(port))
            if protocol:
                label_parts.append(protocol)
            options.append(
                XuiInboundOption(
                    id=int(inbound_id),
                    label=" / ".join(label_parts),
                    enabled=bool(item.get("enable", True)),
                    protocol=protocol,
                    port=port,
                )
            )
        return [option for option in options if option.enabled]

    async def fetch_subscription(self, sub_id: str) -> tuple[str, str]:
        base_url = self.subscription_base_url or f"{self.base_url.rstrip('/')}/sub"
        url = f"{base_url.rstrip('/')}/{sub_id}"
        async with httpx.AsyncClient(timeout=self.timeout_seconds, verify=self.tls_verify) as client:
            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise XuiError(f"3x-ui subscription request failed: {exc}") from exc
        return response.text, response.headers.get("content-type", "text/plain; charset=utf-8")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _post_json(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url.rstrip('/')}{path}"
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            headers=self._headers(),
            verify=self.tls_verify,
        ) as client:
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise XuiError(f"3x-ui API request failed: {exc}") from exc
        return self._parse_xui_response(response)

    async def _get_json(self, path: str) -> dict:
        url = f"{self.base_url.rstrip('/')}{path}"
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            headers=self._headers(),
            verify=self.tls_verify,
        ) as client:
            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise XuiError(f"3x-ui API request failed: {exc}") from exc
        return self._parse_xui_response(response)

    @staticmethod
    def _parse_xui_response(response: httpx.Response) -> dict:
        try:
            payload = response.json()
        except ValueError as exc:
            raise XuiError("3x-ui API returned a non-JSON response") from exc
        if isinstance(payload, dict) and payload.get("success") is False:
            raise XuiError(str(payload.get("msg") or "3x-ui API returned success=false"))
        return payload

    def _normalize_inbound_ids(self, inbound_ids: list[int] | tuple[int, ...] | None) -> list[int]:
        values = list(inbound_ids or [self.inbound_id])
        normalized: list[int] = []
        for value in values:
            inbound_id = int(value)
            if inbound_id and inbound_id not in normalized:
                normalized.append(inbound_id)
        if not normalized:
            raise XuiError("At least one 3x-ui inbound must be selected")
        return normalized

    def _client_payload(
        self,
        *,
        client_id: str,
        email: str,
        sub_id: str,
        expires_at: datetime,
        traffic_limit_bytes: int | None,
        enable: bool,
    ) -> dict:
        return {
            "id": client_id,
            "flow": self.client_flow,
            "email": email,
            "limitIp": 0,
            "totalGB": traffic_limit_bytes or 0,
            "expiryTime": int(expires_at.timestamp() * 1000),
            "enable": enable,
            "tgId": 0,
            "subId": sub_id,
            "reset": 0,
        }

    @staticmethod
    def _make_email(display_name: str) -> str:
        slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in display_name)
        slug = "-".join(part for part in slug.split("-") if part)[:40] or "client"
        return f"{slug}-{secrets.token_hex(4)}"

    def _ensure_configured(self) -> None:
        if not self.base_url or not self.api_token or not self.inbound_id:
            raise XuiError("3x-ui integration is not configured")
