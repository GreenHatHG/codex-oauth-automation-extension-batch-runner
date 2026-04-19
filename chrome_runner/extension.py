"""Extension launch, monitoring, and result classification."""

from __future__ import annotations

import json
import time
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
    wait_for_target_websocket_url,
)


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
    stagnant_seconds: float = 0.0
    recent_logs: tuple[str, ...] = ()


def load_json_file(file_path: Path) -> dict[str, object]:
    return json.loads(file_path.read_text(encoding="utf-8"))


def read_extension_settings(profile_dir: Path, extension_id: str) -> dict[str, object]:
    secure_preferences_path = profile_dir / "Default" / "Secure Preferences"
    secure_preferences = load_json_file(secure_preferences_path)
    return (
        secure_preferences.get("extensions", {})
        .get("settings", {})
        .get(extension_id, {})
    )


def read_manifest_from_directory(extension_dir: Path) -> dict[str, object]:
    manifest_path = extension_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"找不到扩展 manifest 文件: {manifest_path}")
    return load_json_file(manifest_path)


def find_unpacked_extension_dir(profile_dir: Path, extension_id: str) -> Path | None:
    extension_settings = read_extension_settings(profile_dir, extension_id)
    extension_path = str(extension_settings.get("path", "")).strip()
    if not extension_path:
        return None

    source_path = Path(extension_path).expanduser()
    if not source_path.is_dir():
        raise FileNotFoundError(f"找不到扩展源码目录: {source_path}")
    read_manifest_from_directory(source_path)
    return source_path


def find_installed_extension_dir(profile_dir: Path, extension_id: str) -> Path | None:
    extension_versions_dir = profile_dir / "Default" / "Extensions" / extension_id
    if not extension_versions_dir.is_dir():
        return None

    version_dirs = sorted(
        (path for path in extension_versions_dir.iterdir() if path.is_dir()),
        key=lambda path: path.name,
        reverse=True,
    )
    for version_dir in version_dirs:
        if (version_dir / "manifest.json").is_file():
            return version_dir
    return None


def read_extension_source_path(profile_dir: Path, extension_id: str) -> Path:
    unpacked_extension_dir = find_unpacked_extension_dir(profile_dir, extension_id)
    if unpacked_extension_dir is not None:
        return unpacked_extension_dir

    installed_extension_dir = find_installed_extension_dir(profile_dir, extension_id)
    if installed_extension_dir is not None:
        return installed_extension_dir

    raise FileNotFoundError(
        "在基准配置中找不到目标扩展安装目录。"
        f"扩展 ID: {extension_id}"
    )


def build_extension_page_url(profile_dir: Path, extension_id: str) -> str:
    extension_source_path = read_extension_source_path(profile_dir, extension_id)
    manifest = read_manifest_from_directory(extension_source_path)
    side_panel = manifest.get("side_panel", {})
    side_panel_path = side_panel.get("default_path") if isinstance(side_panel, dict) else ""
    if not side_panel_path:
        raise RuntimeError("目标扩展没有配置 side_panel.default_path。")
    return f"chrome-extension://{extension_id}/{side_panel_path}"


def wait_for_extension_ready(devtools_client: DevToolsClient) -> None:
    deadline = time.time() + PAGE_READY_TIMEOUT_SECONDS
    readiness_check = (
        "document.readyState === 'complete' "
        f"&& Boolean(document.querySelector({json.dumps(AUTO_RUN_BUTTON_SELECTOR)}))"
    )

    while time.time() < deadline:
        if evaluate_javascript(devtools_client, readiness_check):
            return
        time.sleep(DEVTOOLS_POLL_INTERVAL_SECONDS)

    raise TimeoutError("扩展页面未在预期时间内完成加载。")


def click_extension_auto_run(devtools_client: DevToolsClient) -> None:
    deadline = time.time() + BUTTON_CLICK_TIMEOUT_SECONDS
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
            stagnant_seconds=stagnant_seconds,
            recent_logs=snapshot.recent_logs,
        )
    return None


def monitor_extension_run(devtools_client: DevToolsClient) -> ExtensionRunResult:
    snapshot = capture_extension_snapshot(devtools_client)
    last_snapshot = snapshot
    last_change_at = time.time()
    last_reported_status = ""

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

        time.sleep(RUN_MONITOR_POLL_INTERVAL_SECONDS)
        snapshot = capture_extension_snapshot(devtools_client)
        if snapshot.fingerprint != last_snapshot.fingerprint:
            last_snapshot = snapshot
            last_change_at = time.time()
            if snapshot.status_text and snapshot.status_text != last_reported_status:
                print(f"扩展状态：{snapshot.status_text}")
                last_reported_status = snapshot.status_text


def create_minimized_extension_target(
    browser_devtools_client: DevToolsClient,
    devtools_port: int,
    extension_url: str,
) -> str:
    response = browser_devtools_client.call(
        "Target.createTarget",
        {
            "url": extension_url,
            "newWindow": True,
            "windowState": "minimized",
        },
    )
    if response.get("error"):
        raise RuntimeError(f"创建扩展目标页失败: {response['error']}")

    target_id = str(response.get("result", {}).get("targetId", "")).strip()
    if not target_id:
        raise RuntimeError("创建扩展目标页失败：缺少 targetId。")
    return wait_for_target_websocket_url(devtools_port, target_id)


def run_extension(
    profile_dir: Path,
    devtools_port: int,
    extension_id: str,
) -> ExtensionRunResult:
    extension_url = build_extension_page_url(profile_dir, extension_id)
    wait_for_devtools_ready(devtools_port, DEVTOOLS_READY_TIMEOUT_SECONDS)
    browser_websocket_url = fetch_browser_websocket_url(devtools_port)
    browser_devtools_client = DevToolsClient(
        browser_websocket_url,
        timeout_seconds=PAGE_READY_TIMEOUT_SECONDS,
    )
    try:
        websocket_url = create_minimized_extension_target(
            browser_devtools_client,
            devtools_port,
            extension_url,
        )
        devtools_client = DevToolsClient(
            websocket_url,
            timeout_seconds=PAGE_READY_TIMEOUT_SECONDS,
        )
    except Exception:
        browser_devtools_client.close()
        raise

    try:
        devtools_client.call("Page.enable")
        devtools_client.call("Runtime.enable")
        wait_for_extension_ready(devtools_client)
        click_extension_auto_run(devtools_client)
        return monitor_extension_run(devtools_client)
    finally:
        devtools_client.close()
        browser_devtools_client.close()
