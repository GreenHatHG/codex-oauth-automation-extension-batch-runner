#!/usr/bin/env python3
"""Launch Chrome with a local base profile or a copied runtime profile."""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from chrome_runner.chrome import (
    build_command,
    build_runtime_profile_dir,
    copy_profile_directory,
    create_profile_directory,
    delete_profile_directory,
    ensure_chrome_exists,
    find_free_port,
    launch_chrome,
    shutdown_chrome_process,
    wait_for_chrome_exit,
)
from chrome_runner.clash import run_pre_run_clash_ai_switch
from chrome_runner.constants import BASE_PROFILE_DIR_NAME, TARGET_EXTENSION_ID
from chrome_runner.extension import ExtensionRunResult, run_extension


@dataclass(frozen=True)
class RunAttemptResult:
    """Single batch attempt result."""

    index: int
    exit_code: int
    duration_seconds: float
    summary_text: str

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0


def parse_positive_int(raw_value: str) -> int:
    try:
        parsed_value = int(raw_value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("次数必须是正整数。") from exc
    if parsed_value < 1:
        raise argparse.ArgumentTypeError("次数必须是正整数。")
    return parsed_value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="启动 Chrome，并可选地打开扩展页面后点击运行按钮。"
    )
    parser.add_argument(
        "--pre-run-clash-ai-switch",
        action="store_true",
        help="在启动浏览器前先调用 Clash HTTP 接口切换 AI 分组节点。",
    )
    parser.add_argument(
        "--run-extension",
        action="store_true",
        help="启动复制出的 Chrome 后，等待扩展执行结束，再自动关闭浏览器并清理运行目录。",
    )
    parser.add_argument(
        "--extension-id",
        default=TARGET_EXTENSION_ID,
        help="指定要运行的扩展 ID。",
    )
    parser.add_argument(
        "--repeat-count",
        type=parse_positive_int,
        default=1,
        help="按顺序重复执行指定次数。大于 1 时需要搭配 --run-extension。",
    )
    return parser.parse_args()


def report_extension_result(result: ExtensionRunResult) -> tuple[int, str]:
    if result.outcome == "success":
        message = f"扩展执行完成：{result.status_text}"
        print(message)
        return 0, message

    if result.outcome == "failure":
        message = f"扩展执行失败：{result.status_text}"
        print(message, file=sys.stderr)
        return 1, message

    message = (
        f"扩展执行卡住：{result.status_text}；连续 "
        f"{int(result.stagnant_seconds)} 秒没有进度。"
    )
    print(message, file=sys.stderr)
    return 1, message


def execute_single_run(
    args: argparse.Namespace,
    base_dir: Path,
    base_profile_dir: Path,
) -> tuple[int, str]:
    chrome_process = None
    runtime_profile_dir: Path | None = None
    should_cleanup_runtime_dir = False
    exit_code = 0
    summary_text = ""
    cleanup_error: Exception | None = None

    try:
        if args.pre_run_clash_ai_switch:
            run_pre_run_clash_ai_switch()

        ensure_chrome_exists()
        if base_profile_dir.exists():
            runtime_profile_dir = build_runtime_profile_dir(base_dir)
            copy_profile_directory(base_profile_dir, runtime_profile_dir)
            remote_debugging_port = find_free_port() if args.run_extension else None
            chrome_process = launch_chrome(
                build_command(
                    runtime_profile_dir,
                    remote_debugging_port=remote_debugging_port,
                )
            )

            if args.run_extension and remote_debugging_port is not None:
                should_cleanup_runtime_dir = True
                result = run_extension(
                    runtime_profile_dir,
                    remote_debugging_port,
                    args.extension_id,
                )
                exit_code, summary_text = report_extension_result(result)
            else:
                first_message = f"Chrome 已启动，运行配置目录: {runtime_profile_dir}"
                second_message = f"基准配置目录: {base_profile_dir}"
                print(first_message)
                print(second_message)
                summary_text = f"{first_message}；{second_message}"
            return exit_code, summary_text

        create_profile_directory(base_profile_dir)
        print("未找到基准配置目录，已启动全新 Chrome。")
        print("请在打开的浏览器中完成操作，完成后关闭浏览器。")
        chrome_process = launch_chrome(build_command(base_profile_dir))
        exit_code = wait_for_chrome_exit(chrome_process)
        if exit_code != 0:
            raise RuntimeError(f"Chrome 退出码异常: {exit_code}")

        summary_text = f"基准配置已保存: {base_profile_dir}"
        print(summary_text)
        if args.run_extension:
            note = "当前是基准配置初始化流程。下次运行时再加 --run-extension。"
            print(note)
            summary_text = f"{summary_text}；{note}"
        return exit_code, summary_text
    except Exception as exc:  # noqa: BLE001
        summary_text = f"启动失败: {exc}"
        print(summary_text, file=sys.stderr)
        exit_code = 1
    finally:
        if should_cleanup_runtime_dir and runtime_profile_dir is not None:
            try:
                if chrome_process is not None:
                    shutdown_chrome_process(chrome_process)
                delete_profile_directory(runtime_profile_dir)
                print(f"已清理运行目录: {runtime_profile_dir}")
            except Exception as exc:  # noqa: BLE001
                cleanup_error = exc

        if cleanup_error is not None:
            summary_text = f"启动失败: 清理运行目录失败：{cleanup_error}"
            print(summary_text, file=sys.stderr)
            exit_code = 1

    return exit_code, summary_text


