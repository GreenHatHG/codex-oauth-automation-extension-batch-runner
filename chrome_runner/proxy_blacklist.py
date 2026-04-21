"""Local persistent proxy blacklist helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .constants import (
    PROXY_BLACKLIST_COOLDOWN_KIND_SUCCESS,
    PROXY_BLACKLIST_COOLDOWN_KIND_UNSUCCESSFUL,
    PROXY_BLACKLIST_FILE_NAME,
)
from .ttl_blacklist import (
    BLACKLIST_ROOT_KEY,
    build_blacklist_file_path,
    normalize_blacklist_name,
    parse_blacklist_timestamp,
    serialize_blacklist_timestamp,
)

PROXY_BLACKLIST_NAME_FIELD = "proxy_name"
PROXY_BLACKLIST_ITEM_LABEL = "节点"
PROXY_BLACKLIST_COOLDOWN_KIND_FIELD = "cooldown_kind"
VALID_PROXY_BLACKLIST_COOLDOWN_KINDS = frozenset(
    {
        PROXY_BLACKLIST_COOLDOWN_KIND_SUCCESS,
        PROXY_BLACKLIST_COOLDOWN_KIND_UNSUCCESSFUL,
    }
)


@dataclass(frozen=True)
class ProxyBlacklistEntry:
    """Single proxy blacklist record."""

    proxy_name: str
    created_at: datetime
    last_hit_at: datetime
    cooldown_kind: str = PROXY_BLACKLIST_COOLDOWN_KIND_UNSUCCESSFUL


def _current_time() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def _normalize_cooldown_kind(raw_value: object) -> str:
    normalized_value = str(raw_value or "").strip()
    if not normalized_value:
        return PROXY_BLACKLIST_COOLDOWN_KIND_UNSUCCESSFUL
    if normalized_value not in VALID_PROXY_BLACKLIST_COOLDOWN_KINDS:
        raise RuntimeError(f"本地黑名单记录的冷却类型无效：{normalized_value}")
    return normalized_value


def _resolve_blacklist_ttl_seconds(
    cooldown_kind: str,
    *,
    success_ttl_seconds: int,
    unsuccessful_ttl_seconds: int,
) -> int:
    if cooldown_kind == PROXY_BLACKLIST_COOLDOWN_KIND_SUCCESS:
        return success_ttl_seconds
    return unsuccessful_ttl_seconds


def _parse_entry(
    item_name: str,
    raw_entry: object,
) -> ProxyBlacklistEntry:
    if not isinstance(raw_entry, dict):
        raise RuntimeError(f"本地黑名单记录格式无效：{item_name}")
    proxy_name = normalize_blacklist_name(
        raw_entry.get(PROXY_BLACKLIST_NAME_FIELD, item_name)
    )
    if not proxy_name:
        raise RuntimeError(f"本地黑名单记录缺少{PROXY_BLACKLIST_ITEM_LABEL}名称。")
    return ProxyBlacklistEntry(
        proxy_name=proxy_name,
        created_at=parse_blacklist_timestamp(
            raw_entry.get("created_at"),
            field_name="created_at",
            item_name=proxy_name,
        ),
        last_hit_at=parse_blacklist_timestamp(
            raw_entry.get("last_hit_at"),
            field_name="last_hit_at",
            item_name=proxy_name,
        ),
        cooldown_kind=_normalize_cooldown_kind(
            raw_entry.get(PROXY_BLACKLIST_COOLDOWN_KIND_FIELD)
        ),
    )


def build_proxy_blacklist_file_path(base_dir: Path) -> Path:
    return build_blacklist_file_path(base_dir, PROXY_BLACKLIST_FILE_NAME)


def load_proxy_blacklist_entries(base_dir: Path) -> dict[str, ProxyBlacklistEntry]:
    file_path = build_proxy_blacklist_file_path(base_dir)
    if not file_path.is_file():
        return {}
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"本地黑名单文件不是有效 JSON：{file_path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"本地黑名单文件格式无效：{file_path}")
    raw_entries = payload.get(BLACKLIST_ROOT_KEY, {})
    if not isinstance(raw_entries, dict):
        raise RuntimeError(f"本地黑名单 entries 字段格式无效：{file_path}")

    entries: dict[str, ProxyBlacklistEntry] = {}
    for item_name, raw_entry in raw_entries.items():
        entry = _parse_entry(str(item_name), raw_entry)
        entries[entry.proxy_name] = entry
    return entries


def save_proxy_blacklist_entries(
    base_dir: Path,
    entries: dict[str, ProxyBlacklistEntry],
) -> None:
    file_path = build_proxy_blacklist_file_path(base_dir)
    payload = {
        BLACKLIST_ROOT_KEY: {
            proxy_name: {
                PROXY_BLACKLIST_NAME_FIELD: entry.proxy_name,
                "created_at": serialize_blacklist_timestamp(entry.created_at),
                "last_hit_at": serialize_blacklist_timestamp(entry.last_hit_at),
                PROXY_BLACKLIST_COOLDOWN_KIND_FIELD: entry.cooldown_kind,
            }
            for proxy_name, entry in sorted(entries.items())
        }
    }
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file_path = file_path.with_name(f"{file_path.name}.tmp")
    temp_file_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_file_path.replace(file_path)


def load_active_proxy_blacklist_names(
    base_dir: Path,
    *,
    success_ttl_seconds: int,
    unsuccessful_ttl_seconds: int,
    now: datetime | None = None,
) -> frozenset[str]:
    current_time = now or _current_time()
    entries = load_proxy_blacklist_entries(base_dir)
    active_proxy_names = {
        proxy_name
        for proxy_name, entry in entries.items()
        if current_time - entry.last_hit_at
        < timedelta(
            seconds=_resolve_blacklist_ttl_seconds(
                entry.cooldown_kind,
                success_ttl_seconds=success_ttl_seconds,
                unsuccessful_ttl_seconds=unsuccessful_ttl_seconds,
            )
        )
    }
    return frozenset(active_proxy_names)


def record_proxy_blacklist_hit(
    base_dir: Path,
    proxy_name: str,
    *,
    cooldown_kind: str,
    now: datetime | None = None,
) -> bool:
    normalized_proxy_name = normalize_blacklist_name(proxy_name)
    if not normalized_proxy_name:
        raise RuntimeError(
            f"写入本地黑名单失败：{PROXY_BLACKLIST_ITEM_LABEL}名称为空。"
        )

    current_time = now or _current_time()
    normalized_cooldown_kind = _normalize_cooldown_kind(cooldown_kind)
    entries = load_proxy_blacklist_entries(base_dir)
    existing_entry = entries.get(normalized_proxy_name)
    created_at = current_time if existing_entry is None else existing_entry.created_at
    entries[normalized_proxy_name] = ProxyBlacklistEntry(
        proxy_name=normalized_proxy_name,
        created_at=created_at,
        last_hit_at=current_time,
        cooldown_kind=normalized_cooldown_kind,
    )
    save_proxy_blacklist_entries(base_dir, entries)
    return existing_entry is None
