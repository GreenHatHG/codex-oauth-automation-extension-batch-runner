#!/usr/bin/env python3
"""Reload unpacked extensions for one or more local Chrome base profiles."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Iterable, Sequence
from pathlib import Path

from chrome_runner.chrome import (
    build_command,
    ensure_chrome_exists,
    find_free_port,
    launch_chrome,
    shutdown_chrome_process,
)
from chrome_runner.constants import DEVTOOLS_READY_TIMEOUT_SECONDS, PAGE_READY_TIMEOUT_SECONDS
from chrome_runner.devtools import (
    DevToolsClient,
    close_browser_via_devtools,
    evaluate_javascript,
    fetch_browser_websocket_url,
    wait_for_devtools_ready,
)
from chrome_runner.extension import (
    build_extension_page_url,
    create_extension_target,
    load_json_file,
    read_extension_settings,
)
from chrome_runner.profile import parse_profile_name, resolve_profile_dir

LAUNCH_FAILURE_PREFIX = "刷新失败"
PROFILE_MISSING_MESSAGE = "profile 不存在"
NO_UNPACKED_EXTENSION_MESSAGE = "profile 中找不到已安装的解压扩展"
AMBIGUOUS_UNPACKED_EXTENSION_MESSAGE = "profile 中存在多个解压扩展，请显式指定 --extension-id"
EXTENSION_NOT_FOUND_MESSAGE = "profile 中找不到目标扩展"
RELOAD_SETTLE_SECONDS = 2.0
RELOAD_SCRIPT = """
(() => {
  const runtime = globalThis.chrome?.runtime;
  if (!runtime?.reload) {
    return { status: 'missing-runtime-reload' };
  }
  const manifest = runtime.getManifest?.() || {};
  const version = String(manifest.version || '');
  window.setTimeout(() => runtime.reload(), 50);
  return {
    status: 'reload-scheduled',
    version,
  };
})()
""".strip()
READY_CHECK_SCRIPT = """
document.readyState === 'complete' && Boolean(globalThis.chrome?.runtime?.reload)
""".strip()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="批量刷新一个或多个基准 Chrome profile 中的解压扩展。"
    )
    parser.add_argument(
        "--profile",
        dest="profile_groups",
        action="append",
        nargs="+",
        required=True,
        type=parse_profile_name,
        help="指定一个或多个基准 profile 目录名，可重复传入。",
    )
    parser.add_argument(
        "--extension-id",
        default="",
        help=(
            "指定要刷新的扩展 ID。"
            "留空时，会按 profile 中唯一的解压扩展自动识别。"
        ),
    )
    return parser.parse_args(argv)


def flatten_profile_names(profile_groups: Iterable[Sequence[str]]) -> tuple[str, ...]:
    return tuple(profile_name for group in profile_groups for profile_name in group)


def load_extension_settings_map(profile_dir: Path) -> dict[str, object]:
    secure_preferences_path = profile_dir / "Default" / "Secure Preferences"
    secure_preferences = load_json_file(secure_preferences_path)
    settings = (
        secure_preferences.get("extensions", {}).get("settings", {})
        if isinstance(secure_preferences, dict)
        else {}
    )
    if not isinstance(settings, dict):
        raise RuntimeError(f"扩展配置格式异常: {secure_preferences_path}")
    return settings


def find_unpacked_extension_ids(profile_dir: Path) -> tuple[str, ...]:
    unpacked_extension_ids: list[str] = []
    for extension_id, settings in load_extension_settings_map(profile_dir).items():
        if not isinstance(extension_id, str) or not isinstance(settings, dict):
            continue
        if int(settings.get("location", 0) or 0) != 4:
            continue
        extension_path = str(settings.get("path", "")).strip()
        if not extension_path:
            continue
        manifest_path = Path(extension_path).expanduser() / "manifest.json"
        if manifest_path.is_file():
            unpacked_extension_ids.append(extension_id)
    return tuple(unpacked_extension_ids)


def resolve_target_extension_id(profile_dir: Path, requested_extension_id: str) -> str:
    extension_id = requested_extension_id.strip()
    if extension_id:
        if read_extension_settings(profile_dir, extension_id):
            return extension_id
        raise RuntimeError(f"{EXTENSION_NOT_FOUND_MESSAGE}: {profile_dir}；扩展 ID: {extension_id}")

    unpacked_extension_ids = find_unpacked_extension_ids(profile_dir)
    if not unpacked_extension_ids:
        raise RuntimeError(f"{NO_UNPACKED_EXTENSION_MESSAGE}: {profile_dir}")
    if len(unpacked_extension_ids) > 1:
        candidates = "、".join(unpacked_extension_ids)
        raise RuntimeError(
            f"{AMBIGUOUS_UNPACKED_EXTENSION_MESSAGE}: {profile_dir}；候选扩展: {candidates}"
        )
    return unpacked_extension_ids[0]


def wait_for_extension_page_ready(
    devtools_client: DevToolsClient,
    timeout_seconds: float = PAGE_READY_TIMEOUT_SECONDS,
) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if evaluate_javascript(devtools_client, READY_CHECK_SCRIPT):
            return
        time.sleep(0.2)
    raise TimeoutError("扩展页面未在预期时间内就绪。")


def trigger_extension_reload(
    profile_dir: Path,
    extension_id: str,
) -> str:
    remote_debugging_port = find_free_port()
    chrome_process = None
    try:
        chrome_process = launch_chrome(
            build_command(
                profile_dir,
                remote_debugging_port=remote_debugging_port,
                suppress_startup_window=True,
            )
        )
        wait_for_devtools_ready(remote_debugging_port, DEVTOOLS_READY_TIMEOUT_SECONDS)
        browser_websocket_url = fetch_browser_websocket_url(remote_debugging_port)
        browser_devtools_client = DevToolsClient(
            browser_websocket_url,
            timeout_seconds=PAGE_READY_TIMEOUT_SECONDS,
        )
        try:
            extension_page_url = build_extension_page_url(profile_dir, extension_id)
            websocket_url = create_extension_target(
                browser_devtools_client,
                remote_debugging_port,
                extension_page_url,
                timeout_seconds=DEVTOOLS_READY_TIMEOUT_SECONDS,
            )
            devtools_client = DevToolsClient(
                websocket_url,
                timeout_seconds=PAGE_READY_TIMEOUT_SECONDS,
            )
            try:
                devtools_client.call("Page.enable")
                devtools_client.call("Runtime.enable")
                wait_for_extension_page_ready(devtools_client)
                payload = evaluate_javascript(devtools_client, RELOAD_SCRIPT)
                if not isinstance(payload, dict):
                    raise RuntimeError("扩展重载返回了非预期结果。")
                status = str(payload.get("status", "")).strip()
                if status != "reload-scheduled":
                    raise RuntimeError(f"扩展重载失败: {status or '未知状态'}")
                time.sleep(RELOAD_SETTLE_SECONDS)
                return str(payload.get("version", "")).strip()
            finally:
                devtools_client.close()
        finally:
            browser_devtools_client.close()
    finally:
        try:
            close_browser_via_devtools(remote_debugging_port)
        except Exception:
            pass
        if chrome_process is not None:
            shutdown_chrome_process(chrome_process)


def run_reload_flow(
    base_dir: Path,
    *,
    profile_names: Sequence[str],
    requested_extension_id: str,
) -> None:
    ensure_chrome_exists()
    for profile_name in profile_names:
        profile_dir = resolve_profile_dir(base_dir, profile_name)
        if not profile_dir.is_dir():
            raise RuntimeError(f"{PROFILE_MISSING_MESSAGE}: {profile_dir}")

        extension_id = resolve_target_extension_id(profile_dir, requested_extension_id)
        version = trigger_extension_reload(profile_dir, extension_id)
        version_suffix = f"（源码版本 {version}）" if version else ""
        print(
            f"已刷新 profile: {profile_name}；"
            f"扩展 ID: {extension_id}{version_suffix}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    base_dir = Path(__file__).resolve().parent
    profile_names = flatten_profile_names(args.profile_groups)

    try:
        run_reload_flow(
            base_dir,
            profile_names=profile_names,
            requested_extension_id=str(args.extension_id or "").strip(),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"{LAUNCH_FAILURE_PREFIX}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
