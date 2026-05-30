from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class VpnClient(Base):
    __tablename__ = "vpn_clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)

    xui_inbound_id: Mapped[int] = mapped_column(Integer, nullable=False)
    xui_inbound_ids: Mapped[str | None] = mapped_column(Text)
    xui_client_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    xui_email: Mapped[str] = mapped_column(String(160), nullable=False, unique=True, index=True)
    xui_sub_id: Mapped[str] = mapped_column(String(160), nullable=False, unique=True, index=True)

    subscription_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    happ_link: Mapped[str | None] = mapped_column(Text)
    happ_encrypted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    traffic_limit_bytes: Mapped[int | None] = mapped_column(BigInteger)
    traffic_used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    traffic_snapshots: Mapped[list["TrafficSnapshot"]] = relationship(
        back_populates="client",
        cascade="all, delete-orphan",
    )
    audit_entries: Mapped[list["ActionAudit"]] = relationship(
        back_populates="client",
        cascade="all, delete-orphan",
    )

    @property
    def effective_status(self) -> str:
        if self.status == "blocked":
            return "blocked"
        if as_utc(self.expires_at) <= utc_now():
            return "expired"
        return "active"

    @property
    def is_subscription_available(self) -> bool:
        return self.effective_status == "active" and bool(self.xui_sub_id)

    @property
    def inbound_id_list(self) -> list[int]:
        if self.xui_inbound_ids:
            ids: list[int] = []
            for part in self.xui_inbound_ids.split(","):
                part = part.strip()
                if not part:
                    continue
                try:
                    ids.append(int(part))
                except ValueError:
                    continue
            if ids:
                return ids
        return [self.xui_inbound_id]


class TrafficSnapshot(Base):
    __tablename__ = "traffic_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("vpn_clients.id", ondelete="CASCADE"), index=True)
    used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    limit_bytes: Mapped[int | None] = mapped_column(BigInteger)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    client: Mapped[VpnClient] = relationship(back_populates="traffic_snapshots")


class ActionAudit(Base):
    __tablename__ = "action_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("vpn_clients.id", ondelete="SET NULL"))
    actor: Mapped[str] = mapped_column(String(120), nullable=False, default="admin")
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    client: Mapped[VpnClient | None] = relationship(back_populates="audit_entries")
