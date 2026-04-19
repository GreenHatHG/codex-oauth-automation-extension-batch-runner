#!/usr/bin/env python3
"""Launch Chrome with a local base profile or a copied runtime profile."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
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
from chrome_runner.clash import normalize_proxy_name, run_pre_run_clash_ai_switch
from chrome_runner.constants import (
    ADD_PHONE_ERROR_SIGNAL_TEXTS,
    BASE_PROFILE_DIR_NAME,
    TARGET_EXTENSION_ID,
)
from chrome_runner.extension import ExtensionRunResult, run_extension
from chrome_runner.profile import parse_profile_name, resolve_profile_dir

CLASH_AI_SWITCH_STRATEGY_ALWAYS = "always"
CLASH_AI_SWITCH_STRATEGY_REUSE = "reuse"
CLASH_AI_SWITCH_STRATEGY_CHOICES = (
    CLASH_AI_SWITCH_STRATEGY_ALWAYS,
    CLASH_AI_SWITCH_STRATEGY_REUSE,
)
DEFAULT_CLASH_AI_SWITCH_REUSE_LIMIT = 5
DEFAULT_PROFILE_NAMES = (BASE_PROFILE_DIR_NAME,)


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


@dataclass(frozen=True)
class SingleRunResult:
    """Single run result with proxy usage metadata."""

    exit_code: int
    summary_text: str
    selected_proxy_name: str = ""
    should_blacklist_selected_proxy: bool = False

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0


@dataclass
class BatchProxyState:
    """Batch-level proxy reuse state."""

    proxy_blacklist: set[str] = field(default_factory=set)
    current_proxy_name: str = ""
    current_proxy_run_count: int = 0


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
        "--profile",
        nargs="+",
        type=parse_profile_name,
        help=(
            "指定一个或多个基准 profile 目录名，按输入顺序轮询。"
            f"默认使用 {BASE_PROFILE_DIR_NAME}。"
        ),
    )
    parser.add_argument(
        "--pre-run-clash-ai-switch",
        action="store_true",
        help=(
            "旧参数别名，等价于 "
            f"--clash-ai-switch-strategy {CLASH_AI_SWITCH_STRATEGY_ALWAYS}。"
        ),
    )
    parser.add_argument(
        "--clash-ai-switch-strategy",
        choices=CLASH_AI_SWITCH_STRATEGY_CHOICES,
        help=(
            "Clash AI 分组节点切换策略。"
            f"{CLASH_AI_SWITCH_STRATEGY_ALWAYS} 表示每轮切换，"
            f"{CLASH_AI_SWITCH_STRATEGY_REUSE} 表示复用当前节点直到达到上限或命中 addphone。"
        ),
    )
    parser.add_argument(
        "--clash-ai-switch-reuse-limit",
        type=parse_positive_int,
        default=DEFAULT_CLASH_AI_SWITCH_REUSE_LIMIT,
        help=(
            "reuse 策略下单个节点最多连续运行次数。"
            f"默认 {DEFAULT_CLASH_AI_SWITCH_REUSE_LIMIT}。"
        ),
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


def resolve_clash_ai_switch_strategy(args: argparse.Namespace) -> str:
    if getattr(args, "pre_run_clash_ai_switch", False):
        return CLASH_AI_SWITCH_STRATEGY_ALWAYS
    return str(getattr(args, "clash_ai_switch_strategy", "") or "")


def should_enable_clash_ai_switch(args: argparse.Namespace) -> bool:
    return bool(resolve_clash_ai_switch_strategy(args))


def resolve_profile_names(args: argparse.Namespace) -> tuple[str, ...]:
    profile_names = getattr(args, "profile", None)
    if profile_names:
        return tuple(profile_names)
    return DEFAULT_PROFILE_NAMES


def choose_profile_name(profile_names: Sequence[str], attempt_index: int) -> str:
    return profile_names[(attempt_index - 1) % len(profile_names)]


def build_base_profile_dir(base_dir: Path, profile_name: str) -> Path:
    return resolve_profile_dir(base_dir, profile_name)


def collect_missing_profile_dirs(
    base_dir: Path,
    profile_names: Sequence[str],
) -> list[Path]:
    missing_profile_dirs: list[Path] = []
    seen_profile_names: set[str] = set()
    for profile_name in profile_names:
        if profile_name in seen_profile_names:
            continue
        seen_profile_names.add(profile_name)
        profile_dir = build_base_profile_dir(base_dir, profile_name)
        if profile_dir.exists():
            continue
        missing_profile_dirs.append(profile_dir)
    return missing_profile_dirs


def report_extension_result(result: ExtensionRunResult) -> tuple[int, str]:
    recent_logs_text = ""
    if result.recent_logs:
        recent_logs_text = "\n最近日志：\n" + "\n".join(result.recent_logs)

    if result.outcome == "success":
        message = f"扩展执行完成：{result.status_text}"
        print(message)
        return 0, message

    if result.outcome == "failure":
        message = f"扩展执行失败：{result.status_text}{recent_logs_text}"
        print(message, file=sys.stderr)
        return 1, message

    message = (
        f"扩展执行卡住：{result.status_text}；连续 "
        f"{int(result.stagnant_seconds)} 秒没有进度。"
    )
    message = f"{message}{recent_logs_text}"
    print(message, file=sys.stderr)
    return 1, message


def should_blacklist_proxy_for_add_phone(result: ExtensionRunResult) -> bool:
    if result.outcome != "failure":
        return False
    messages = (result.status_text, *result.recent_logs)
    return any(
        signal_text in message
        for message in messages
        for signal_text in ADD_PHONE_ERROR_SIGNAL_TEXTS
    )


def maybe_blacklist_selected_proxy(
    proxy_blacklist: set[str],
    result: SingleRunResult,
) -> None:
    proxy_name = normalize_proxy_name(result.selected_proxy_name)
    if not result.should_blacklist_selected_proxy or not proxy_name:
        return
    if proxy_name in proxy_blacklist:
        return
    proxy_blacklist.add(proxy_name)
    print(f"自动运行前置：节点已加入内存黑名单，后续轮次跳过：{proxy_name}")


def should_switch_proxy_for_batch_attempt(
    args: argparse.Namespace,
    proxy_state: BatchProxyState,
) -> bool:
    strategy = resolve_clash_ai_switch_strategy(args)
    if not strategy:
        return False
    if strategy == CLASH_AI_SWITCH_STRATEGY_ALWAYS:
        return True
    current_proxy_name = normalize_proxy_name(proxy_state.current_proxy_name)
    if not current_proxy_name:
        return True
    return proxy_state.current_proxy_run_count >= args.clash_ai_switch_reuse_limit


def maybe_report_reused_proxy_for_batch_attempt(
    args: argparse.Namespace,
    proxy_state: BatchProxyState,
) -> None:
    strategy = resolve_clash_ai_switch_strategy(args)
    current_proxy_name = normalize_proxy_name(proxy_state.current_proxy_name)
    if strategy != CLASH_AI_SWITCH_STRATEGY_REUSE or not current_proxy_name:
        return
    if proxy_state.current_proxy_run_count >= args.clash_ai_switch_reuse_limit:
        print(
            f"自动运行前置：节点 {current_proxy_name} 已连续运行 "
            f"{proxy_state.current_proxy_run_count} 次，准备切换新节点。"
        )
        return
    print(
        f"自动运行前置：继续复用节点 {current_proxy_name}，当前已连续运行 "
        f"{proxy_state.current_proxy_run_count} 次，上限 "
        f"{args.clash_ai_switch_reuse_limit} 次。"
    )


def update_batch_proxy_state(
    proxy_state: BatchProxyState,
    result: SingleRunResult,
) -> None:
    proxy_name = normalize_proxy_name(result.selected_proxy_name)
    if result.should_blacklist_selected_proxy:
        maybe_blacklist_selected_proxy(proxy_state.proxy_blacklist, result)
        proxy_state.current_proxy_name = ""
        proxy_state.current_proxy_run_count = 0
        return
    if not proxy_name:
        return
    if proxy_name == normalize_proxy_name(proxy_state.current_proxy_name):
        proxy_state.current_proxy_run_count += 1
        return
    proxy_state.current_proxy_name = proxy_name
    proxy_state.current_proxy_run_count = 1


def execute_single_run(
    args: argparse.Namespace,
    base_dir: Path,
    base_profile_dir: Path,
    *,
    excluded_proxy_names: frozenset[str] = frozenset(),
    current_proxy_name: str = "",
    should_switch_proxy: bool | None = None,
) -> SingleRunResult:
    chrome_process = None
    runtime_profile_dir: Path | None = None
    should_cleanup_runtime_dir = False
    exit_code = 0
    summary_text = ""
    cleanup_error: Exception | None = None
    if should_switch_proxy is None:
        should_switch_proxy = should_enable_clash_ai_switch(args)
    selected_proxy_name = (
        ""
        if should_switch_proxy
        else normalize_proxy_name(current_proxy_name)
    )
    should_blacklist_selected_proxy = False

    try:
        if should_switch_proxy:
            switch_result = run_pre_run_clash_ai_switch(
                excluded_proxy_names=excluded_proxy_names
            )
            selected_proxy_name = normalize_proxy_name(switch_result.get("proxy_name"))

        ensure_chrome_exists()
        if base_profile_dir.exists():
            runtime_profile_dir = build_runtime_profile_dir(base_dir)
            copy_profile_directory(base_profile_dir, runtime_profile_dir)
            remote_debugging_port = find_free_port() if args.run_extension else None
            chrome_process = launch_chrome(
                build_command(
                    runtime_profile_dir,
                    remote_debugging_port=remote_debugging_port,
                    suppress_startup_window=args.run_extension,
                ),
            )

            if args.run_extension and remote_debugging_port is not None:
                should_cleanup_runtime_dir = True
                result = run_extension(
                    runtime_profile_dir,
                    remote_debugging_port,
                    args.extension_id,
                )
                exit_code, summary_text = report_extension_result(result)
                should_blacklist_selected_proxy = (
                    bool(selected_proxy_name)
                    and should_blacklist_proxy_for_add_phone(result)
                )
            else:
                first_message = f"Chrome 已启动，运行配置目录: {runtime_profile_dir}"
                second_message = f"基准配置目录: {base_profile_dir}"
                print(first_message)
                print(second_message)
                summary_text = f"{first_message}；{second_message}"
        else:
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

    return SingleRunResult(
        exit_code=exit_code,
        summary_text=summary_text,
        selected_proxy_name=selected_proxy_name,
        should_blacklist_selected_proxy=should_blacklist_selected_proxy,
    )


def validate_batch_args(
    args: argparse.Namespace,
    base_dir: Path,
    profile_names: Sequence[str],
) -> None:
    if (
        getattr(args, "pre_run_clash_ai_switch", False)
        and getattr(args, "clash_ai_switch_strategy", None)
    ):
        raise RuntimeError(
            "--pre-run-clash-ai-switch 和 --clash-ai-switch-strategy 不能同时使用。"
        )
    if args.repeat_count == 1:
        return
    if not args.run_extension:
        raise RuntimeError("多次运行模式需要搭配 --run-extension。")
    missing_profile_dirs = collect_missing_profile_dirs(base_dir, profile_names)
    if missing_profile_dirs:
        missing_dirs_text = "、".join(str(path) for path in missing_profile_dirs)
        raise RuntimeError(f"多次运行模式缺少 profile 目录：{missing_dirs_text}")


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
    profile_names: Sequence[str],
) -> int:
    results: list[RunAttemptResult] = []
    batch_started_at = time.perf_counter()
    proxy_state = BatchProxyState()

    for attempt_index in range(1, args.repeat_count + 1):
        profile_name = choose_profile_name(profile_names, attempt_index)
        base_profile_dir = build_base_profile_dir(base_dir, profile_name)
        print(f"第 {attempt_index}/{args.repeat_count} 轮开始")
        print(f"本轮基准 profile: {profile_name}")
        attempt_started_at = time.perf_counter()
        should_switch_proxy = should_switch_proxy_for_batch_attempt(args, proxy_state)
        if not should_switch_proxy:
            maybe_report_reused_proxy_for_batch_attempt(args, proxy_state)
        single_run_result = execute_single_run(
            args,
            base_dir,
            base_profile_dir,
            excluded_proxy_names=frozenset(proxy_state.proxy_blacklist),
            current_proxy_name=proxy_state.current_proxy_name,
            should_switch_proxy=should_switch_proxy,
        )
        update_batch_proxy_state(proxy_state, single_run_result)
        duration_seconds = time.perf_counter() - attempt_started_at
        result = RunAttemptResult(
            index=attempt_index,
            exit_code=single_run_result.exit_code,
            duration_seconds=duration_seconds,
            summary_text=single_run_result.summary_text,
        )
        results.append(result)
        print_attempt_result(result, args.repeat_count)

    total_duration_seconds = time.perf_counter() - batch_started_at
    print_batch_summary(results, total_duration_seconds=total_duration_seconds)
    return 0 if all(result.succeeded for result in results) else 1


def main() -> int:
    args = parse_args()
    base_dir = Path(__file__).resolve().parent
    profile_names = resolve_profile_names(args)

    try:
        validate_batch_args(args, base_dir, profile_names)
    except Exception as exc:  # noqa: BLE001
        print(f"启动失败: {exc}", file=sys.stderr)
        return 1

    if args.repeat_count > 1:
        return run_batch(args, base_dir, profile_names)

    profile_name = choose_profile_name(profile_names, 1)
    base_profile_dir = build_base_profile_dir(base_dir, profile_name)
    print(f"本轮基准 profile: {profile_name}")
    started_at = time.perf_counter()
    single_run_result = execute_single_run(args, base_dir, base_profile_dir)
    result = RunAttemptResult(
        index=1,
        exit_code=single_run_result.exit_code,
        duration_seconds=time.perf_counter() - started_at,
        summary_text=single_run_result.summary_text,
    )
    print_attempt_result(result, 1)
    return single_run_result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
