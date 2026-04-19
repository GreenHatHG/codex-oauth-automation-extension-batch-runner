"""Shared local persistent TTL blacklist helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

BLACKLIST_ROOT_KEY = "entries"


@dataclass(frozen=True)
class LocalBlacklistEntry:
    """Single local blacklist record."""

    name: str
    created_at: datetime
    last_hit_at: datetime


def normalize_blacklist_name(value: object) -> str:
    return str(value or "").strip()


def _current_time() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def _serialize_timestamp(value: datetime) -> str:
    return value.astimezone().replace(microsecond=0).isoformat()


def _parse_timestamp(raw_value: object, *, field_name: str, item_name: str) -> datetime:
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise RuntimeError(f"本地黑名单记录缺少 {field_name}：{item_name}")
    try:
        parsed_value = datetime.fromisoformat(raw_value)
    except ValueError as exc:
        raise RuntimeError(
            f"本地黑名单记录的 {field_name} 格式无效：{item_name}"
        ) from exc
    if parsed_value.tzinfo is None:
        raise RuntimeError(f"本地黑名单记录的 {field_name} 缺少时区：{item_name}")
    return parsed_value


def _parse_entry(
    item_name: str,
    raw_entry: object,
    *,
    name_field: str,
    item_label: str,
) -> LocalBlacklistEntry:
    if not isinstance(raw_entry, dict):
        raise RuntimeError(f"本地黑名单记录格式无效：{item_name}")
    normalized_name = normalize_blacklist_name(raw_entry.get(name_field, item_name))
    if not normalized_name:
        raise RuntimeError(f"本地黑名单记录缺少{item_label}名称。")
    created_at = _parse_timestamp(
        raw_entry.get("created_at"),
        field_name="created_at",
        item_name=normalized_name,
    )
    last_hit_at = _parse_timestamp(
        raw_entry.get("last_hit_at"),
        field_name="last_hit_at",
        item_name=normalized_name,
    )
    return LocalBlacklistEntry(
        name=normalized_name,
        created_at=created_at,
        last_hit_at=last_hit_at,
    )


def build_blacklist_file_path(base_dir: Path, file_name: str) -> Path:
    return base_dir / file_name


def load_blacklist_entries(
    base_dir: Path,
    file_name: str,
    *,
    name_field: str,
    item_label: str,
) -> dict[str, LocalBlacklistEntry]:
    file_path = build_blacklist_file_path(base_dir, file_name)
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

    entries: dict[str, LocalBlacklistEntry] = {}
    for item_name, raw_entry in raw_entries.items():
        entry = _parse_entry(
            str(item_name),
            raw_entry,
            name_field=name_field,
            item_label=item_label,
        )
        entries[entry.name] = entry
    return entries


def save_blacklist_entries(
    base_dir: Path,
    file_name: str,
    entries: dict[str, LocalBlacklistEntry],
    *,
    name_field: str,
) -> None:
    file_path = build_blacklist_file_path(base_dir, file_name)
    payload = {
        BLACKLIST_ROOT_KEY: {
            item_name: {
                name_field: entry.name,
                "created_at": _serialize_timestamp(entry.created_at),
                "last_hit_at": _serialize_timestamp(entry.last_hit_at),
            }
            for item_name, entry in sorted(entries.items())
        }
    }
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file_path = file_path.with_name(f"{file_path.name}.tmp")
    temp_file_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_file_path.replace(file_path)


def load_active_blacklist_names(
    base_dir: Path,
    file_name: str,
    ttl_seconds: int,
    *,
    name_field: str,
    item_label: str,
    now: datetime | None = None,
) -> frozenset[str]:
    current_time = now or _current_time()
    ttl = timedelta(seconds=ttl_seconds)
    entries = load_blacklist_entries(
        base_dir,
        file_name,
        name_field=name_field,
        item_label=item_label,
    )
    return frozenset(
        item_name
        for item_name, entry in entries.items()
        if current_time - entry.last_hit_at < ttl
    )


def record_blacklist_hit(
    base_dir: Path,
    file_name: str,
    item_name: str,
    *,
    name_field: str,
    item_label: str,
    now: datetime | None = None,
) -> bool:
    normalized_name = normalize_blacklist_name(item_name)
    if not normalized_name:
        raise RuntimeError(f"写入本地黑名单失败：{item_label}名称为空。")

    current_time = now or _current_time()
    entries = load_blacklist_entries(
        base_dir,
        file_name,
        name_field=name_field,
        item_label=item_label,
    )
    existing_entry = entries.get(normalized_name)
    created_at = current_time if existing_entry is None else existing_entry.created_at
    entries[normalized_name] = LocalBlacklistEntry(
        name=normalized_name,
        created_at=created_at,
        last_hit_at=current_time,
    )
    save_blacklist_entries(
        base_dir,
        file_name,
        entries,
        name_field=name_field,
    )
    return existing_entry is None
