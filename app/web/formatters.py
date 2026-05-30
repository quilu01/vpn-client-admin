from __future__ import annotations

from datetime import datetime, timezone


def format_bytes(value: int | None) -> str:
    if value is None:
        return "Без лимита"
    units = ["B", "KB", "MB", "GB", "TB"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value} B"


def format_datetime(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone().strftime("%d.%m.%Y %H:%M")


def status_label(value: str) -> str:
    return {
        "active": "Активен",
        "blocked": "Заблокирован",
        "expired": "Истек",
    }.get(value, value)

