from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import secrets
import sys
import time
from dataclasses import dataclass
from typing import Iterable

from fastapi import HTTPException, Request, status

PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 390_000
SESSION_COOKIE_NAME = "vpn_admin_session"


def hash_password(password: str, *, salt: str | None = None) -> str:
    salt = salt or secrets.token_urlsafe(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_ITERATIONS,
    )
    encoded = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"{PASSWORD_ALGORITHM}${PASSWORD_ITERATIONS}${salt}${encoded}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt, expected = password_hash.split("$", 3)
        if algorithm != PASSWORD_ALGORITHM:
            return False
        iterations = int(iterations_raw)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        )
        actual = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def make_session(username: str, secret_key: str, ttl_seconds: int) -> str:
    expires_at = int(time.time()) + ttl_seconds
    payload = f"{username}|{expires_at}"
    signature = hmac.new(secret_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256)
    token = f"{payload}|{signature.hexdigest()}"
    return base64.urlsafe_b64encode(token.encode("utf-8")).decode("ascii")


def read_session(token: str | None, secret_key: str) -> str | None:
    if not token:
        return None
    try:
        decoded = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        username, expires_raw, provided_signature = decoded.split("|", 2)
        payload = f"{username}|{expires_raw}"
        expected_signature = hmac.new(
            secret_key.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(provided_signature, expected_signature):
            return None
        if int(expires_raw) < int(time.time()):
            return None
        return username
    except (ValueError, TypeError, UnicodeDecodeError):
        return None


def check_admin_password(password: str, password_hash: str, fallback_password: str) -> bool:
    if password_hash:
        return verify_password(password, password_hash)
    return hmac.compare_digest(password, fallback_password)


@dataclass(frozen=True)
class IpAllowlist:
    networks: tuple[ipaddress._BaseNetwork, ...]

    @classmethod
    def from_csv(cls, raw: str) -> "IpAllowlist":
        entries = [part.strip() for part in raw.split(",") if part.strip()]
        networks: list[ipaddress._BaseNetwork] = []
        for entry in entries:
            if "/" in entry:
                networks.append(ipaddress.ip_network(entry, strict=False))
            else:
                address = ipaddress.ip_address(entry)
                suffix = 32 if address.version == 4 else 128
                networks.append(ipaddress.ip_network(f"{entry}/{suffix}", strict=False))
        return cls(tuple(networks))

    def allows(self, ip: str | None) -> bool:
        if not self.networks:
            return True
        if not ip:
            return False
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(address in network for network in self.networks)


def get_client_ip(request: Request, *, trust_proxy_headers: bool) -> str | None:
    if trust_proxy_headers:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",", 1)[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
    return request.client.host if request.client else None


def ensure_allowed_ip(request: Request, allowlist: IpAllowlist, *, trust_proxy_headers: bool) -> None:
    ip = get_client_ip(request, trust_proxy_headers=trust_proxy_headers)
    if not allowlist.allows(ip):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="IP is not allowed")


def require_session_username(request: Request, *, secret_key: str) -> str:
    username = read_session(request.cookies.get(SESSION_COOKIE_NAME), secret_key)
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return username


def main(argv: Iterable[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if args and args[0] == "hash-password":
        password = args[1] if len(args) > 1 else secrets.token_urlsafe(18)
        print("Generated password:")
        print(password)
        print()
        print("ADMIN_PASSWORD_HASH:")
        print(hash_password(password))
        return 0
    print("Usage: python -m app.core.security hash-password [password]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
