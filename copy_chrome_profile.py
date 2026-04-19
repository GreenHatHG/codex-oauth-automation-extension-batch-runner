#!/usr/bin/env python3
"""Copy a local Chrome profile to a new profile and launch it for manual edits."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from chrome_runner.chrome import (
    build_command,
    copy_profile_directory,
    ensure_chrome_exists,
    launch_chrome,
    wait_for_chrome_exit,
)
from chrome_runner.profile import parse_profile_name, resolve_profile_dir

SOURCE_PROFILE_MISSING_MESSAGE = "来源 profile 不存在"
OUTPUT_PROFILE_EXISTS_MESSAGE = "输出 profile 已存在"
IDENTICAL_PROFILE_MESSAGE = "来源 profile 和输出 profile 不能相同。"
LAUNCH_FAILURE_PREFIX = "启动失败"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从已有 Chrome profile 复制出新 profile，并启动浏览器手动操作。"
    )
    parser.add_argument(
        "--profile",
        required=True,
        type=parse_profile_name,
        help="指定复制来源，对应项目根目录下已有的 profile 目录名。",
    )
    parser.add_argument(
        "--output-profile",
        required=True,
        type=parse_profile_name,
        help="指定保存目标，对应项目根目录下新的 profile 目录名。",
    )
    return parser.parse_args(argv)


def validate_profile_paths(source_profile_dir: Path, output_profile_dir: Path) -> None:
    if source_profile_dir.resolve(strict=False) == output_profile_dir.resolve(strict=False):
        raise RuntimeError(IDENTICAL_PROFILE_MESSAGE)
    if not source_profile_dir.is_dir():
        raise RuntimeError(f"{SOURCE_PROFILE_MISSING_MESSAGE}: {source_profile_dir}")
    if output_profile_dir.exists():
        raise RuntimeError(f"{OUTPUT_PROFILE_EXISTS_MESSAGE}: {output_profile_dir}")


def run_copy_flow(source_profile_dir: Path, output_profile_dir: Path) -> None:
    ensure_chrome_exists()
    validate_profile_paths(source_profile_dir, output_profile_dir)
    copy_profile_directory(source_profile_dir, output_profile_dir)

    print(f"来源 profile: {source_profile_dir}")
    print(f"输出 profile: {output_profile_dir}")
    print("请在打开的浏览器中完成操作，完成后关闭浏览器。")

    chrome_process = launch_chrome(build_command(output_profile_dir))
    exit_code = wait_for_chrome_exit(chrome_process)
    if exit_code != 0:
        raise RuntimeError(f"Chrome 退出码异常: {exit_code}")

    print(f"新 profile 已保存: {output_profile_dir}")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    base_dir = Path(__file__).resolve().parent
    source_profile_dir = resolve_profile_dir(base_dir, args.profile)
    output_profile_dir = resolve_profile_dir(base_dir, args.output_profile)

    try:
        run_copy_flow(source_profile_dir, output_profile_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"{LAUNCH_FAILURE_PREFIX}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
