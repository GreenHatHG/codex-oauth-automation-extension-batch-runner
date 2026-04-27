"""Helpers for extracting current email logs and persisting retry email queues."""

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
    FAILED_SIGNUP_EMAIL_RETRY_COUNTS_FILE_NAME,
    FAILED_SIGNUP_EMAILS_FILE_NAME,
)
from .email_utils import EMAIL_ADDRESS_PATTERN, save_email_lines
from .profile import parse_profile_name

CURRENT_EMAIL_PATTERN = re.compile(
    rf"{re.escape(CURRENT_EMAIL_LOG_PREFIX)}\s*"
    rf"({EMAIL_ADDRESS_PATTERN})"
)


@dataclass(frozen=True)
class FailedEmailRetryResult:
    """Retry count update result for one preserved email."""

    retry_count: int
    did_remove_email: bool
    remaining_email_count: int


@dataclass(frozen=True)
class RetryEmailQueueConfig:
    """Queue-specific file names and validation messages."""

    emails_file_stem: str
    emails_file_suffix: str
    retry_counts_file_stem: str
    retry_counts_file_suffix: str
    empty_profile_error_message: str
    empty_email_error_message: str
    invalid_retry_counts_message: str
    missing_email_message: str


FAILED_ADD_PHONE_EMAILS_FILE_STEM = Path(FAILED_ADD_PHONE_EMAILS_FILE_NAME).stem
FAILED_ADD_PHONE_EMAILS_FILE_SUFFIX = Path(FAILED_ADD_PHONE_EMAILS_FILE_NAME).suffix
FAILED_ADD_PHONE_EMAILS_FILE_PREFIX = f"{FAILED_ADD_PHONE_EMAILS_FILE_STEM}."
FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_FILE_STEM = Path(
    FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_FILE_NAME
).stem
FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_FILE_SUFFIX = Path(
    FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_FILE_NAME
).suffix

FAILED_SIGNUP_EMAILS_FILE_STEM = Path(FAILED_SIGNUP_EMAILS_FILE_NAME).stem
FAILED_SIGNUP_EMAILS_FILE_SUFFIX = Path(FAILED_SIGNUP_EMAILS_FILE_NAME).suffix
FAILED_SIGNUP_EMAILS_FILE_PREFIX = f"{FAILED_SIGNUP_EMAILS_FILE_STEM}."
FAILED_SIGNUP_EMAIL_RETRY_COUNTS_FILE_STEM = Path(
    FAILED_SIGNUP_EMAIL_RETRY_COUNTS_FILE_NAME
).stem
FAILED_SIGNUP_EMAIL_RETRY_COUNTS_FILE_SUFFIX = Path(
    FAILED_SIGNUP_EMAIL_RETRY_COUNTS_FILE_NAME
).suffix

FAILED_EMAIL_RETRY_COUNTS_ROOT_KEY = "counts"
EMPTY_FAILED_ADD_PHONE_PROFILE_NAME_ERROR_MESSAGE = (
    "写入 add-phone 失败邮箱失败：profile 为空。"
)
EMPTY_FAILED_ADD_PHONE_EMAIL_ERROR_MESSAGE = "写入 add-phone 失败邮箱失败：邮箱为空。"
INVALID_FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_MESSAGE = (
    "读取 add-phone 失败邮箱重试次数失败：文件格式无效。"
)
MISSING_FAILED_ADD_PHONE_EMAIL_MESSAGE = (
    "更新 add-phone 失败邮箱重试次数失败：邮箱不在文件中。"
)
EMPTY_FAILED_SIGNUP_PROFILE_NAME_ERROR_MESSAGE = (
    "写入注册重跑邮箱失败：profile 为空。"
)
EMPTY_FAILED_SIGNUP_EMAIL_ERROR_MESSAGE = "写入注册重跑邮箱失败：邮箱为空。"
INVALID_FAILED_SIGNUP_EMAIL_RETRY_COUNTS_MESSAGE = (
    "读取注册重跑邮箱重试次数失败：文件格式无效。"
)
MISSING_FAILED_SIGNUP_EMAIL_MESSAGE = (
    "更新注册重跑邮箱重试次数失败：邮箱不在文件中。"
)

