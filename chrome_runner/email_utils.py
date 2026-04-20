"""Shared email validation and file loading helpers."""

from __future__ import annotations

import re
from pathlib import Path

EMAIL_LOCAL_PART_PATTERN = r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+"
EMAIL_DOMAIN_PART_PATTERN = r"(?:[A-Za-z0-9-]+\.)+[A-Za-z0-9-]+"
EMAIL_ADDRESS_PATTERN = rf"{EMAIL_LOCAL_PART_PATTERN}@{EMAIL_DOMAIN_PART_PATTERN}"
EMAIL_ADDRESS_REGEX = re.compile(rf"^{EMAIL_ADDRESS_PATTERN}$")


def normalize_email_text(raw_value: object) -> str:
    return str(raw_value or "").strip()


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_ADDRESS_REGEX.fullmatch(normalize_email_text(email)))


def load_email_lines(file_path: Path) -> tuple[str, ...]:
    normalized_file_path = file_path.expanduser()
    if not normalized_file_path.is_file():
        raise FileNotFoundError(f"邮箱文件不存在：{normalized_file_path}")

    seen_email_keys: set[str] = set()
    emails: list[str] = []
    for line_number, raw_line in enumerate(
        normalized_file_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        email = normalize_email_text(raw_line)
        if not email:
            continue
        if not is_valid_email(email):
            raise RuntimeError(
                f"邮箱文件第 {line_number} 行不是有效邮箱：{email}"
            )
        email_key = email.casefold()
        if email_key in seen_email_keys:
            continue
        seen_email_keys.add(email_key)
        emails.append(email)

    if not emails:
        raise RuntimeError(f"邮箱文件里没有可用邮箱：{normalized_file_path}")
    return tuple(emails)


def save_email_lines(file_path: Path, emails: list[str] | tuple[str, ...]) -> None:
    normalized_file_path = file_path.expanduser()
    normalized_emails = [normalize_email_text(email) for email in emails]
    file_text = ""
    if normalized_emails:
        file_text = "\n".join(normalized_emails) + "\n"

    normalized_file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file_path = normalized_file_path.with_name(
        f"{normalized_file_path.name}.tmp"
    )
    temp_file_path.write_text(file_text, encoding="utf-8")
    temp_file_path.replace(normalized_file_path)
