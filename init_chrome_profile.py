#!/usr/bin/env python3
"""Initialize a fresh local Chrome profile for manual setup."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from chrome_runner.chrome import (
    build_command,
    create_profile_directory,
    ensure_chrome_exists,
    launch_chrome,
    wait_for_chrome_exit,
)
from chrome_runner.profile import parse_profile_name, resolve_profile_dir

PROFILE_EXISTS_MESSAGE = "目标 profile 已存在"
LAUNCH_FAILURE_PREFIX = "启动失败"
MANUAL_SETUP_PROMPT = "请在打开的浏览器中完成操作，完成后关闭浏览器。"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="初始化一个全新的 Chrome profile，并启动浏览器手动完成配置。"
    )
    parser.add_argument(
        "--profile",
        required=True,
        type=parse_profile_name,
        help="指定要初始化的 profile 目录名。",
    )
    return parser.parse_args(argv)


def validate_profile_dir(profile_dir: Path) -> None:
    if profile_dir.exists():
        raise RuntimeError(f"{PROFILE_EXISTS_MESSAGE}: {profile_dir}")


def run_init_flow(profile_dir: Path) -> None:
    ensure_chrome_exists()
    validate_profile_dir(profile_dir)
    create_profile_directory(profile_dir)

    print(f"目标 profile: {profile_dir}")
    print(MANUAL_SETUP_PROMPT)

    chrome_process = launch_chrome(build_command(profile_dir))
    exit_code = wait_for_chrome_exit(chrome_process)
    if exit_code != 0:
        raise RuntimeError(f"Chrome 退出码异常: {exit_code}")

    print(f"基准 profile 已保存: {profile_dir}")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    base_dir = Path(__file__).resolve().parent
    profile_dir = resolve_profile_dir(base_dir, args.profile)

    try:
        run_init_flow(profile_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"{LAUNCH_FAILURE_PREFIX}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
