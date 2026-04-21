"""Helpers for extracting and persisting add-phone failure emails."""

from __future__ import annotations

import argparse
import re
from collections.abc import Collection
from pathlib import Path

from .constants import CURRENT_EMAIL_LOG_PREFIX, FAILED_ADD_PHONE_EMAILS_FILE_NAME
from .email_utils import EMAIL_ADDRESS_PATTERN
from .profile import parse_profile_name

CURRENT_EMAIL_PATTERN = re.compile(
    rf"{re.escape(CURRENT_EMAIL_LOG_PREFIX)}\s*"
    rf"({EMAIL_ADDRESS_PATTERN})"
)
FAILED_ADD_PHONE_EMAILS_FILE_STEM = Path(FAILED_ADD_PHONE_EMAILS_FILE_NAME).stem
FAILED_ADD_PHONE_EMAILS_FILE_SUFFIX = Path(FAILED_ADD_PHONE_EMAILS_FILE_NAME).suffix
FAILED_ADD_PHONE_EMAILS_FILE_PREFIX = f"{FAILED_ADD_PHONE_EMAILS_FILE_STEM}."
EMPTY_PROFILE_NAME_ERROR_MESSAGE = "写入 add-phone 失败邮箱失败：profile 为空。"


def extract_latest_current_email(messages: Collection[str]) -> str:
    latest_email = ""
    for message in messages:
        for match in CURRENT_EMAIL_PATTERN.finditer(message):
            latest_email = match.group(1).strip()
    return latest_email


def build_failed_add_phone_emails_file_path(
    base_dir: Path,
    profile_name: str,
) -> Path:
    normalized_profile_name = profile_name.strip()
    if not normalized_profile_name:
        raise RuntimeError(EMPTY_PROFILE_NAME_ERROR_MESSAGE)
    file_name = (
        f"{FAILED_ADD_PHONE_EMAILS_FILE_STEM}."
        f"{normalized_profile_name}"
        f"{FAILED_ADD_PHONE_EMAILS_FILE_SUFFIX}"
    )
    return base_dir / file_name


def parse_failed_add_phone_profile_name(file_path: Path) -> str | None:
    file_name = file_path.name.strip()
    if not file_name.startswith(FAILED_ADD_PHONE_EMAILS_FILE_PREFIX):
        return None
    if not file_name.endswith(FAILED_ADD_PHONE_EMAILS_FILE_SUFFIX):
        return None
    raw_profile_name = file_name[
        len(FAILED_ADD_PHONE_EMAILS_FILE_PREFIX) : -len(FAILED_ADD_PHONE_EMAILS_FILE_SUFFIX)
    ]
    if not raw_profile_name:
        return None
    try:
        return parse_profile_name(raw_profile_name)
    except argparse.ArgumentTypeError:
        return None


def load_failed_add_phone_emails(
    base_dir: Path,
    profile_name: str,
) -> tuple[str, ...]:
    file_path = build_failed_add_phone_emails_file_path(base_dir, profile_name)
    if not file_path.is_file():
        return ()

    seen_emails: set[str] = set()
    emails: list[str] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        email = line.strip()
        if not email or email in seen_emails:
            continue
        seen_emails.add(email)
        emails.append(email)
    return tuple(emails)


def record_failed_add_phone_email(
    base_dir: Path,
    profile_name: str,
    email: str,
) -> bool:
    normalized_email = email.strip()
    if not normalized_email:
        raise RuntimeError("写入 add-phone 失败邮箱失败：邮箱为空。")

    file_path = build_failed_add_phone_emails_file_path(base_dir, profile_name)
    existing_emails = list(load_failed_add_phone_emails(base_dir, profile_name))
    if normalized_email in existing_emails:
        return False

    existing_emails.append(normalized_email)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file_path = file_path.with_name(f"{file_path.name}.tmp")
    temp_file_path.write_text(
        "\n".join(existing_emails) + "\n",
        encoding="utf-8",
    )
    temp_file_path.replace(file_path)
    return True