ADD_PHONE_QUEUE_CONFIG = RetryEmailQueueConfig(
    emails_file_stem=FAILED_ADD_PHONE_EMAILS_FILE_STEM,
    emails_file_suffix=FAILED_ADD_PHONE_EMAILS_FILE_SUFFIX,
    retry_counts_file_stem=FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_FILE_STEM,
    retry_counts_file_suffix=FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_FILE_SUFFIX,
    empty_profile_error_message=EMPTY_FAILED_ADD_PHONE_PROFILE_NAME_ERROR_MESSAGE,
    empty_email_error_message=EMPTY_FAILED_ADD_PHONE_EMAIL_ERROR_MESSAGE,
    invalid_retry_counts_message=INVALID_FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_MESSAGE,
    missing_email_message=MISSING_FAILED_ADD_PHONE_EMAIL_MESSAGE,
)
SIGNUP_QUEUE_CONFIG = RetryEmailQueueConfig(
    emails_file_stem=FAILED_SIGNUP_EMAILS_FILE_STEM,
    emails_file_suffix=FAILED_SIGNUP_EMAILS_FILE_SUFFIX,
    retry_counts_file_stem=FAILED_SIGNUP_EMAIL_RETRY_COUNTS_FILE_STEM,
    retry_counts_file_suffix=FAILED_SIGNUP_EMAIL_RETRY_COUNTS_FILE_SUFFIX,
    empty_profile_error_message=EMPTY_FAILED_SIGNUP_PROFILE_NAME_ERROR_MESSAGE,
    empty_email_error_message=EMPTY_FAILED_SIGNUP_EMAIL_ERROR_MESSAGE,
    invalid_retry_counts_message=INVALID_FAILED_SIGNUP_EMAIL_RETRY_COUNTS_MESSAGE,
    missing_email_message=MISSING_FAILED_SIGNUP_EMAIL_MESSAGE,
)


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
    empty_profile_error_message: str,
) -> Path:
    normalized_profile_name = profile_name.strip()
    if not normalized_profile_name:
        raise RuntimeError(empty_profile_error_message)
    file_name = f"{file_stem}.{normalized_profile_name}{file_suffix}"
    return base_dir / file_name


def _build_retry_emails_file_path(
    base_dir: Path,
    profile_name: str,
    *,
    config: RetryEmailQueueConfig,
) -> Path:
    return _build_profile_scoped_file_path(
        base_dir,
        profile_name,
        file_stem=config.emails_file_stem,
        file_suffix=config.emails_file_suffix,
        empty_profile_error_message=config.empty_profile_error_message,
    )


def _build_retry_counts_file_path(
    base_dir: Path,
    profile_name: str,
    *,
    config: RetryEmailQueueConfig,
) -> Path:
    return _build_profile_scoped_file_path(
        base_dir,
        profile_name,
        file_stem=config.retry_counts_file_stem,
        file_suffix=config.retry_counts_file_suffix,
        empty_profile_error_message=config.empty_profile_error_message,
    )


def build_failed_add_phone_emails_file_path(
    base_dir: Path,
    profile_name: str,
) -> Path:
    return _build_retry_emails_file_path(
        base_dir,
        profile_name,
        config=ADD_PHONE_QUEUE_CONFIG,
    )


def build_failed_add_phone_email_retry_counts_file_path(
    base_dir: Path,
    profile_name: str,
) -> Path:
    return _build_retry_counts_file_path(
        base_dir,
        profile_name,
        config=ADD_PHONE_QUEUE_CONFIG,
    )


def build_failed_signup_emails_file_path(
    base_dir: Path,
    profile_name: str,
) -> Path:
    return _build_retry_emails_file_path(
        base_dir,
        profile_name,
        config=SIGNUP_QUEUE_CONFIG,
    )


def build_failed_signup_email_retry_counts_file_path(
    base_dir: Path,
    profile_name: str,
) -> Path:
    return _build_retry_counts_file_path(
        base_dir,
        profile_name,
        config=SIGNUP_QUEUE_CONFIG,
    )


def _parse_retry_profile_name(
    file_path: Path,
    *,
    file_prefix: str,
    file_suffix: str,
) -> str | None:
    file_name = file_path.name.strip()
    if not file_name.startswith(file_prefix):
        return None
    if not file_name.endswith(file_suffix):
        return None
    raw_profile_name = file_name[
        len(file_prefix) : -len(file_suffix)
    ]
    if not raw_profile_name:
        return None
    try:
        return parse_profile_name(raw_profile_name)
    except argparse.ArgumentTypeError:
        return None


def parse_failed_add_phone_profile_name(file_path: Path) -> str | None:
    return _parse_retry_profile_name(
        file_path,
        file_prefix=FAILED_ADD_PHONE_EMAILS_FILE_PREFIX,
        file_suffix=FAILED_ADD_PHONE_EMAILS_FILE_SUFFIX,
    )


def parse_failed_signup_profile_name(file_path: Path) -> str | None:
    return _parse_retry_profile_name(
        file_path,
        file_prefix=FAILED_SIGNUP_EMAILS_FILE_PREFIX,
        file_suffix=FAILED_SIGNUP_EMAILS_FILE_SUFFIX,
    )


def _load_retry_emails(file_path: Path) -> tuple[str, ...]:
    if not file_path.is_file():
        return ()

    seen_email_keys: set[str] = set()
    emails: list[str] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        email = line.strip()
        email_key = _build_email_key(email)
        if not email or email_key in seen_email_keys:
            continue
        seen_email_keys.add(email_key)
        emails.append(email)
    return tuple(emails)


