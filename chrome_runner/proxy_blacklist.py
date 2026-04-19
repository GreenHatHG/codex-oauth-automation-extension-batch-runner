"""Local persistent proxy blacklist helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .constants import PROXY_BLACKLIST_FILE_NAME
from .ttl_blacklist import (
    LocalBlacklistEntry,
    build_blacklist_file_path,
    load_active_blacklist_names,
    load_blacklist_entries,
    record_blacklist_hit,
    save_blacklist_entries,
)

PROXY_BLACKLIST_NAME_FIELD = "proxy_name"
PROXY_BLACKLIST_ITEM_LABEL = "节点"
ProxyBlacklistEntry = LocalBlacklistEntry


def build_proxy_blacklist_file_path(base_dir: Path) -> Path:
    return build_blacklist_file_path(base_dir, PROXY_BLACKLIST_FILE_NAME)


def load_proxy_blacklist_entries(base_dir: Path) -> dict[str, ProxyBlacklistEntry]:
    return load_blacklist_entries(
        base_dir,
        PROXY_BLACKLIST_FILE_NAME,
        name_field=PROXY_BLACKLIST_NAME_FIELD,
        item_label=PROXY_BLACKLIST_ITEM_LABEL,
    )


def save_proxy_blacklist_entries(
    base_dir: Path,
    entries: dict[str, ProxyBlacklistEntry],
) -> None:
    save_blacklist_entries(
        base_dir,
        PROXY_BLACKLIST_FILE_NAME,
        entries,
        name_field=PROXY_BLACKLIST_NAME_FIELD,
    )


def load_active_proxy_blacklist_names(
    base_dir: Path,
    ttl_seconds: int,
    *,
    now: datetime | None = None,
) -> frozenset[str]:
    return load_active_blacklist_names(
        base_dir,
        PROXY_BLACKLIST_FILE_NAME,
        ttl_seconds,
        name_field=PROXY_BLACKLIST_NAME_FIELD,
        item_label=PROXY_BLACKLIST_ITEM_LABEL,
        now=now,
    )


def record_proxy_blacklist_hit(
    base_dir: Path,
    proxy_name: str,
    *,
    now: datetime | None = None,
) -> bool:
    return record_blacklist_hit(
        base_dir,
        PROXY_BLACKLIST_FILE_NAME,
        proxy_name,
        name_field=PROXY_BLACKLIST_NAME_FIELD,
        item_label=PROXY_BLACKLIST_ITEM_LABEL,
        now=now,
    )
