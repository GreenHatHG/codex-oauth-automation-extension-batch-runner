"""Helpers for extracting and persisting add-phone failure emails."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from .constants import (
    CURRENT_EMAIL_LOG_PREFIX,
    FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_FILE_NAME,
    FAILED_ADD_PHONE_EMAILS_FILE_NAME,
)
from .email_utils import EMAIL_ADDRESS_PATTERN, save_email_lines
from .profile import parse_profile_name

CURRENT_EMAIL_PATTERN = re.compile(
    rf"{re.escape(CURRENT_EMAIL_LOG_PREFIX)}\s*"
    rf"({EMAIL_ADDRESS_PATTERN})"
)
FAILED_ADD_PHONE_EMAILS_FILE_STEM = Path(FAILED_ADD_PHONE_EMAILS_FILE_NAME).stem
FAILED_ADD_PHONE_EMAILS_FILE_SUFFIX = Path(FAILED_ADD_PHONE_EMAILS_FILE_NAME).suffix
FAILED_ADD_PHONE_EMAILS_FILE_PREFIX = f"{FAILED_ADD_PHONE_EMAILS_FILE_STEM}."
FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_FILE_STEM = Path(
    FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_FILE_NAME
).stem
FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_FILE_SUFFIX = Path(
    FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_FILE_NAME
).suffix
EMPTY_PROFILE_NAME_ERROR_MESSAGE = "写入 add-phone 失败邮箱失败：profile 为空。"
EMPTY_EMAIL_ERROR_MESSAGE = "写入 add-phone 失败邮箱失败：邮箱为空。"
FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_ROOT_KEY = "counts"
INVALID_FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_MESSAGE = (
    "读取 add-phone 失败邮箱重试次数失败：文件格式无效。"
)
MISSING_FAILED_ADD_PHONE_EMAIL_MESSAGE = (
    "更新 add-phone 失败邮箱重试次数失败：邮箱不在文件中。"
)


@dataclass(frozen=True)
class FailedAddPhoneEmailRetryResult:
    """Retry count update result for one failed add-phone email."""

    retry_count: int
    did_remove_email: bool
    remaining_email_count: int


def extract_latest_current_email(messages: Collection[str]) -> str:
    latest_email = ""
    for message in messages:
        for match in CURRENT_EMAIL_PATTERN.finditer(message):
            latest_email = match.group(1).strip()
    return latest_email


def _build_profile_scoped_file_path(
    base_dir: Path,
    profile_name: str,
    *,
    file_stem: str,
    file_suffix: str,
) -> Path:
    normalized_profile_name = profile_name.strip()
    if not normalized_profile_name:
        raise RuntimeError(EMPTY_PROFILE_NAME_ERROR_MESSAGE)
    file_name = f"{file_stem}.{normalized_profile_name}{file_suffix}"
    return base_dir / file_name


def build_failed_add_phone_emails_file_path(
    base_dir: Path,
    profile_name: str,
) -> Path:
    return _build_profile_scoped_file_path(
        base_dir,
        profile_name,
        file_stem=FAILED_ADD_PHONE_EMAILS_FILE_STEM,
        file_suffix=FAILED_ADD_PHONE_EMAILS_FILE_SUFFIX,
    )


def build_failed_add_phone_email_retry_counts_file_path(
    base_dir: Path,
    profile_name: str,
) -> Path:
    return _build_profile_scoped_file_path(
        base_dir,
        profile_name,
        file_stem=FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_FILE_STEM,
        file_suffix=FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_FILE_SUFFIX,
    )


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


def _build_email_key(email: str) -> str:
    return email.casefold()


def _remove_email_from_pending_list(
    pending_emails: list[str],
    email: str,
) -> list[str]:
    email_key = _build_email_key(email)
    for index, pending_email in enumerate(pending_emails):
        if _build_email_key(pending_email) == email_key:
            return [
                *pending_emails[:index],
                *pending_emails[index + 1 :],
            ]
    raise RuntimeError(f"{MISSING_FAILED_ADD_PHONE_EMAIL_MESSAGE} {email}")


def _filter_retry_counts(
    retry_counts: dict[str, int],
    pending_emails: Collection[str],
) -> dict[str, int]:
    pending_email_keys = {_build_email_key(email) for email in pending_emails}
    return {
        email_key: retry_count
        for email_key, retry_count in retry_counts.items()
        if email_key in pending_email_keys
    }


def _load_failed_add_phone_email_retry_counts(
    base_dir: Path,
    profile_name: str,
) -> dict[str, int]:
    file_path = build_failed_add_phone_email_retry_counts_file_path(base_dir, profile_name)
    if not file_path.is_file():
        return {}
    try:
        raw_payload = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            INVALID_FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_MESSAGE
        ) from exc
    if not isinstance(raw_payload, dict):
        raise RuntimeError(INVALID_FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_MESSAGE)
    raw_counts = raw_payload.get(FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_ROOT_KEY, {})
    if not isinstance(raw_counts, dict):
        raise RuntimeError(INVALID_FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_MESSAGE)

    retry_counts: dict[str, int] = {}
    for raw_email_key, raw_retry_count in raw_counts.items():
        if not isinstance(raw_email_key, str) or not raw_email_key.strip():
            raise RuntimeError(INVALID_FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_MESSAGE)
        if not isinstance(raw_retry_count, int) or raw_retry_count < 0:
            raise RuntimeError(INVALID_FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_MESSAGE)
        retry_counts[raw_email_key.strip()] = raw_retry_count
    return retry_counts


def _save_failed_add_phone_email_retry_counts(
    base_dir: Path,
    profile_name: str,
    retry_counts: dict[str, int],
) -> None:
    file_path = build_failed_add_phone_email_retry_counts_file_path(base_dir, profile_name)
    if not retry_counts:
        file_path.unlink(missing_ok=True)
        return

    payload = {
        FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_ROOT_KEY: {
            email_key: retry_count
            for email_key, retry_count in sorted(retry_counts.items())
        }
    }
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file_path = file_path.with_name(f"{file_path.name}.tmp")
    temp_file_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_file_path.replace(file_path)


def clear_failed_add_phone_email_retry_count(
    base_dir: Path,
    profile_name: str,
    email: str,
) -> None:
    normalized_email = email.strip()
    if not normalized_email:
        raise RuntimeError(EMPTY_EMAIL_ERROR_MESSAGE)

    retry_counts = _load_failed_add_phone_email_retry_counts(base_dir, profile_name)
    email_key = _build_email_key(normalized_email)
    if email_key not in retry_counts:
        return
    retry_counts.pop(email_key)
    _save_failed_add_phone_email_retry_counts(base_dir, profile_name, retry_counts)


def remove_failed_add_phone_email(
    base_dir: Path,
    profile_name: str,
    email: str,
) -> tuple[str, ...]:
    normalized_email = email.strip()
    if not normalized_email:
        raise RuntimeError(EMPTY_EMAIL_ERROR_MESSAGE)

    pending_emails = list(load_failed_add_phone_emails(base_dir, profile_name))
    next_pending_emails = _remove_email_from_pending_list(
        pending_emails,
        normalized_email,
    )
    save_email_lines(
        build_failed_add_phone_emails_file_path(base_dir, profile_name),
        next_pending_emails,
    )
    retry_counts = _filter_retry_counts(
        _load_failed_add_phone_email_retry_counts(base_dir, profile_name),
        next_pending_emails,
    )
    _save_failed_add_phone_email_retry_counts(base_dir, profile_name, retry_counts)
    return tuple(next_pending_emails)


def record_failed_add_phone_email_retry(
    base_dir: Path,
    profile_name: str,
    email: str,
    *,
    max_retry_count: int,
) -> FailedAddPhoneEmailRetryResult:
    normalized_email = email.strip()
    if not normalized_email:
        raise RuntimeError(EMPTY_EMAIL_ERROR_MESSAGE)
    if max_retry_count < 1:
        raise RuntimeError("更新 add-phone 失败邮箱重试次数失败：最大重试次数必须大于 0。")

    pending_emails = list(load_failed_add_phone_emails(base_dir, profile_name))
    pending_email_keys = {_build_email_key(item) for item in pending_emails}
    email_key = _build_email_key(normalized_email)
    if email_key not in pending_email_keys:
        raise RuntimeError(f"{MISSING_FAILED_ADD_PHONE_EMAIL_MESSAGE} {normalized_email}")

    retry_counts = _filter_retry_counts(
        _load_failed_add_phone_email_retry_counts(base_dir, profile_name),
        pending_emails,
    )
    next_retry_count = retry_counts.get(email_key, 0) + 1
    if next_retry_count >= max_retry_count:
        next_pending_emails = remove_failed_add_phone_email(
            base_dir,
            profile_name,
            normalized_email,
        )
        return FailedAddPhoneEmailRetryResult(
            retry_count=next_retry_count,
            did_remove_email=True,
            remaining_email_count=len(next_pending_emails),
        )

    retry_counts[email_key] = next_retry_count
    _save_failed_add_phone_email_retry_counts(base_dir, profile_name, retry_counts)
    return FailedAddPhoneEmailRetryResult(
        retry_count=next_retry_count,
        did_remove_email=False,
        remaining_email_count=len(pending_emails),
    )


def record_failed_add_phone_email(
    base_dir: Path,
    profile_name: str,
    email: str,
) -> bool:
    normalized_email = email.strip()
    if not normalized_email:
        raise RuntimeError(EMPTY_EMAIL_ERROR_MESSAGE)

    file_path = build_failed_add_phone_emails_file_path(base_dir, profile_name)
    existing_emails = list(load_failed_add_phone_emails(base_dir, profile_name))
    if normalized_email in existing_emails:
        return False

    existing_emails.append(normalized_email)
    save_email_lines(file_path, existing_emails)
    clear_failed_add_phone_email_retry_count(base_dir, profile_name, normalized_email)
    return True
