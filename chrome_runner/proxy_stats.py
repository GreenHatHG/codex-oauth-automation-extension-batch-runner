"""Local persistent proxy statistics helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from .constants import PROXY_STATS_FILE_NAME

PROXY_STATS_ROOT_KEY = "entries"
PROXY_STATS_NAME_FIELD = "proxy_name"
PROXY_STATS_SUCCESS_DAYS_FIELD = "success_days"
PROXY_STATS_ITEM_LABEL = "节点"
PROXY_SUCCESS_WINDOW_DAYS = 7


@dataclass(frozen=True)
class ProxyStatsEntry:
    """Single proxy statistics record."""

    proxy_name: str
    success_days: dict[str, int] = field(default_factory=dict)

    @property
    def success_count(self) -> int:
        return sum(self.success_days.values())


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
        raise RuntimeError(f"节点统计记录的 {field_name} 无效：{proxy_name}")
    return raw_value


def _parse_date_bucket(raw_value: object, *, proxy_name: str) -> date:
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise RuntimeError(f"节点统计记录的日期桶无效：{proxy_name}")
    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"节点统计记录的日期桶格式无效：{proxy_name}") from exc


def _prune_success_days(
    raw_success_days: Mapping[str, int],
    *,
    current_date: date,
) -> dict[str, int]:
    window_start = current_date - timedelta(days=PROXY_SUCCESS_WINDOW_DAYS - 1)
    return {
        day_text: count
        for day_text, count in raw_success_days.items()
        if count > 0 and date.fromisoformat(day_text) >= window_start
    }


def _parse_success_days(
    raw_value: object,
    *,
    proxy_name: str,
    current_date: date,
) -> dict[str, int]:
    if raw_value is None:
        return {}
    if not isinstance(raw_value, dict):
        raise RuntimeError(f"节点统计记录的 {PROXY_STATS_SUCCESS_DAYS_FIELD} 格式无效：{proxy_name}")
    parsed_success_days: dict[str, int] = {}
    for raw_day, raw_count in raw_value.items():
        bucket_date = _parse_date_bucket(raw_day, proxy_name=proxy_name)
        day_text = bucket_date.isoformat()
        parsed_success_days[day_text] = _parse_non_negative_int(
            raw_count,
            field_name=f"{PROXY_STATS_SUCCESS_DAYS_FIELD}.{day_text}",
            proxy_name=proxy_name,
        )
    return _prune_success_days(parsed_success_days, current_date=current_date)


def _parse_entry(
    item_name: str,
    raw_entry: object,
    *,
    current_date: date,
) -> ProxyStatsEntry:
    if not isinstance(raw_entry, dict):
        raise RuntimeError(f"节点统计记录格式无效：{item_name}")
    proxy_name = normalize_proxy_stats_name(
        raw_entry.get(PROXY_STATS_NAME_FIELD, item_name)
    )
    if not proxy_name:
        raise RuntimeError(f"节点统计记录缺少{PROXY_STATS_ITEM_LABEL}名称。")
    return ProxyStatsEntry(
        proxy_name=proxy_name,
        success_days=_parse_success_days(
            raw_entry.get(PROXY_STATS_SUCCESS_DAYS_FIELD),
            proxy_name=proxy_name,
            current_date=current_date,
        ),
    )


def build_proxy_stats_file_path(base_dir: Path) -> Path:
    return base_dir / PROXY_STATS_FILE_NAME


def load_proxy_stats_entries(
    base_dir: Path,
    *,
    now: datetime | None = None,
) -> dict[str, ProxyStatsEntry]:
    file_path = build_proxy_stats_file_path(base_dir)
    if not file_path.is_file():
        return {}
    current_date = (now or _current_time()).date()
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
        entry = _parse_entry(
            str(item_name),
            raw_entry,
            current_date=current_date,
        )
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
                PROXY_STATS_SUCCESS_DAYS_FIELD: dict(sorted(entry.success_days.items())),
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


def record_proxy_success(
    base_dir: Path,
    proxy_name: str,
    *,
    now: datetime | None = None,
) -> ProxyStatsEntry:
    normalized_name = normalize_proxy_stats_name(proxy_name)
    if not normalized_name:
        raise RuntimeError(f"写入节点统计失败：{PROXY_STATS_ITEM_LABEL}名称为空。")

    current_time = now or _current_time()
    entries = load_proxy_stats_entries(base_dir, now=current_time)
    existing_entry = entries.get(
        normalized_name,
        ProxyStatsEntry(proxy_name=normalized_name),
    )
    updated_success_days = dict(existing_entry.success_days)
    success_day = current_time.date().isoformat()
    updated_success_days[success_day] = updated_success_days.get(success_day, 0) + 1
    updated_entry = ProxyStatsEntry(
        proxy_name=normalized_name,
        success_days=_prune_success_days(
            updated_success_days,
            current_date=current_time.date(),
        ),
    )
    entries[normalized_name] = updated_entry
    save_proxy_stats_entries(base_dir, entries)
    return updated_entry


def build_proxy_priority_sort_key(
    proxy_name: str,
    entries: Mapping[str, ProxyStatsEntry],
) -> int:
    normalized_name = normalize_proxy_stats_name(proxy_name)
    entry = entries.get(normalized_name)
    if entry is None:
        return 0
    return -entry.success_count
