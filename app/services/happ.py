from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class HappCryptoError(RuntimeError):
    pass


@dataclass(frozen=True)
class HappCryptoClient:
    api_url: str
    mode: str = "api"
    timeout_seconds: float = 20.0

    async def encrypt_url(self, url: str) -> str:
        if self.mode == "passthrough":
            return url
        if self.mode != "api":
            raise HappCryptoError(f"Unsupported Happ crypto mode: {self.mode}")

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            try:
                response = await client.post(self.api_url, json={"url": url})
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise HappCryptoError(f"Happ Crypto API request failed: {exc}") from exc

        encrypted = self._extract_encrypted_link(response)
        if not encrypted:
            raise HappCryptoError("Happ Crypto API response did not contain an encrypted link")
        if not encrypted.startswith("happ://crypt"):
            raise HappCryptoError("Happ Crypto API returned a non-Happ encrypted link")
        return encrypted

    @staticmethod
    def _extract_encrypted_link(response: httpx.Response) -> str | None:
        text = response.text.strip().strip('"')
        if text.startswith("happ://crypt"):
            return text
        try:
            payload = response.json()
        except ValueError:
            return None
        return _find_happ_link(payload)


def _find_happ_link(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped.startswith("happ://crypt") else None
    if isinstance(value, dict):
        preferred_keys = ("url", "encrypted_url", "link", "result", "data", "msg")
        for key in preferred_keys:
            if key in value:
                found = _find_happ_link(value[key])
                if found:
                    return found
        for item in value.values():
            found = _find_happ_link(item)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_happ_link(item)
            if found:
                return found
    return None

