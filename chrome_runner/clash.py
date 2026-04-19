"""Clash pre-run actions."""

from __future__ import annotations

import json
import random
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Collection

from .constants import (
    CLASH_AI_SWITCH_ERROR_PREFIX,
    CLASH_BASE_URL,
    CLASH_DELAY_TEST_URL,
    CLASH_DELAY_TIMEOUT_MS,
    CLASH_GROUP_NAME,
    CLASH_REQUEST_RETRY_ATTEMPTS,
    CLASH_REQUEST_RETRY_DELAY_SECONDS,
    CLASH_REQUEST_TIMEOUT_SECONDS,
    CLASH_SKIP_NAME_WORDS,
    CLASH_SKIP_PROXY_TYPES,
)


def normalize_proxy_name(value: object) -> str:
    return str(value or "").strip()


def should_skip_proxy_name(proxy_name: str) -> bool:
    return any(skip_word in proxy_name for skip_word in CLASH_SKIP_NAME_WORDS)


def should_skip_proxy_type(proxy: object) -> bool:
    if not isinstance(proxy, dict):
        return True
    return str(proxy.get("type", "")) in CLASH_SKIP_PROXY_TYPES


def build_clash_delay_url(proxy_name: str) -> str:
    encoded_proxy_name = urllib.parse.quote(proxy_name, safe="")
    encoded_test_url = urllib.parse.quote(CLASH_DELAY_TEST_URL, safe="")
    return (
        f"{CLASH_BASE_URL}/proxies/{encoded_proxy_name}/delay"
        f"?url={encoded_test_url}&timeout={CLASH_DELAY_TIMEOUT_MS}"
    )


def build_clash_selector_url() -> str:
    return f"{CLASH_BASE_URL}/proxies/{urllib.parse.quote(CLASH_GROUP_NAME, safe='')}"


def should_retry_clash_error(exc: urllib.error.URLError) -> bool:
    reason = exc.reason
    if isinstance(reason, (socket.timeout, TimeoutError, ConnectionResetError)):
        return True
    if isinstance(reason, str):
        normalized_reason = reason.strip().lower()
        return normalized_reason in {
            "timed out",
            "timeout",
            "connection refused",
            "connection reset by peer",
        }
    return isinstance(reason, OSError)


def format_clash_error_reason(exc: urllib.error.URLError) -> str:
    reason = exc.reason
    if isinstance(reason, BaseException):
        return str(reason) or reason.__class__.__name__
    return str(reason)


def format_generic_error_reason(exc: BaseException) -> str:
    return str(exc) or exc.__class__.__name__


def build_retry_suffix(total_attempts: int) -> str:
    if total_attempts <= 1:
        return ""
    return f"，共尝试 {total_attempts} 次"


def request_json(
    url: str,
    *,
    error_message: str,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    timeout_seconds: float = CLASH_REQUEST_TIMEOUT_SECONDS,
    retry_attempts: int = CLASH_REQUEST_RETRY_ATTEMPTS,
) -> object:
    headers: dict[str, str] = {}
    data: bytes | None = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")

    total_attempts = max(1, retry_attempts)
    last_reason = ""

    for attempt in range(1, total_attempts + 1):
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body_text = response.read().decode("utf-8")
                return json.loads(body_text) if body_text else {}
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"{error_message}（HTTP {exc.code}）") from exc
        except urllib.error.URLError as exc:
            last_reason = format_clash_error_reason(exc)
            if attempt >= total_attempts or not should_retry_clash_error(exc):
                raise RuntimeError(
                    f"{error_message}（{last_reason}{build_retry_suffix(total_attempts)}）"
                ) from exc
            time.sleep(CLASH_REQUEST_RETRY_DELAY_SECONDS)
        except (socket.timeout, TimeoutError, ConnectionResetError) as exc:
            last_reason = format_generic_error_reason(exc)
            if attempt >= total_attempts:
                raise RuntimeError(
                    f"{error_message}（{last_reason}{build_retry_suffix(total_attempts)}）"
                ) from exc
            time.sleep(CLASH_REQUEST_RETRY_DELAY_SECONDS)

    raise RuntimeError(f"{error_message}（{last_reason or 'unknown error'}）")


def fetch_clash_proxy_snapshot() -> dict[str, object]:
    snapshot = request_json(
        f"{CLASH_BASE_URL}/proxies",
        error_message="读取 Clash 节点列表失败",
    )
    if not isinstance(snapshot, dict):
        raise RuntimeError("读取 Clash 节点列表失败（返回了非预期数据）。")
    return snapshot


