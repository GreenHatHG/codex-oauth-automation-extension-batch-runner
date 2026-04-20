"""Profile name validation and path helpers."""

from __future__ import annotations

import argparse
from pathlib import Path

from .constants import PROFILE_MAILBOX_SITE_REFERENCES, PROFILE_PREFERENCES_RELATIVE_PATH

INVALID_PROFILE_NAME_MESSAGE = "profile 名称必须是项目目录下的子目录名。"


def parse_profile_name(raw_value: str) -> str:
    profile_name = raw_value.strip()
    if not profile_name or "/" in profile_name or "\\" in profile_name:
        raise argparse.ArgumentTypeError(INVALID_PROFILE_NAME_MESSAGE)
    if profile_name in {".", ".."}:
        raise argparse.ArgumentTypeError(INVALID_PROFILE_NAME_MESSAGE)
    return profile_name


def resolve_profile_dir(base_dir: Path, profile_name: str) -> Path:
    return base_dir / profile_name


def build_profile_preferences_path(profile_dir: Path) -> Path:
    return profile_dir.joinpath(*PROFILE_PREFERENCES_RELATIVE_PATH)


def profile_contains_site_reference(profile_dir: Path, site_reference: str) -> bool:
    preferences_path = build_profile_preferences_path(profile_dir)
    if not preferences_path.is_file():
        return False
    return site_reference in preferences_path.read_text(encoding="utf-8")


def profile_uses_blacklistable_mailbox(profile_dir: Path) -> bool:
    return any(
        profile_contains_site_reference(profile_dir, site_reference)
        for site_reference in PROFILE_MAILBOX_SITE_REFERENCES
    )
