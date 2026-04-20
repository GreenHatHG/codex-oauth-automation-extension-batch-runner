"""Extension launch, monitoring, and result classification."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .constants import (
    AUTO_RUN_BUTTON_SELECTOR,
    AUTO_RUN_NOW_BUTTON_SELECTOR,
    AUTO_START_MODAL_SELECTOR,
    AUTO_START_RESTART_BUTTON_SELECTOR,
    BUTTON_CLICK_TIMEOUT_SECONDS,
    DEVTOOLS_POLL_INTERVAL_SECONDS,
    FAILURE_STATUS_TEXTS,
    LOG_LINE_SELECTOR,
    PAGE_READY_TIMEOUT_SECONDS,
    START_PAGE_REUSE_TIMEOUT_SECONDS,
    RUN_MONITOR_POLL_INTERVAL_SECONDS,
    RUN_MONITOR_STAGNATION_TIMEOUT_SECONDS,
    EXTENSION_RESULT_LOG_LINE_LIMIT,
    RUNNING_STATUS_TEXTS,
    SCHEDULED_STATUS_TEXTS,
    STATUS_BAR_SELECTOR,
    STATUS_DISPLAY_SELECTOR,
    STEP_STATUS_SELECTOR,
    SUCCESS_STATUS_TEXTS,
    EXTENSION_START_SCRIPT_TEMPLATE,
    EXTENSION_STATUS_SNAPSHOT_SCRIPT_TEMPLATE,
    DEVTOOLS_READY_TIMEOUT_SECONDS,
)
from .devtools import (
    DevToolsClient,
    evaluate_javascript,
    fetch_browser_websocket_url,
    wait_for_devtools_ready,
    wait_for_page_websocket_url,
    wait_for_target_websocket_url,
)
from .extension_source import build_extension_page_url


@dataclass(frozen=True)
class ExtensionSnapshot:
    """Visible extension state collected from the sidepanel page."""

    status_text: str
    status_bar_class: str
    auto_run_button_text: str
    log_count: int
    recent_logs: tuple[str, ...]
    step_signature: tuple[str, ...]

    @property
    def fingerprint(self) -> tuple[str, str, str, int, tuple[str, ...], tuple[str, ...]]:
        return (
            self.status_text,
            self.status_bar_class,
            self.auto_run_button_text,
            self.log_count,
            self.recent_logs,
            self.step_signature,
        )


@dataclass(frozen=True)
class ExtensionRunResult:
    """Final extension execution result."""

    outcome: str
    status_text: str
    timeout_seconds: float = 0.0
    recent_logs: tuple[str, ...] = ()


SnapshotObserver = Callable[[ExtensionSnapshot, float | None], None]


class AttemptTimeoutError(TimeoutError):
    """Raised when a single automatic run exceeds the configured attempt limit."""


def wait_for_extension_ready(
    devtools_client: DevToolsClient,
    timeout_seconds: float = PAGE_READY_TIMEOUT_SECONDS,
) -> None:
    deadline = time.time() + timeout_seconds
    readiness_check = (
        "document.readyState === 'complete' "
        f"&& Boolean(document.querySelector({json.dumps(AUTO_RUN_BUTTON_SELECTOR)}))"
    )

    while time.time() < deadline:
        if evaluate_javascript(devtools_client, readiness_check):
            return
        time.sleep(DEVTOOLS_POLL_INTERVAL_SECONDS)

    raise TimeoutError("扩展页面未在预期时间内完成加载。")


def click_extension_auto_run(
    devtools_client: DevToolsClient,
    timeout_seconds: float = BUTTON_CLICK_TIMEOUT_SECONDS,
) -> None:
    deadline = time.time() + timeout_seconds
    script = EXTENSION_START_SCRIPT_TEMPLATE % {
        "auto_run_button": json.dumps(AUTO_RUN_BUTTON_SELECTOR),
        "run_now_button": json.dumps(AUTO_RUN_NOW_BUTTON_SELECTOR),
        "auto_start_modal": json.dumps(AUTO_START_MODAL_SELECTOR),
        "restart_button": json.dumps(AUTO_START_RESTART_BUTTON_SELECTOR),
        "running_labels": json.dumps(RUNNING_STATUS_TEXTS, ensure_ascii=False),
        "scheduled_labels": json.dumps(SCHEDULED_STATUS_TEXTS, ensure_ascii=False),
    }

    while time.time() < deadline:
        result = str(evaluate_javascript(devtools_client, script) or "")
        if result in {"clicked-auto-run", "clicked-restart", "clicked-run-now"}:
            time.sleep(DEVTOOLS_POLL_INTERVAL_SECONDS)
            continue
        if result in {"started", "scheduled"}:
            return
        if result == "missing-auto-run-button":
            time.sleep(DEVTOOLS_POLL_INTERVAL_SECONDS)
            continue
        raise RuntimeError(f"扩展自动运行状态异常: {result}")

    raise TimeoutError("未能确认扩展已进入自动运行状态。")


def capture_extension_snapshot(devtools_client: DevToolsClient) -> ExtensionSnapshot:
    script = EXTENSION_STATUS_SNAPSHOT_SCRIPT_TEMPLATE % {
        "status_display_selector": json.dumps(STATUS_DISPLAY_SELECTOR),
        "status_bar_selector": json.dumps(STATUS_BAR_SELECTOR),
        "auto_run_button_selector": json.dumps(AUTO_RUN_BUTTON_SELECTOR),
        "log_line_selector": json.dumps(LOG_LINE_SELECTOR),
        "recent_log_limit": EXTENSION_RESULT_LOG_LINE_LIMIT,
        "step_status_selector": json.dumps(STEP_STATUS_SELECTOR),
    }
    payload = evaluate_javascript(devtools_client, script)
    if not isinstance(payload, dict):
        raise RuntimeError("扩展状态采样返回了非预期数据。")

    raw_recent_logs = payload.get("recentLogs", [])
    raw_steps = payload.get("steps", [])
    recent_logs: tuple[str, ...] = ()
    if isinstance(raw_recent_logs, list):
        recent_logs = tuple(
            str(item).strip()
            for item in raw_recent_logs
            if str(item).strip()
        )

    step_signature: tuple[str, ...] = ()
    if isinstance(raw_steps, list):
        step_signature = tuple(
            f"{item.get('step', '')}|{item.get('rowClass', '')}|{item.get('text', '')}"
            for item in raw_steps
            if isinstance(item, dict)
        )

    return ExtensionSnapshot(
        status_text=str(payload.get("statusText", "")).strip(),
        status_bar_class=str(payload.get("statusBarClass", "")).strip(),
        auto_run_button_text=str(payload.get("autoRunButtonText", "")).strip(),
        log_count=max(0, int(payload.get("logCount", 0) or 0)),
        recent_logs=recent_logs,
        step_signature=step_signature,
    )


def classify_extension_snapshot(
    snapshot: ExtensionSnapshot,
    *,
    stagnant_seconds: float,
) -> ExtensionRunResult | None:
    if any(text in snapshot.status_text for text in SUCCESS_STATUS_TEXTS):
        return ExtensionRunResult("success", snapshot.status_text)
    if any(text in snapshot.status_text for text in FAILURE_STATUS_TEXTS):
        return ExtensionRunResult(
            "failure",
            snapshot.status_text,
            recent_logs=snapshot.recent_logs,
        )
    if stagnant_seconds >= RUN_MONITOR_STAGNATION_TIMEOUT_SECONDS:
        status_text = snapshot.status_text or "状态长期无变化"
        return ExtensionRunResult(
            "timeout",
            status_text,
            timeout_seconds=stagnant_seconds,
            recent_logs=snapshot.recent_logs,
        )
    return None


def has_attempt_timed_out(
    attempt_started_at: float,
    max_attempt_seconds: int | None,
) -> bool:
    if max_attempt_seconds is None:
        return False
    return (time.monotonic() - attempt_started_at) >= max_attempt_seconds


def build_attempt_timeout_result(
    status_text: str,
    *,
    timeout_seconds: int,
    recent_logs: tuple[str, ...] = (),
) -> ExtensionRunResult:
    return ExtensionRunResult(
        "attempt_timeout",
        status_text or "单轮运行时间达到上限",
        timeout_seconds=timeout_seconds,
        recent_logs=recent_logs,
    )


def resolve_operation_timeout_seconds(
    attempt_started_at: float,
    max_attempt_seconds: int | None,
    default_timeout_seconds: float,
) -> float:
    if max_attempt_seconds is None:
        return default_timeout_seconds

    remaining_seconds = max_attempt_seconds - (time.monotonic() - attempt_started_at)
    if remaining_seconds <= 0:
        raise AttemptTimeoutError("单轮运行时间达到上限")
    return min(default_timeout_seconds, remaining_seconds)


def compute_remaining_attempt_seconds(
    attempt_started_at: float,
    max_attempt_seconds: int | None,
) -> float | None:
    if max_attempt_seconds is None:
        return None
    return max(max_attempt_seconds - (time.monotonic() - attempt_started_at), 0.0)


def monitor_extension_run(
    devtools_client: DevToolsClient,
    *,
    attempt_started_at: float,
    max_attempt_seconds: int | None = None,
    snapshot_observer: SnapshotObserver | None = None,
) -> ExtensionRunResult:
    snapshot = capture_extension_snapshot(devtools_client)
    last_snapshot = snapshot
    last_change_at = time.time()
    last_reported_status = ""
    if snapshot_observer is not None:
        snapshot_observer(
            snapshot,
            compute_remaining_attempt_seconds(
                attempt_started_at,
                max_attempt_seconds,
            ),
        )

    if snapshot.status_text:
        print(f"扩展状态：{snapshot.status_text}")
        last_reported_status = snapshot.status_text

    while True:
        now = time.time()
        stagnant_seconds = now - last_change_at
        outcome = classify_extension_snapshot(
            last_snapshot,
            stagnant_seconds=stagnant_seconds,
        )
        if outcome is not None:
            return outcome
        if has_attempt_timed_out(attempt_started_at, max_attempt_seconds):
            return build_attempt_timeout_result(
                last_snapshot.status_text or "状态未知",
                timeout_seconds=max_attempt_seconds or 0,
                recent_logs=last_snapshot.recent_logs,
            )

        sleep_seconds = RUN_MONITOR_POLL_INTERVAL_SECONDS
        if max_attempt_seconds is not None:
            remaining_seconds = max_attempt_seconds - (
                time.monotonic() - attempt_started_at
            )
            if remaining_seconds <= 0:
                return build_attempt_timeout_result(
                    last_snapshot.status_text or "状态未知",
                    timeout_seconds=max_attempt_seconds,
                    recent_logs=last_snapshot.recent_logs,
                )
            sleep_seconds = min(sleep_seconds, remaining_seconds)
        time.sleep(sleep_seconds)
        snapshot = capture_extension_snapshot(devtools_client)
        if snapshot.fingerprint != last_snapshot.fingerprint:
            last_snapshot = snapshot
            last_change_at = time.time()
            if snapshot_observer is not None:
                snapshot_observer(
                    snapshot,
                    compute_remaining_attempt_seconds(
                        attempt_started_at,
                        max_attempt_seconds,
                    ),
                )
            if snapshot.status_text and snapshot.status_text != last_reported_status:
                print(f"扩展状态：{snapshot.status_text}")
                last_reported_status = snapshot.status_text


def create_extension_target(
    browser_devtools_client: DevToolsClient,
    devtools_port: int,
    extension_url: str,
    *,
    auto_minimize: bool = True,
    new_window: bool = True,
    timeout_seconds: float = DEVTOOLS_READY_TIMEOUT_SECONDS,
) -> str:
    target_params: dict[str, object] = {"url": extension_url}
    if new_window:
        target_params["newWindow"] = True
    if auto_minimize and new_window:
        target_params["windowState"] = "minimized"
    response = browser_devtools_client.call(
        "Target.createTarget",
        target_params,
    )
    if response.get("error"):
        raise RuntimeError(f"创建扩展目标页失败: {response['error']}")

    target_id = str(response.get("result", {}).get("targetId", "")).strip()
    if not target_id:
        raise RuntimeError("创建扩展目标页失败：缺少 targetId。")
    return wait_for_target_websocket_url(
        devtools_port,
        target_id,
        timeout_seconds=timeout_seconds,
    )


def find_reusable_start_page_websocket_url(
    devtools_port: int,
    timeout_seconds: float = START_PAGE_REUSE_TIMEOUT_SECONDS,
) -> str | None:
    try:
        return wait_for_page_websocket_url(
            devtools_port,
            include_url_substring="about:blank",
            timeout_seconds=timeout_seconds,
        )
    except TimeoutError:
        return None


def navigate_to_extension_page(
    devtools_client: DevToolsClient,
    extension_url: str,
    timeout_seconds: float = PAGE_READY_TIMEOUT_SECONDS,
) -> None:
    response = devtools_client.call("Page.navigate", {"url": extension_url})
    if response.get("error"):
        raise RuntimeError(f"跳转扩展目标页失败: {response['error']}")
    devtools_client.wait_for_event("Page.loadEventFired", timeout_seconds)


def run_extension(
    profile_dir: Path,
    devtools_port: int,
    extension_id: str,
    *,
    auto_minimize: bool = True,
    max_attempt_seconds: int | None = None,
    snapshot_observer: SnapshotObserver | None = None,
) -> ExtensionRunResult:
    attempt_started_at = time.monotonic()
    extension_url = build_extension_page_url(profile_dir, extension_id)
    try:
        wait_for_devtools_ready(
            devtools_port,
            resolve_operation_timeout_seconds(
                attempt_started_at,
                max_attempt_seconds,
                DEVTOOLS_READY_TIMEOUT_SECONDS,
            ),
        )
        browser_websocket_url = fetch_browser_websocket_url(devtools_port)
        browser_devtools_client = DevToolsClient(
            browser_websocket_url,
            timeout_seconds=resolve_operation_timeout_seconds(
                attempt_started_at,
                max_attempt_seconds,
                PAGE_READY_TIMEOUT_SECONDS,
            ),
        )
        try:
            target_timeout_seconds = resolve_operation_timeout_seconds(
                attempt_started_at,
                max_attempt_seconds,
                DEVTOOLS_READY_TIMEOUT_SECONDS,
            )
            should_navigate_existing_page = False
            websocket_url = ""
            if not auto_minimize:
                websocket_url = (
                    find_reusable_start_page_websocket_url(
                        devtools_port,
                        timeout_seconds=min(
                            target_timeout_seconds,
                            START_PAGE_REUSE_TIMEOUT_SECONDS,
                        ),
                    )
                    or ""
                )
                should_navigate_existing_page = bool(websocket_url)
            if not websocket_url:
                websocket_url = create_extension_target(
                    browser_devtools_client,
                    devtools_port,
                    extension_url,
                    auto_minimize=auto_minimize,
                    new_window=auto_minimize,
                    timeout_seconds=target_timeout_seconds,
                )
            devtools_client = DevToolsClient(
                websocket_url,
                timeout_seconds=resolve_operation_timeout_seconds(
                    attempt_started_at,
                    max_attempt_seconds,
                    PAGE_READY_TIMEOUT_SECONDS,
                ),
            )
        except Exception:
            browser_devtools_client.close()
            raise

        try:
            devtools_client.call("Page.enable")
            devtools_client.call("Runtime.enable")
            if should_navigate_existing_page:
                navigate_to_extension_page(
                    devtools_client,
                    extension_url,
                    timeout_seconds=resolve_operation_timeout_seconds(
                        attempt_started_at,
                        max_attempt_seconds,
                        PAGE_READY_TIMEOUT_SECONDS,
                    ),
                )
            wait_for_extension_ready(
                devtools_client,
                timeout_seconds=resolve_operation_timeout_seconds(
                    attempt_started_at,
                    max_attempt_seconds,
                    PAGE_READY_TIMEOUT_SECONDS,
                ),
            )
            click_extension_auto_run(
                devtools_client,
                timeout_seconds=resolve_operation_timeout_seconds(
                    attempt_started_at,
                    max_attempt_seconds,
                    BUTTON_CLICK_TIMEOUT_SECONDS,
                ),
            )
            return monitor_extension_run(
                devtools_client,
                attempt_started_at=attempt_started_at,
                max_attempt_seconds=max_attempt_seconds,
                snapshot_observer=snapshot_observer,
            )
        finally:
            devtools_client.close()
            browser_devtools_client.close()
    except AttemptTimeoutError as exc:
        return build_attempt_timeout_result(
            str(exc),
            timeout_seconds=max_attempt_seconds or 0,
        )
    except TimeoutError as exc:
        if has_attempt_timed_out(attempt_started_at, max_attempt_seconds):
            return build_attempt_timeout_result(
                str(exc),
                timeout_seconds=max_attempt_seconds or 0,
            )
        raise