def pick_clash_candidates(snapshot: dict[str, object]) -> list[str]:
    proxies = snapshot.get("proxies", {})
    if not isinstance(proxies, dict):
        raise RuntimeError(f"没有找到 Clash 分组：{CLASH_GROUP_NAME}")

    group = proxies.get(CLASH_GROUP_NAME)
    if not isinstance(group, dict) or not isinstance(group.get("all"), list):
        raise RuntimeError(f"没有找到 Clash 分组：{CLASH_GROUP_NAME}")

    candidates: list[str] = []
    seen_names: set[str] = set()
    for raw_name in group["all"]:
        proxy_name = normalize_proxy_name(raw_name)
        if not proxy_name or proxy_name in seen_names:
            continue
        if should_skip_proxy_name(proxy_name):
            continue
        proxy = proxies.get(proxy_name)
        if should_skip_proxy_type(proxy):
            continue
        seen_names.add(proxy_name)
        candidates.append(proxy_name)

    return candidates


def build_available_proxy_candidates(
    candidates: list[str],
    *,
    current_proxy_name: str,
    excluded_proxy_names: Collection[str] = (),
) -> list[str]:
    excluded_names = {
        normalize_proxy_name(proxy_name)
        for proxy_name in excluded_proxy_names
        if normalize_proxy_name(proxy_name)
    }
    return [
        proxy_name
        for proxy_name in candidates
        if proxy_name != current_proxy_name and proxy_name not in excluded_names
    ]


def probe_clash_proxy_delay(proxy_name: str) -> int | None:
    try:
        payload = request_json(
            build_clash_delay_url(proxy_name),
            error_message=f"测速失败：{proxy_name}",
            timeout_seconds=CLASH_REQUEST_TIMEOUT_SECONDS,
        )
    except RuntimeError:
        return None

    if not isinstance(payload, dict):
        return None
    delay = payload.get("delay")
    if isinstance(delay, (int, float)) and delay >= 0:
        return int(delay)
    return None


def switch_clash_proxy(proxy_name: str) -> None:
    request_json(
        build_clash_selector_url(),
        error_message=f"切换 Clash 节点失败：{proxy_name}",
        method="PUT",
        payload={"name": proxy_name},
    )


def run_pre_run_clash_ai_switch(
    *,
    excluded_proxy_names: Collection[str] = (),
) -> dict[str, object]:
    try:
        snapshot = fetch_clash_proxy_snapshot()
        proxies = snapshot.get("proxies", {})
        current_proxy_name = ""
        if isinstance(proxies, dict):
            group = proxies.get(CLASH_GROUP_NAME, {})
            if isinstance(group, dict):
                current_proxy_name = normalize_proxy_name(group.get("now"))

        candidates = pick_clash_candidates(snapshot)
        shuffled_candidates = list(candidates)
        random.shuffle(shuffled_candidates)
        available_candidates = build_available_proxy_candidates(
            shuffled_candidates,
            current_proxy_name=current_proxy_name,
            excluded_proxy_names=excluded_proxy_names,
        )

        if not available_candidates:
            if current_proxy_name:
                raise RuntimeError(f"{CLASH_GROUP_NAME} 分组没有可切换的新节点。")
            raise RuntimeError(f"{CLASH_GROUP_NAME} 分组里没有可用节点。")

        print(
            f"自动运行前置：开始选择 {CLASH_GROUP_NAME} 节点，当前节点："
            f"{current_proxy_name or '未知'}。"
        )
        if excluded_proxy_names:
            excluded_names_text = "、".join(sorted({
                normalize_proxy_name(proxy_name)
                for proxy_name in excluded_proxy_names
                if normalize_proxy_name(proxy_name)
            }))
            if excluded_names_text:
                print(f"自动运行前置：内存黑名单跳过节点：{excluded_names_text}。")

        for proxy_name in available_candidates:
            print(f"自动运行前置：测速 {proxy_name}")
            delay = probe_clash_proxy_delay(proxy_name)
            if delay is None:
                print(f"自动运行前置：{proxy_name} 不可用，继续尝试下一个节点。")
                continue

            switch_clash_proxy(proxy_name)
            print(
                f"自动运行前置：已由 {current_proxy_name or '未知'} 切到 "
                f"{proxy_name}，延迟 {delay} ms。"
            )
            return {
                "proxy_name": proxy_name,
                "delay": delay,
                "changed": proxy_name != current_proxy_name,
            }

        raise RuntimeError(f"{CLASH_GROUP_NAME} 分组没有可用节点。")
    except Exception as exc:
        raise RuntimeError(f"{CLASH_AI_SWITCH_ERROR_PREFIX}{exc}") from exc
