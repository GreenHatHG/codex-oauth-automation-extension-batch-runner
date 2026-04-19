"""Profile name validation and path helpers."""

from __future__ import annotations

import argparse
from pathlib import Path

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
