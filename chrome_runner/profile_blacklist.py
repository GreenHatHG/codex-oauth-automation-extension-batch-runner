"""Local persistent profile blacklist helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .constants import PROFILE_BLACKLIST_FILE_NAME
from .ttl_blacklist import (
    LocalBlacklistEntry,
    build_blacklist_file_path,
    load_active_blacklist_names,
    load_blacklist_entries,
    record_blacklist_hit,
    save_blacklist_entries,
)

PROFILE_BLACKLIST_NAME_FIELD = "profile_name"
PROFILE_BLACKLIST_ITEM_LABEL = "profile"
ProfileBlacklistEntry = LocalBlacklistEntry


def build_profile_blacklist_file_path(base_dir: Path) -> Path:
    return build_blacklist_file_path(base_dir, PROFILE_BLACKLIST_FILE_NAME)


def load_profile_blacklist_entries(base_dir: Path) -> dict[str, ProfileBlacklistEntry]:
    return load_blacklist_entries(
        base_dir,
        PROFILE_BLACKLIST_FILE_NAME,
        name_field=PROFILE_BLACKLIST_NAME_FIELD,
        item_label=PROFILE_BLACKLIST_ITEM_LABEL,
    )


def save_profile_blacklist_entries(
    base_dir: Path,
    entries: dict[str, ProfileBlacklistEntry],
) -> None:
    save_blacklist_entries(
        base_dir,
        PROFILE_BLACKLIST_FILE_NAME,
        entries,
        name_field=PROFILE_BLACKLIST_NAME_FIELD,
    )


def load_active_profile_blacklist_names(
    base_dir: Path,
    ttl_seconds: int,
    *,
    now: datetime | None = None,
) -> frozenset[str]:
    return load_active_blacklist_names(
        base_dir,
        PROFILE_BLACKLIST_FILE_NAME,
        ttl_seconds,
        name_field=PROFILE_BLACKLIST_NAME_FIELD,
        item_label=PROFILE_BLACKLIST_ITEM_LABEL,
        now=now,
    )


def record_profile_blacklist_hit(
    base_dir: Path,
    profile_name: str,
    *,
    now: datetime | None = None,
) -> bool:
    return record_blacklist_hit(
        base_dir,
        PROFILE_BLACKLIST_FILE_NAME,
        profile_name,
        name_field=PROFILE_BLACKLIST_NAME_FIELD,
        item_label=PROFILE_BLACKLIST_ITEM_LABEL,
        now=now,
    )