def _load_retry_emails_for_config(
    base_dir: Path,
    profile_name: str,
    *,
    config: RetryEmailQueueConfig,
) -> tuple[str, ...]:
    return _load_retry_emails(
        _build_retry_emails_file_path(base_dir, profile_name, config=config)
    )


def load_failed_add_phone_emails(
    base_dir: Path,
    profile_name: str,
) -> tuple[str, ...]:
    return _load_retry_emails_for_config(
        base_dir,
        profile_name,
        config=ADD_PHONE_QUEUE_CONFIG,
    )


def load_failed_signup_emails(
    base_dir: Path,
    profile_name: str,
) -> tuple[str, ...]:
    return _load_retry_emails_for_config(
        base_dir,
        profile_name,
        config=SIGNUP_QUEUE_CONFIG,
    )


def _build_email_key(email: str) -> str:
    return email.casefold()


def _remove_email_from_pending_list(
    pending_emails: list[str],
    email: str,
    *,
    missing_email_message: str,
) -> list[str]:
    email_key = _build_email_key(email)
    for index, pending_email in enumerate(pending_emails):
        if _build_email_key(pending_email) == email_key:
            return [
                *pending_emails[:index],
                *pending_emails[index + 1 :],
            ]
    raise RuntimeError(f"{missing_email_message} {email}")


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


def _load_retry_counts(
    file_path: Path,
    *,
    invalid_retry_counts_message: str,
) -> dict[str, int]:
    if not file_path.is_file():
        return {}
    try:
        raw_payload = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(invalid_retry_counts_message) from exc
    if not isinstance(raw_payload, dict):
        raise RuntimeError(invalid_retry_counts_message)
    raw_counts = raw_payload.get(FAILED_EMAIL_RETRY_COUNTS_ROOT_KEY, {})
    if not isinstance(raw_counts, dict):
        raise RuntimeError(invalid_retry_counts_message)

    retry_counts: dict[str, int] = {}
    for raw_email_key, raw_retry_count in raw_counts.items():
        if not isinstance(raw_email_key, str) or not raw_email_key.strip():
            raise RuntimeError(invalid_retry_counts_message)
        if not isinstance(raw_retry_count, int) or raw_retry_count < 0:
            raise RuntimeError(invalid_retry_counts_message)
        retry_counts[raw_email_key.strip()] = raw_retry_count
    return retry_counts


def _load_retry_counts_for_config(
    base_dir: Path,
    profile_name: str,
    *,
    config: RetryEmailQueueConfig,
) -> dict[str, int]:
    return _load_retry_counts(
        _build_retry_counts_file_path(base_dir, profile_name, config=config),
        invalid_retry_counts_message=config.invalid_retry_counts_message,
    )