def validate_batch_args(args: argparse.Namespace, base_profile_dir: Path) -> None:
    if args.repeat_count == 1:
        return
    if not args.run_extension:
        raise RuntimeError("多次运行模式需要搭配 --run-extension。")
    if not base_profile_dir.exists():
        raise RuntimeError("多次运行模式需要已存在的基准配置目录。")


def format_duration(duration_seconds: float) -> str:
    return f"{duration_seconds:.1f} 秒"


def print_attempt_result(result: RunAttemptResult, total_runs: int) -> None:
    outcome_text = "成功" if result.succeeded else "失败"
    print(
        f"第 {result.index}/{total_runs} 轮结束：{outcome_text}，"
        f"耗时 {format_duration(result.duration_seconds)}。"
    )


def print_batch_summary(
    results: list[RunAttemptResult],
    *,
    total_duration_seconds: float,
) -> None:
    total_runs = len(results)
    success_count = sum(1 for result in results if result.succeeded)
    failure_results = [result for result in results if not result.succeeded]
    failure_count = len(failure_results)
    average_duration_seconds = total_duration_seconds / total_runs if total_runs else 0.0
    success_rate = (success_count / total_runs * 100.0) if total_runs else 0.0

    print("批量运行汇总：")
    print(f"总轮数: {total_runs}")
    print(f"成功次数: {success_count}")
    print(f"失败次数: {failure_count}")
    print(f"成功率: {success_rate:.1f}%")
    print(f"总耗时: {format_duration(total_duration_seconds)}")
    print(f"平均每轮耗时: {format_duration(average_duration_seconds)}")

    for result in failure_results:
        print(f"失败轮次 {result.index}: {result.summary_text}")


def run_batch(
    args: argparse.Namespace,
    base_dir: Path,
    base_profile_dir: Path,
) -> int:
    results: list[RunAttemptResult] = []
    batch_started_at = time.perf_counter()

    for attempt_index in range(1, args.repeat_count + 1):
        print(f"第 {attempt_index}/{args.repeat_count} 轮开始")
        attempt_started_at = time.perf_counter()
        exit_code, summary_text = execute_single_run(args, base_dir, base_profile_dir)
        duration_seconds = time.perf_counter() - attempt_started_at
        result = RunAttemptResult(
            index=attempt_index,
            exit_code=exit_code,
            duration_seconds=duration_seconds,
            summary_text=summary_text,
        )
        results.append(result)
        print_attempt_result(result, args.repeat_count)

    total_duration_seconds = time.perf_counter() - batch_started_at
    print_batch_summary(results, total_duration_seconds=total_duration_seconds)
    return 0 if all(result.succeeded for result in results) else 1


def main() -> int:
    args = parse_args()
    base_dir = Path(__file__).resolve().parent
    base_profile_dir = base_dir / BASE_PROFILE_DIR_NAME

    try:
        validate_batch_args(args, base_profile_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"启动失败: {exc}", file=sys.stderr)
        return 1

    if args.repeat_count > 1:
        return run_batch(args, base_dir, base_profile_dir)

    started_at = time.perf_counter()
    exit_code, summary_text = execute_single_run(args, base_dir, base_profile_dir)
    result = RunAttemptResult(
        index=1,
        exit_code=exit_code,
        duration_seconds=time.perf_counter() - started_at,
        summary_text=summary_text,
    )
    print_attempt_result(result, 1)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
