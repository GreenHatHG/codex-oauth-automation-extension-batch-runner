"""Local persistent proxy statistics helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .constants import PROXY_STATS_FILE_NAME

PROXY_STATS_ROOT_KEY = "entries"
PROXY_STATS_NAME_FIELD = "proxy_name"
PROXY_STATS_ITEM_LABEL = "节点"


@dataclass(frozen=True)
class ProxyStatsEntry:
    """Single proxy statistics record."""

    proxy_name: str
    success_count: int = 0
    failure_count: int = 0
    last_selected_at: datetime | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_delay_ms: int | None = None


def normalize_proxy_stats_name(value: object) -> str:
    return str(value or "").strip()


def _current_time() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def _serialize_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone().replace(microsecond=0).isoformat()


def _parse_timestamp(
    raw_value: object,
    *,
    field_name: str,
    proxy_name: str,
) -> datetime | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise RuntimeError(f"节点统计记录缺少 {field_name}：{proxy_name}")
    try:
        parsed_value = datetime.fromisoformat(raw_value)
    except ValueError as exc:
        raise RuntimeError(
            f"节点统计记录的 {field_name} 格式无效：{proxy_name}"
        ) from exc
    if parsed_value.tzinfo is None:
        raise RuntimeError(f"节点统计记录的 {field_name} 缺少时区：{proxy_name}")
    return parsed_value


def _parse_non_negative_int(
    raw_value: object,
    *,
    field_name: str,
    proxy_name: str,
) -> int:
    if not isinstance(raw_value, int) or raw_value < 0:
        raise RuntimeError(f"节点统计记录的 {field_name} 无效：{proxy_name}")
    return raw_value


def _parse_optional_non_negative_int(
    raw_value: object,
    *,
    field_name: str,
    proxy_name: str,
) -> int | None:
    if raw_value is None:
        return None
    return _parse_non_negative_int(
        raw_value,
        field_name=field_name,
        proxy_name=proxy_name,
    )


def _parse_entry(item_name: str, raw_entry: object) -> ProxyStatsEntry:
    if not isinstance(raw_entry, dict):
        raise RuntimeError(f"节点统计记录格式无效：{item_name}")
    proxy_name = normalize_proxy_stats_name(
        raw_entry.get(PROXY_STATS_NAME_FIELD, item_name)
    )
    if not proxy_name:
        raise RuntimeError(f"节点统计记录缺少{PROXY_STATS_ITEM_LABEL}名称。")
    return ProxyStatsEntry(
        proxy_name=proxy_name,
        success_count=_parse_non_negative_int(
            raw_entry.get("success_count", 0),
            field_name="success_count",
            proxy_name=proxy_name,
        ),
        failure_count=_parse_non_negative_int(
            raw_entry.get("failure_count", 0),
            field_name="failure_count",
            proxy_name=proxy_name,
        ),
        last_selected_at=_parse_timestamp(
            raw_entry.get("last_selected_at"),
            field_name="last_selected_at",
            proxy_name=proxy_name,
        ),
        last_success_at=_parse_timestamp(
            raw_entry.get("last_success_at"),
            field_name="last_success_at",
            proxy_name=proxy_name,
        ),
        last_failure_at=_parse_timestamp(
            raw_entry.get("last_failure_at"),
            field_name="last_failure_at",
            proxy_name=proxy_name,
        ),
        last_delay_ms=_parse_optional_non_negative_int(
            raw_entry.get("last_delay_ms"),
            field_name="last_delay_ms",
            proxy_name=proxy_name,
        ),
    )


def build_proxy_stats_file_path(base_dir: Path) -> Path:
    return base_dir / PROXY_STATS_FILE_NAME


def load_proxy_stats_entries(base_dir: Path) -> dict[str, ProxyStatsEntry]:
    file_path = build_proxy_stats_file_path(base_dir)
    if not file_path.is_file():
        return {}
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"节点统计文件不是有效 JSON：{file_path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"节点统计文件格式无效：{file_path}")
    raw_entries = payload.get(PROXY_STATS_ROOT_KEY, {})
    if not isinstance(raw_entries, dict):
        raise RuntimeError(f"节点统计 entries 字段格式无效：{file_path}")

    entries: dict[str, ProxyStatsEntry] = {}
    for item_name, raw_entry in raw_entries.items():
        entry = _parse_entry(str(item_name), raw_entry)
        entries[entry.proxy_name] = entry
    return entries


def save_proxy_stats_entries(
    base_dir: Path,
    entries: Mapping[str, ProxyStatsEntry],
) -> None:
    file_path = build_proxy_stats_file_path(base_dir)
    payload = {
        PROXY_STATS_ROOT_KEY: {
            proxy_name: {
                PROXY_STATS_NAME_FIELD: entry.proxy_name,
                "success_count": entry.success_count,
                "failure_count": entry.failure_count,
                "last_selected_at": _serialize_timestamp(entry.last_selected_at),
                "last_success_at": _serialize_timestamp(entry.last_success_at),
                "last_failure_at": _serialize_timestamp(entry.last_failure_at),
                "last_delay_ms": entry.last_delay_ms,
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


def list_active_proxy_cooldown_names(
    entries: Mapping[str, ProxyStatsEntry],
    ttl_seconds: int,
    *,
    now: datetime | None = None,
) -> frozenset[str]:
    current_time = now or _current_time()
    ttl = timedelta(seconds=ttl_seconds)
    return frozenset(
        proxy_name
        for proxy_name, entry in entries.items()
        if entry.last_failure_at is not None
        and current_time - entry.last_failure_at < ttl
    )


def record_proxy_selection(
    base_dir: Path,
    proxy_name: str,
    *,
    delay_ms: int | None = None,
    now: datetime | None = None,
) -> ProxyStatsEntry:
    normalized_name = normalize_proxy_stats_name(proxy_name)
    if not normalized_name:
        raise RuntimeError(f"写入节点统计失败：{PROXY_STATS_ITEM_LABEL}名称为空。")

    current_time = now or _current_time()
    entries = load_proxy_stats_entries(base_dir)
    existing_entry = entries.get(
        normalized_name,
        ProxyStatsEntry(proxy_name=normalized_name),
    )
    updated_entry = ProxyStatsEntry(
        proxy_name=normalized_name,
        success_count=existing_entry.success_count,
        failure_count=existing_entry.failure_count,
        last_selected_at=current_time,
        last_success_at=existing_entry.last_success_at,
        last_failure_at=existing_entry.last_failure_at,
        last_delay_ms=delay_ms if delay_ms is not None else existing_entry.last_delay_ms,
    )
    entries[normalized_name] = updated_entry
    save_proxy_stats_entries(base_dir, entries)
    return updated_entry


def record_proxy_run_result(
    base_dir: Path,
    proxy_name: str,
    *,
    succeeded: bool,
    now: datetime | None = None,
) -> ProxyStatsEntry:
    normalized_name = normalize_proxy_stats_name(proxy_name)
    if not normalized_name:
        raise RuntimeError(f"写入节点统计失败：{PROXY_STATS_ITEM_LABEL}名称为空。")

    current_time = now or _current_time()
    entries = load_proxy_stats_entries(base_dir)
    existing_entry = entries.get(
        normalized_name,
        ProxyStatsEntry(proxy_name=normalized_name),
    )
    updated_entry = ProxyStatsEntry(
        proxy_name=normalized_name,
        success_count=existing_entry.success_count + int(succeeded),
        failure_count=existing_entry.failure_count + int(not succeeded),
        last_selected_at=existing_entry.last_selected_at or current_time,
        last_success_at=current_time if succeeded else existing_entry.last_success_at,
        last_failure_at=current_time if not succeeded else existing_entry.last_failure_at,
        last_delay_ms=existing_entry.last_delay_ms,
    )
    entries[normalized_name] = updated_entry
    save_proxy_stats_entries(base_dir, entries)
    return updated_entry


def build_proxy_priority_sort_key(
    proxy_name: str,
    entries: Mapping[str, ProxyStatsEntry],
) -> tuple[int, int, int | float, str]:
    normalized_name = normalize_proxy_stats_name(proxy_name)
    entry = entries.get(normalized_name)
    if entry is None:
        return (0, 0, float("inf"), normalized_name)
    delay_sort_key = entry.last_delay_ms if entry.last_delay_ms is not None else float("inf")
    return (
        entry.failure_count,
        -entry.success_count,
        delay_sort_key,
        normalized_name,
    )
