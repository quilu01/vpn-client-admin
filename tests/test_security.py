from __future__ import annotations

from app.core.security import IpAllowlist, hash_password, make_session, read_session, verify_password


def test_password_hash_roundtrip() -> None:
    password_hash = hash_password("very-secret")

    assert verify_password("very-secret", password_hash)
    assert not verify_password("wrong", password_hash)


def test_session_roundtrip() -> None:
    token = make_session("admin", "secret-key", ttl_seconds=60)

    assert read_session(token, "secret-key") == "admin"
    assert read_session(token, "other-secret") is None


def test_ip_allowlist_supports_hosts_and_networks() -> None:
    allowlist = IpAllowlist.from_csv("127.0.0.1,10.20.0.0/16")

    assert allowlist.allows("127.0.0.1")
    assert allowlist.allows("10.20.4.5")
    assert not allowlist.allows("10.21.4.5")