def _save_retry_counts(file_path: Path, retry_counts: dict[str, int]) -> None:
    if not retry_counts:
        file_path.unlink(missing_ok=True)
        return

    payload = {
        FAILED_EMAIL_RETRY_COUNTS_ROOT_KEY: {
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


def _clear_retry_count(
    base_dir: Path,
    profile_name: str,
    email: str,
    *,
    config: RetryEmailQueueConfig,
) -> None:
    normalized_email = email.strip()
    if not normalized_email:
        raise RuntimeError(config.empty_email_error_message)

    retry_counts = _load_retry_counts_for_config(base_dir, profile_name, config=config)
    email_key = _build_email_key(normalized_email)
    if email_key not in retry_counts:
        return
    retry_counts.pop(email_key)
    _save_retry_counts(
        _build_retry_counts_file_path(base_dir, profile_name, config=config),
        retry_counts,
    )


def clear_failed_add_phone_email_retry_count(
    base_dir: Path,
    profile_name: str,
    email: str,
) -> None:
    _clear_retry_count(
        base_dir,
        profile_name,
        email,
        config=ADD_PHONE_QUEUE_CONFIG,
    )


def clear_failed_signup_email_retry_count(
    base_dir: Path,
    profile_name: str,
    email: str,
) -> None:
    _clear_retry_count(
        base_dir,
        profile_name,
        email,
        config=SIGNUP_QUEUE_CONFIG,
    )


def _remove_retry_email(
    base_dir: Path,
    profile_name: str,
    email: str,
    *,
    config: RetryEmailQueueConfig,
) -> tuple[str, ...]:
    normalized_email = email.strip()
    if not normalized_email:
        raise RuntimeError(config.empty_email_error_message)

    pending_emails = list(
        _load_retry_emails_for_config(base_dir, profile_name, config=config)
    )
    next_pending_emails = _remove_email_from_pending_list(
        pending_emails,
        normalized_email,
        missing_email_message=config.missing_email_message,
    )
    save_email_lines(
        _build_retry_emails_file_path(base_dir, profile_name, config=config),
        next_pending_emails,
    )
    retry_counts = _filter_retry_counts(
        _load_retry_counts_for_config(base_dir, profile_name, config=config),
        next_pending_emails,
    )
    _save_retry_counts(
        _build_retry_counts_file_path(base_dir, profile_name, config=config),
        retry_counts,
    )
    return tuple(next_pending_emails)


def remove_failed_add_phone_email(
    base_dir: Path,
    profile_name: str,
    email: str,
) -> tuple[str, ...]:
    return _remove_retry_email(
        base_dir,
        profile_name,
        email,
        config=ADD_PHONE_QUEUE_CONFIG,
    )


def remove_failed_signup_email(
    base_dir: Path,
    profile_name: str,
    email: str,
) -> tuple[str, ...]:
    return _remove_retry_email(
        base_dir,
        profile_name,
        email,
        config=SIGNUP_QUEUE_CONFIG,
    )


def _record_retry_email_retry(
    base_dir: Path,
    profile_name: str,
    email: str,
    *,
    max_retry_count: int,
    config: RetryEmailQueueConfig,
) -> FailedEmailRetryResult:
    normalized_email = email.strip()
    if not normalized_email:
        raise RuntimeError(config.empty_email_error_message)
    if max_retry_count < 1:
        raise RuntimeError("更新失败邮箱重试次数失败：最大重试次数必须大于 0。")

    pending_emails = list(
        _load_retry_emails_for_config(base_dir, profile_name, config=config)
    )
    pending_email_keys = {_build_email_key(item) for item in pending_emails}
    email_key = _build_email_key(normalized_email)
    if email_key not in pending_email_keys:
        raise RuntimeError(f"{config.missing_email_message} {normalized_email}")

    retry_counts = _filter_retry_counts(
        _load_retry_counts_for_config(base_dir, profile_name, config=config),
        pending_emails,
    )
    next_retry_count = retry_counts.get(email_key, 0) + 1
    if next_retry_count >= max_retry_count:
        next_pending_emails = _remove_retry_email(
            base_dir,
            profile_name,
            normalized_email,
            config=config,
        )
        return FailedEmailRetryResult(
            retry_count=next_retry_count,
            did_remove_email=True,
            remaining_email_count=len(next_pending_emails),
        )

    retry_counts[email_key] = next_retry_count
    _save_retry_counts(
        _build_retry_counts_file_path(base_dir, profile_name, config=config),
        retry_counts,
    )
    return FailedEmailRetryResult(
        retry_count=next_retry_count,
        did_remove_email=False,
        remaining_email_count=len(pending_emails),
    )


def record_failed_add_phone_email_retry(
    base_dir: Path,
    profile_name: str,
    email: str,
    *,
    max_retry_count: int,
) -> FailedEmailRetryResult:
    return _record_retry_email_retry(
        base_dir,
        profile_name,
        email,
        max_retry_count=max_retry_count,
        config=ADD_PHONE_QUEUE_CONFIG,
    )


def record_failed_signup_email_retry(
    base_dir: Path,
    profile_name: str,
    email: str,
    *,
    max_retry_count: int,
) -> FailedEmailRetryResult:
    return _record_retry_email_retry(
        base_dir,
        profile_name,
        email,
        max_retry_count=max_retry_count,
        config=SIGNUP_QUEUE_CONFIG,
    )


def _record_retry_email(
    base_dir: Path,
    profile_name: str,
    email: str,
    *,
    config: RetryEmailQueueConfig,
) -> bool:
    normalized_email = email.strip()
    if not normalized_email:
        raise RuntimeError(config.empty_email_error_message)

    file_path = _build_retry_emails_file_path(base_dir, profile_name, config=config)
    existing_emails = list(
        _load_retry_emails_for_config(base_dir, profile_name, config=config)
    )
    normalized_email_key = _build_email_key(normalized_email)
    existing_email_keys = {_build_email_key(item) for item in existing_emails}
    if normalized_email_key in existing_email_keys:
        return False

    existing_emails.append(normalized_email)
    save_email_lines(file_path, existing_emails)
    _clear_retry_count(base_dir, profile_name, normalized_email, config=config)
    return True


def record_failed_add_phone_email(
    base_dir: Path,
    profile_name: str,
    email: str,
) -> bool:
    return _record_retry_email(
        base_dir,
        profile_name,
        email,
        config=ADD_PHONE_QUEUE_CONFIG,
    )


def record_failed_signup_email(
    base_dir: Path,
    profile_name: str,
    email: str,
) -> bool:
    return _record_retry_email(
        base_dir,
        profile_name,
        email,
        config=SIGNUP_QUEUE_CONFIG,
    )


FailedAddPhoneEmailRetryResult = FailedEmailRetryResult
