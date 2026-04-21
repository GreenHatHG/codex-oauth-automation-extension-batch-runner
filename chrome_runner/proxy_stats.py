"""Local persistent proxy status helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .constants import PROXY_STATS_FILE_NAME, PROXY_SUCCESS_FAILURE_THRESHOLD

PROXY_STATS_ROOT_KEY = "entries"
PROXY_STATS_NAME_FIELD = "proxy_name"
PROXY_STATS_IS_SUCCESS_PROXY_FIELD = "is_success_proxy"
PROXY_STATS_CONSECUTIVE_FAILURES_FIELD = "consecutive_failures"
PROXY_STATS_LAST_SUCCESS_AT_FIELD = "last_success_at"
PROXY_STATS_LEGACY_SUCCESS_DAYS_FIELD = "success_days"
PROXY_STATS_ITEM_LABEL = "节点"


@dataclass(frozen=True)
class ProxyStatsEntry:
    """Single proxy status record."""

    proxy_name: str
    is_success_proxy: bool = False
    consecutive_failures: int = 0
    last_success_at: datetime | None = None


@dataclass(frozen=True)
class ProxyFailureRecordResult:
    """Result of recording one proxy failure."""

    entry: ProxyStatsEntry
    did_demote_success_proxy: bool


def normalize_proxy_stats_name(value: object) -> str:
    return str(value or "").strip()


def _current_time() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def _parse_non_negative_int(
    raw_value: object,
    *,
    field_name: str,
    proxy_name: str,
) -> int:
    if not isinstance(raw_value, int) or raw_value < 0:
        raise RuntimeError(f"节点状态记录的 {field_name} 无效：{proxy_name}")
    return raw_value


def _parse_bool(
    raw_value: object,
    *,
    field_name: str,
    proxy_name: str,
) -> bool:
    if not isinstance(raw_value, bool):
        raise RuntimeError(f"节点状态记录的 {field_name} 无效：{proxy_name}")
    return raw_value


def _parse_date_bucket(raw_value: object, *, proxy_name: str) -> date:
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise RuntimeError(f"节点状态记录的日期桶无效：{proxy_name}")
    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"节点状态记录的日期桶格式无效：{proxy_name}") from exc


def _parse_optional_timestamp(
    raw_value: object,
    *,
    field_name: str,
    proxy_name: str,
) -> datetime | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise RuntimeError(f"节点状态记录的 {field_name} 无效：{proxy_name}")
    try:
        parsed_value = datetime.fromisoformat(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"节点状态记录的 {field_name} 格式无效：{proxy_name}") from exc
    if parsed_value.tzinfo is None:
        raise RuntimeError(f"节点状态记录的 {field_name} 缺少时区：{proxy_name}")
    return parsed_value


def _serialize_optional_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone().replace(microsecond=0).isoformat()


def _parse_legacy_success_days(
    raw_value: object,
    *,
    proxy_name: str,
) -> dict[str, int]:
    if raw_value is None:
        return {}
    if not isinstance(raw_value, dict):
        raise RuntimeError(
            f"节点状态记录的 {PROXY_STATS_LEGACY_SUCCESS_DAYS_FIELD} 格式无效：{proxy_name}"
        )
    parsed_success_days: dict[str, int] = {}
    for raw_day, raw_count in raw_value.items():
        bucket_date = _parse_date_bucket(raw_day, proxy_name=proxy_name)
        parsed_success_days[bucket_date.isoformat()] = _parse_non_negative_int(
            raw_count,
            field_name=(
                f"{PROXY_STATS_LEGACY_SUCCESS_DAYS_FIELD}.{bucket_date.isoformat()}"
            ),
            proxy_name=proxy_name,
        )
    return parsed_success_days


def _resolve_legacy_last_success_at(success_days: dict[str, int]) -> datetime | None:
    if not success_days:
        return None
    latest_day = max(success_days)
    latest_date = date.fromisoformat(latest_day)
    current_timezone = _current_time().tzinfo
    return datetime(
        latest_date.year,
        latest_date.month,
        latest_date.day,
        tzinfo=current_timezone,
    )


def _is_legacy_entry(raw_entry: dict[str, object]) -> bool:
    return (
        PROXY_STATS_IS_SUCCESS_PROXY_FIELD not in raw_entry
        and PROXY_STATS_CONSECUTIVE_FAILURES_FIELD not in raw_entry
        and PROXY_STATS_LAST_SUCCESS_AT_FIELD not in raw_entry
    )


def _parse_legacy_entry(
    proxy_name: str,
    raw_entry: dict[str, object],
) -> ProxyStatsEntry:
    success_days = _parse_legacy_success_days(
        raw_entry.get(PROXY_STATS_LEGACY_SUCCESS_DAYS_FIELD),
        proxy_name=proxy_name,
    )
    return ProxyStatsEntry(
        proxy_name=proxy_name,
        is_success_proxy=True,
        consecutive_failures=0,
        last_success_at=_resolve_legacy_last_success_at(success_days),
    )


def _parse_current_entry(
    proxy_name: str,
    raw_entry: dict[str, object],
) -> ProxyStatsEntry:
    is_success_proxy = _parse_bool(
        raw_entry.get(PROXY_STATS_IS_SUCCESS_PROXY_FIELD, False),
        field_name=PROXY_STATS_IS_SUCCESS_PROXY_FIELD,
        proxy_name=proxy_name,
    )
    consecutive_failures = _parse_non_negative_int(
        raw_entry.get(PROXY_STATS_CONSECUTIVE_FAILURES_FIELD, 0),
        field_name=PROXY_STATS_CONSECUTIVE_FAILURES_FIELD,
        proxy_name=proxy_name,
    )
    return ProxyStatsEntry(
        proxy_name=proxy_name,
        is_success_proxy=is_success_proxy,
        consecutive_failures=consecutive_failures,
        last_success_at=_parse_optional_timestamp(
            raw_entry.get(PROXY_STATS_LAST_SUCCESS_AT_FIELD),
            field_name=PROXY_STATS_LAST_SUCCESS_AT_FIELD,
            proxy_name=proxy_name,
        ),
    )


def _parse_entry(
    item_name: str,
    raw_entry: object,
) -> ProxyStatsEntry:
    if not isinstance(raw_entry, dict):
        raise RuntimeError(f"节点状态记录格式无效：{item_name}")
    proxy_name = normalize_proxy_stats_name(
        raw_entry.get(PROXY_STATS_NAME_FIELD, item_name)
    )
    if not proxy_name:
        raise RuntimeError(f"节点状态记录缺少{PROXY_STATS_ITEM_LABEL}名称。")
    if _is_legacy_entry(raw_entry):
        return _parse_legacy_entry(proxy_name, raw_entry)
    return _parse_current_entry(proxy_name, raw_entry)


def build_proxy_stats_file_path(base_dir: Path) -> Path:
    return base_dir / PROXY_STATS_FILE_NAME


def load_proxy_stats_entries(base_dir: Path) -> dict[str, ProxyStatsEntry]:
    file_path = build_proxy_stats_file_path(base_dir)
    if not file_path.is_file():
        return {}
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"节点状态文件不是有效 JSON：{file_path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"节点状态文件格式无效：{file_path}")
    raw_entries = payload.get(PROXY_STATS_ROOT_KEY, {})
    if not isinstance(raw_entries, dict):
        raise RuntimeError(f"节点状态 entries 字段格式无效：{file_path}")

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
                PROXY_STATS_IS_SUCCESS_PROXY_FIELD: entry.is_success_proxy,
                PROXY_STATS_CONSECUTIVE_FAILURES_FIELD: entry.consecutive_failures,
                PROXY_STATS_LAST_SUCCESS_AT_FIELD: _serialize_optional_timestamp(
                    entry.last_success_at
                ),
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


def _build_default_entry(proxy_name: str) -> ProxyStatsEntry:
    return ProxyStatsEntry(proxy_name=proxy_name)


def record_proxy_success(
    base_dir: Path,
    proxy_name: str,
    *,
    now: datetime | None = None,
) -> ProxyStatsEntry:
    normalized_name = normalize_proxy_stats_name(proxy_name)
    if not normalized_name:
        raise RuntimeError(f"写入节点状态失败：{PROXY_STATS_ITEM_LABEL}名称为空。")

    current_time = now or _current_time()
    entries = load_proxy_stats_entries(base_dir)
    updated_entry = ProxyStatsEntry(
        proxy_name=normalized_name,
        is_success_proxy=True,
        consecutive_failures=0,
        last_success_at=current_time,
    )
    entries[normalized_name] = updated_entry
    save_proxy_stats_entries(base_dir, entries)
    return updated_entry


def record_proxy_failure(
    base_dir: Path,
    proxy_name: str,
) -> ProxyFailureRecordResult:
    normalized_name = normalize_proxy_stats_name(proxy_name)
    if not normalized_name:
        raise RuntimeError(f"写入节点状态失败：{PROXY_STATS_ITEM_LABEL}名称为空。")

    entries = load_proxy_stats_entries(base_dir)
    existing_entry = entries.get(normalized_name, _build_default_entry(normalized_name))
    next_failure_count = min(
        existing_entry.consecutive_failures + 1,
        PROXY_SUCCESS_FAILURE_THRESHOLD,
    )
    updated_entry = ProxyStatsEntry(
        proxy_name=normalized_name,
        is_success_proxy=(
            existing_entry.is_success_proxy
            and next_failure_count < PROXY_SUCCESS_FAILURE_THRESHOLD
        ),
        consecutive_failures=next_failure_count,
        last_success_at=existing_entry.last_success_at,
    )
    entries[normalized_name] = updated_entry
    save_proxy_stats_entries(base_dir, entries)
    return ProxyFailureRecordResult(
        entry=updated_entry,
        did_demote_success_proxy=(
            existing_entry.is_success_proxy and not updated_entry.is_success_proxy
        ),
    )


def build_proxy_priority_sort_key(
    proxy_name: str,
    entries: Mapping[str, ProxyStatsEntry],
) -> tuple[int, float]:
    normalized_name = normalize_proxy_stats_name(proxy_name)
    entry = entries.get(normalized_name)
    if entry is None or not entry.is_success_proxy:
        return (1, 0.0)
    last_success_timestamp = (
        entry.last_success_at.timestamp() if entry.last_success_at is not None else 0.0
    )
    return (0, -last_success_timestamp)
