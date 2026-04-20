"""Helpers for extracting and persisting add-phone failure emails."""

from __future__ import annotations

import re
from collections.abc import Collection
from pathlib import Path

from .constants import CURRENT_EMAIL_LOG_PREFIX, FAILED_ADD_PHONE_EMAILS_FILE_NAME

EMAIL_LOCAL_PART_PATTERN = r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+"
EMAIL_DOMAIN_PART_PATTERN = r"(?:[A-Za-z0-9-]+\.)+[A-Za-z0-9-]+"
CURRENT_EMAIL_PATTERN = re.compile(
    rf"{re.escape(CURRENT_EMAIL_LOG_PREFIX)}\s*"
    rf"({EMAIL_LOCAL_PART_PATTERN}@{EMAIL_DOMAIN_PART_PATTERN})"
)


def extract_latest_current_email(messages: Collection[str]) -> str:
    latest_email = ""
    for message in messages:
        for match in CURRENT_EMAIL_PATTERN.finditer(message):
            latest_email = match.group(1).strip()
    return latest_email


def build_failed_add_phone_emails_file_path(base_dir: Path) -> Path:
    return base_dir / FAILED_ADD_PHONE_EMAILS_FILE_NAME


def load_failed_add_phone_emails(base_dir: Path) -> tuple[str, ...]:
    file_path = build_failed_add_phone_emails_file_path(base_dir)
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


def record_failed_add_phone_email(base_dir: Path, email: str) -> bool:
    normalized_email = email.strip()
    if not normalized_email:
        raise RuntimeError("写入 add-phone 失败邮箱失败：邮箱为空。")

    file_path = build_failed_add_phone_emails_file_path(base_dir)
    existing_emails = list(load_failed_add_phone_emails(base_dir))
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
