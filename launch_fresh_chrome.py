#!/usr/bin/env python3
"""Launch Chrome with a local base profile or a copied runtime profile."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from chrome_runner.chrome import (
    build_command,
    build_runtime_profile_dir,
    copy_profile_directory,
    delete_profile_directory,
    ensure_chrome_exists,
    find_free_port,
    launch_chrome,
    shutdown_chrome_process,
)
from chrome_runner.clash import normalize_proxy_name, run_pre_run_clash_ai_switch
from chrome_runner.constants import (
    ADD_PHONE_ERROR_SIGNAL_TEXTS,
    BASE_PROFILE_DIR_NAME,
    DEFAULT_SMS_CODE_REGEX,
    DEFAULT_SMS_CODE_TIMEOUT_SECONDS,
    DEFAULT_PROXY_BLACKLIST_TTL_SECONDS,
    DEFAULT_PROFILE_BLACKLIST_TTL_SECONDS,
    DEFAULT_SMS_SOCKET_HOST,
    PROFILE_BLACKLIST_SIGNAL_TEXTS,
    TARGET_EXTENSION_ID,
)
from chrome_runner.devtools import close_browser_via_devtools
from chrome_runner.extension import ExtensionRunResult, run_extension
from chrome_runner.profile import (
    parse_profile_name,
    profile_uses_2925_mailbox,
    resolve_profile_dir,
)
from chrome_runner.profile_blacklist import (
    load_active_profile_blacklist_names,
    record_profile_blacklist_hit,
)
from chrome_runner.proxy_blacklist import (
    load_active_proxy_blacklist_names,
    record_proxy_blacklist_hit,
)
from chrome_runner.proxy_stats import (
    ProxyStatsEntry,
    load_proxy_stats_entries,
    record_proxy_success,
)
from chrome_runner.sms_verification import (
    SmsCodeAutomation,
    SmsCodeAutomationConfig,
)

CLASH_AI_SWITCH_STRATEGY_ALWAYS = "always"
CLASH_AI_SWITCH_STRATEGY_REUSE = "reuse"
CLASH_AI_SWITCH_STRATEGY_CHOICES = (
    CLASH_AI_SWITCH_STRATEGY_ALWAYS,
    CLASH_AI_SWITCH_STRATEGY_REUSE,
)
DEFAULT_CLASH_AI_SWITCH_REUSE_LIMIT = 5
DEFAULT_PROFILE_NAMES = (BASE_PROFILE_DIR_NAME,)
MANUAL_PRE_RUN_CANCEL_INPUTS = frozenset({"q", "quit", "exit"})
MANUAL_PRE_RUN_PROMPT = (
    "请在当前 Chrome 完成前置操作，完成后按回车继续自动运行，"
    "输入 q 后回车取消本轮："
)
MANUAL_PRE_RUN_NOTICE = "自动运行前置：请在当前 Chrome 完成手动操作。"
MANUAL_PRE_RUN_RESUME_NOTICE = "自动运行前置：收到继续指令，开始执行扩展。"
MANUAL_PRE_RUN_CANCEL_MESSAGE = "已取消本轮自动运行。"
MANUAL_PRE_RUN_STDIN_ERROR = "当前运行需要交互式终端，无法读取继续指令。"
AUTO_MINIMIZE_DISABLED_HELP = (
    "自动运行时保持 Chrome 和扩展窗口可见。"
    "默认会自动最小化。仅对 --run-extension 生效。"
)
INTERRUPTED_EXIT_CODE = 130
INTERRUPTED_MESSAGE = "已中断当前运行。"
INIT_PROFILE_SCRIPT_NAME = "init_chrome_profile.py"
MISSING_PROFILE_MESSAGE = "缺少基准 profile 目录"


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
    selected_proxy_delay_ms: int | None = None
    should_blacklist_selected_proxy: bool = False

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0


@dataclass
class BatchProxyState:
    """Batch-level proxy reuse state."""

    current_proxy_name: str = ""
    current_proxy_run_count: int = 0


@dataclass
class BatchProfileState:
    """Batch-level profile selection state."""

    next_profile_index: int = 0


@dataclass(frozen=True)
class ProxySelectionState:
    """Current proxy filtering and priority state."""

    blacklisted_proxy_names: frozenset[str] = frozenset()
    stats_entries: dict[str, ProxyStatsEntry] = field(default_factory=dict)


def parse_positive_int(raw_value: str) -> int:
    try:
        parsed_value = int(raw_value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("参数值必须是正整数。") from exc
    if parsed_value < 1:
        raise argparse.ArgumentTypeError("参数值必须是正整数。")
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
            f"{CLASH_AI_SWITCH_STRATEGY_REUSE} 表示成功时继续复用当前节点，"
            "直到达到上限或命中 add-phone。"
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
        "--proxy-blacklist-ttl-seconds",
        type=parse_positive_int,
        default=DEFAULT_PROXY_BLACKLIST_TTL_SECONDS,
        help=(
            "本地节点黑名单冷却时长。节点命中 add-phone 后，"
            "达到该秒数前都会被跳过。"
            f"默认 {DEFAULT_PROXY_BLACKLIST_TTL_SECONDS} 秒。"
        ),
    )
    parser.add_argument(
        "--profile-blacklist-ttl-seconds",
        type=parse_positive_int,
        default=DEFAULT_PROFILE_BLACKLIST_TTL_SECONDS,
        help=(
            "本地 profile 黑名单冷却时长。2925 邮箱 profile 命中子账号数量上限通知后，"
            "达到该秒数前都会被跳过。"
            f"默认 {DEFAULT_PROFILE_BLACKLIST_TTL_SECONDS} 秒。"
        ),
    )
    parser.add_argument(
        "--run-extension",
        action="store_true",
        help="启动复制出的 Chrome 后，等待扩展执行结束，再自动关闭浏览器并清理运行目录。",
    )
    parser.add_argument(
        "--no-auto-minimize",
        action="store_true",
        help=AUTO_MINIMIZE_DISABLED_HELP,
    )
    parser.add_argument(
        "--pause-before-run-extension",
        action="store_true",
        help=(
            "启动复制出的 Chrome 后暂停，等待手动完成前置操作，"
            "回车后再继续扩展自动运行。需要搭配 --run-extension。"
        ),
    )
    parser.add_argument(
        "--extension-id",
        default=TARGET_EXTENSION_ID,
        help="指定要运行的扩展 ID。",
    )
    parser.add_argument(
        "--max-attempt-seconds",
        type=parse_positive_int,
        default=None,
        help=(
            "单轮最大运行时间。超过后自动关闭浏览器并清理运行目录，"
            "仅对 --run-extension 生效。"
        ),
    )
    parser.add_argument(
        "--repeat-count",
        type=parse_positive_int,
        default=1,
        help="按顺序重复执行指定次数。大于 1 时需要搭配 --run-extension。",
    )
    parser.add_argument(
        "--sms-socket-host",
        default=DEFAULT_SMS_SOCKET_HOST,
        help="本地短信接收 socket 的监听地址。",
    )
    parser.add_argument(
        "--sms-socket-port",
        type=parse_positive_int,
        default=None,
        help="本地短信接收 socket 的监听端口。设置后会在验证码日志出现时等待短信并自动填码。",
    )
    parser.add_argument(
        "--sms-code-timeout-seconds",
        type=parse_positive_int,
        default=DEFAULT_SMS_CODE_TIMEOUT_SECONDS,
        help=(
            "检测到验证码等待日志后，最多等待短信验证码的时长。"
            f"默认 {DEFAULT_SMS_CODE_TIMEOUT_SECONDS} 秒。"
        ),
    )
    parser.add_argument(
        "--sms-code-regex",
        default=DEFAULT_SMS_CODE_REGEX,
        help="从短信正文里提取验证码时使用的正则，要求第 1 个捕获组为验证码。",
    )
    parser.add_argument(
        "--sms-code-input-selector",
        default="",
        help="验证码输入框 CSS selector。留空时使用内置规则查找。",
    )
    parser.add_argument(
        "--sms-code-submit-selector",
        default="",
        help="验证码提交按钮 CSS selector。留空时按按钮文案自动查找。",
    )
    return parser.parse_args()


def resolve_clash_ai_switch_strategy(args: argparse.Namespace) -> str:
    if getattr(args, "pre_run_clash_ai_switch", False):
        return CLASH_AI_SWITCH_STRATEGY_ALWAYS
    return str(getattr(args, "clash_ai_switch_strategy", "") or "")


def should_enable_clash_ai_switch(args: argparse.Namespace) -> bool:
    return bool(resolve_clash_ai_switch_strategy(args))


def should_auto_minimize(args: argparse.Namespace) -> bool:
    return bool(args.run_extension and not getattr(args, "no_auto_minimize", False))


def should_enable_sms_code_flow(args: argparse.Namespace) -> bool:
    return getattr(args, "sms_socket_port", None) is not None


def resolve_profile_names(args: argparse.Namespace) -> tuple[str, ...]:
    profile_names = getattr(args, "profile", None)
    if profile_names:
        return tuple(profile_names)
    return DEFAULT_PROFILE_NAMES


def build_base_profile_dir(base_dir: Path, profile_name: str) -> Path:
    return resolve_profile_dir(base_dir, profile_name)


def build_init_profile_command(profile_name: str) -> str:
    return f"python3 {INIT_PROFILE_SCRIPT_NAME} --profile {profile_name}"


def build_missing_profile_error(profile_dir: Path) -> str:
    init_command = build_init_profile_command(profile_dir.name)
    return f"{MISSING_PROFILE_MESSAGE}: {profile_dir}。请先运行：{init_command}"


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

    if result.outcome == "attempt_timeout":
        message = (
            f"扩展执行超时：{result.status_text}；本轮运行已超过 "
            f"{int(result.timeout_seconds)} 秒。"
        )
        message = f"{message}{recent_logs_text}"
        print(message, file=sys.stderr)
        return 1, message

    message = (
        f"扩展执行卡住：{result.status_text}；连续 "
        f"{int(result.timeout_seconds)} 秒没有进度。"
    )
    message = f"{message}{recent_logs_text}"
    print(message, file=sys.stderr)
    return 1, message


def build_extension_result_messages(result: ExtensionRunResult) -> tuple[str, ...]:
    return (result.status_text, *result.recent_logs)


def has_any_signal_text(messages: Collection[str], signal_texts: Collection[str]) -> bool:
    return any(
        signal_text in message
        for message in messages
        for signal_text in signal_texts
    )


def should_blacklist_proxy_for_add_phone(result: ExtensionRunResult) -> bool:
    if result.outcome != "failure":
        return False
    return has_any_signal_text(
        build_extension_result_messages(result),
        ADD_PHONE_ERROR_SIGNAL_TEXTS,
    )


def should_blacklist_profile_for_limit_notice(
    result: ExtensionRunResult,
    *,
    uses_2925_mailbox: bool,
) -> bool:
    if not uses_2925_mailbox:
        return False
    return has_any_signal_text(
        build_extension_result_messages(result),
        PROFILE_BLACKLIST_SIGNAL_TEXTS,
    )


def maybe_record_selected_proxy_blacklist(
    base_dir: Path,
    *,
    proxy_name: str,
    should_blacklist_proxy: bool,
) -> None:
    proxy_name = normalize_proxy_name(proxy_name)
    if not should_blacklist_proxy or not proxy_name:
        return
    is_new_entry = record_proxy_blacklist_hit(base_dir, proxy_name)
    if is_new_entry:
        print(f"自动运行前置：节点已写入本地黑名单：{proxy_name}")
        return
    print(f"自动运行前置：节点再次命中 add-phone，已刷新本地黑名单时间：{proxy_name}")


def maybe_record_profile_blacklist(
    base_dir: Path,
    *,
    profile_name: str,
    should_blacklist_profile: bool,
) -> None:
    if not should_blacklist_profile:
        return
    is_new_entry = record_profile_blacklist_hit(base_dir, profile_name)
    if is_new_entry:
        print(f"自动运行前置：profile 已写入本地黑名单：{profile_name}")
        return
    print(
        f"自动运行前置：profile 再次命中子账号数量上限通知，"
        f"已刷新本地黑名单时间：{profile_name}"
    )


def maybe_reset_reused_proxy_for_blacklist(
    proxy_state: BatchProxyState,
    active_proxy_blacklist: Collection[str],
) -> None:
    current_proxy_name = normalize_proxy_name(proxy_state.current_proxy_name)
    if not current_proxy_name or current_proxy_name not in active_proxy_blacklist:
        return
    print(
        f"自动运行前置：当前复用节点 {current_proxy_name} 处于本地黑名单冷却期，"
        "准备切换新节点。"
    )
    proxy_state.current_proxy_name = ""
    proxy_state.current_proxy_run_count = 0


def load_active_proxy_blacklist(
    args: argparse.Namespace,
    base_dir: Path,
) -> frozenset[str]:
    if not should_enable_clash_ai_switch(args):
        return frozenset()
    return load_active_proxy_blacklist_names(
        base_dir,
        args.proxy_blacklist_ttl_seconds,
    )


def load_proxy_selection_state(
    args: argparse.Namespace,
    base_dir: Path,
) -> ProxySelectionState:
    active_proxy_blacklist = load_active_proxy_blacklist(args, base_dir)
    if not should_enable_clash_ai_switch(args):
        return ProxySelectionState(
            blacklisted_proxy_names=active_proxy_blacklist,
        )
    proxy_stats_entries = load_proxy_stats_entries(base_dir)
    return ProxySelectionState(
        blacklisted_proxy_names=active_proxy_blacklist,
        stats_entries=proxy_stats_entries,
    )


def load_active_profile_blacklist(
    args: argparse.Namespace,
    base_dir: Path,
) -> frozenset[str]:
    return load_active_profile_blacklist_names(
        base_dir,
        args.profile_blacklist_ttl_seconds,
    )


def format_profile_names(profile_names: Collection[str]) -> str:
    seen_profile_names: set[str] = set()
    ordered_profile_names: list[str] = []
    for profile_name in profile_names:
        if profile_name in seen_profile_names:
            continue
        seen_profile_names.add(profile_name)
        ordered_profile_names.append(profile_name)
    return "、".join(ordered_profile_names)


def report_skipped_blacklisted_profiles(
    profile_names: Sequence[str],
    active_profile_blacklist: Collection[str],
) -> None:
    skipped_profile_names = tuple(
        profile_name
        for profile_name in profile_names
        if profile_name in active_profile_blacklist
    )
    if not skipped_profile_names:
        return
    skipped_profile_names_text = format_profile_names(skipped_profile_names)
    print(f"自动运行前置：profile 黑名单冷却期跳过：{skipped_profile_names_text}。")


def choose_next_profile_name(
    profile_names: Sequence[str],
    active_profile_blacklist: Collection[str],
    profile_state: BatchProfileState,
) -> str:
    total_profile_count = len(profile_names)
    if total_profile_count == 0:
        raise RuntimeError("没有可用的 profile。")

    for offset in range(total_profile_count):
        profile_index = (profile_state.next_profile_index + offset) % total_profile_count
        profile_name = profile_names[profile_index]
        if profile_name in active_profile_blacklist:
            continue
        profile_state.next_profile_index = (profile_index + 1) % total_profile_count
        return profile_name

    blacklisted_profile_names_text = format_profile_names(profile_names)
    if total_profile_count == 1:
        raise RuntimeError(
            f"profile {blacklisted_profile_names_text} 处于本地黑名单冷却期。"
        )
    raise RuntimeError(
        f"所有 profile 都处于本地黑名单冷却期：{blacklisted_profile_names_text}"
    )


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
    if result.should_blacklist_selected_proxy or not result.succeeded:
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


def maybe_record_selected_proxy_success(
    base_dir: Path,
    *,
    proxy_name: str,
) -> None:
    proxy_name = normalize_proxy_name(proxy_name)
    if not proxy_name:
        return
    record_proxy_success(base_dir, proxy_name)


def parse_selected_proxy_delay(raw_value: object) -> int | None:
    if isinstance(raw_value, (int, float)) and raw_value >= 0:
        return int(raw_value)
    return None


def build_sms_code_automation(
    args: argparse.Namespace,
    *,
    devtools_port: int,
) -> SmsCodeAutomation | None:
    if not should_enable_sms_code_flow(args):
        return None
    config = SmsCodeAutomationConfig(
        socket_host=args.sms_socket_host,
        socket_port=args.sms_socket_port,
        code_timeout_seconds=args.sms_code_timeout_seconds,
        code_regex=args.sms_code_regex,
        input_selector=args.sms_code_input_selector,
        submit_selector=args.sms_code_submit_selector,
    )
    return SmsCodeAutomation(
        devtools_port=devtools_port,
        extension_id=args.extension_id,
        config=config,
    )


def report_runtime_profile_paths(
    runtime_profile_dir: Path,
    base_profile_dir: Path,
) -> str:
    first_message = f"Chrome 已启动，运行配置目录: {runtime_profile_dir}"
    second_message = f"基准配置目录: {base_profile_dir}"
    print(first_message)
    print(second_message)
    return f"{first_message}；{second_message}"


def wait_for_manual_pre_run_confirmation(
    runtime_profile_dir: Path,
    base_profile_dir: Path,
) -> None:
    report_runtime_profile_paths(runtime_profile_dir, base_profile_dir)
    print(MANUAL_PRE_RUN_NOTICE)
    try:
        user_input = input(MANUAL_PRE_RUN_PROMPT).strip().lower()
    except EOFError as exc:
        raise RuntimeError(MANUAL_PRE_RUN_STDIN_ERROR) from exc
    if user_input in MANUAL_PRE_RUN_CANCEL_INPUTS:
        raise RuntimeError(MANUAL_PRE_RUN_CANCEL_MESSAGE)
    print(MANUAL_PRE_RUN_RESUME_NOTICE)


def execute_single_run(
    args: argparse.Namespace,
    base_dir: Path,
    base_profile_dir: Path,
    *,
    excluded_proxy_names: frozenset[str] = frozenset(),
    proxy_stats_entries: dict[str, ProxyStatsEntry] | None = None,
    current_proxy_name: str = "",
    should_switch_proxy: bool | None = None,
) -> SingleRunResult:
    chrome_process = None
    sms_code_automation: SmsCodeAutomation | None = None
    remote_debugging_port: int | None = None
    runtime_profile_dir: Path | None = None
    should_cleanup_runtime_dir = False
    exit_code = 0
    summary_text = ""
    cleanup_error: Exception | None = None
    profile_name = base_profile_dir.name
    uses_2925_mailbox = profile_uses_2925_mailbox(base_profile_dir)
    if should_switch_proxy is None:
        should_switch_proxy = should_enable_clash_ai_switch(args)
    selected_proxy_name = (
        ""
        if should_switch_proxy
        else normalize_proxy_name(current_proxy_name)
    )
    selected_proxy_delay_ms: int | None = None
    should_blacklist_selected_proxy = False

    try:
        if not base_profile_dir.is_dir():
            raise RuntimeError(build_missing_profile_error(base_profile_dir))
        if should_switch_proxy:
            switch_result = run_pre_run_clash_ai_switch(
                excluded_proxy_names=excluded_proxy_names,
                proxy_stats_entries=proxy_stats_entries,
            )
            selected_proxy_name = normalize_proxy_name(switch_result.get("proxy_name"))
            selected_proxy_delay_ms = parse_selected_proxy_delay(
                switch_result.get("delay")
            )

        ensure_chrome_exists()
        runtime_profile_dir = build_runtime_profile_dir(base_dir)
        copy_profile_directory(base_profile_dir, runtime_profile_dir)
        remote_debugging_port = find_free_port() if args.run_extension else None
        if args.run_extension and remote_debugging_port is not None:
            sms_code_automation = build_sms_code_automation(
                args,
                devtools_port=remote_debugging_port,
            )
            if sms_code_automation is not None:
                sms_code_automation.start()
        chrome_process = launch_chrome(
            build_command(
                runtime_profile_dir,
                remote_debugging_port=remote_debugging_port,
                suppress_startup_window=(
                    should_auto_minimize(args)
                    and not args.pause_before_run_extension
                ),
            ),
        )

        if args.run_extension and remote_debugging_port is not None:
            should_cleanup_runtime_dir = True
            if args.pause_before_run_extension:
                wait_for_manual_pre_run_confirmation(
                    runtime_profile_dir,
                    base_profile_dir,
                )
            result = run_extension(
                runtime_profile_dir,
                remote_debugging_port,
                args.extension_id,
                auto_minimize=should_auto_minimize(args),
                max_attempt_seconds=args.max_attempt_seconds,
                snapshot_observer=(
                    sms_code_automation.maybe_handle_snapshot
                    if sms_code_automation is not None
                    else None
                ),
            )
            exit_code, summary_text = report_extension_result(result)
            should_blacklist_selected_proxy = (
                bool(selected_proxy_name)
                and should_blacklist_proxy_for_add_phone(result)
            )
            if result.outcome == "success":
                maybe_record_selected_proxy_success(
                    base_dir,
                    proxy_name=selected_proxy_name,
                )
            should_blacklist_profile = should_blacklist_profile_for_limit_notice(
                result,
                uses_2925_mailbox=uses_2925_mailbox,
            )
            maybe_record_selected_proxy_blacklist(
                base_dir,
                proxy_name=selected_proxy_name,
                should_blacklist_proxy=should_blacklist_selected_proxy,
            )
            maybe_record_profile_blacklist(
                base_dir,
                profile_name=profile_name,
                should_blacklist_profile=should_blacklist_profile,
            )
        else:
            summary_text = report_runtime_profile_paths(
                runtime_profile_dir,
                base_profile_dir,
            )
    except Exception as exc:  # noqa: BLE001
        summary_text = f"启动失败: {exc}"
        print(summary_text, file=sys.stderr)
        exit_code = 1
    finally:
        if sms_code_automation is not None:
            sms_code_automation.close()
        if should_cleanup_runtime_dir and runtime_profile_dir is not None:
            try:
                if remote_debugging_port is not None:
                    try:
                        close_browser_via_devtools(remote_debugging_port)
                    except Exception:
                        pass
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
        selected_proxy_delay_ms=selected_proxy_delay_ms,
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
    if args.pause_before_run_extension and not args.run_extension:
        raise RuntimeError("--pause-before-run-extension 需要搭配 --run-extension。")
    if should_enable_sms_code_flow(args) and not args.run_extension:
        raise RuntimeError("--sms-socket-port 需要搭配 --run-extension。")
    if args.max_attempt_seconds is not None and not args.run_extension:
        raise RuntimeError("--max-attempt-seconds 需要搭配 --run-extension。")
    if args.repeat_count == 1:
        return
    if not args.run_extension:
        raise RuntimeError("多次运行模式需要搭配 --run-extension。")
    missing_profile_dirs = collect_missing_profile_dirs(base_dir, profile_names)
    if missing_profile_dirs:
        missing_profile_error_text = "；".join(
            build_missing_profile_error(path) for path in missing_profile_dirs
        )
        raise RuntimeError(missing_profile_error_text)


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
    profile_state = BatchProfileState()

    for attempt_index in range(1, args.repeat_count + 1):
        active_profile_blacklist = load_active_profile_blacklist(args, base_dir)
        report_skipped_blacklisted_profiles(profile_names, active_profile_blacklist)
        profile_name = choose_next_profile_name(
            profile_names,
            active_profile_blacklist,
            profile_state,
        )
        base_profile_dir = build_base_profile_dir(base_dir, profile_name)
        print(f"第 {attempt_index}/{args.repeat_count} 轮开始")
        print(f"本轮基准 profile: {profile_name}")
        attempt_started_at = time.perf_counter()
        proxy_selection_state = load_proxy_selection_state(args, base_dir)
        maybe_reset_reused_proxy_for_blacklist(
            proxy_state,
            proxy_selection_state.blacklisted_proxy_names,
        )
        should_switch_proxy = should_switch_proxy_for_batch_attempt(args, proxy_state)
        if not should_switch_proxy:
            maybe_report_reused_proxy_for_batch_attempt(args, proxy_state)
        single_run_result = execute_single_run(
            args,
            base_dir,
            base_profile_dir,
            excluded_proxy_names=proxy_selection_state.blacklisted_proxy_names,
            proxy_stats_entries=proxy_selection_state.stats_entries,
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
        try:
            return run_batch(args, base_dir, profile_names)
        except KeyboardInterrupt:
            print(INTERRUPTED_MESSAGE, file=sys.stderr)
            return INTERRUPTED_EXIT_CODE
        except Exception as exc:  # noqa: BLE001
            print(f"启动失败: {exc}", file=sys.stderr)
            return 1

    active_profile_blacklist = load_active_profile_blacklist(args, base_dir)
    report_skipped_blacklisted_profiles(profile_names, active_profile_blacklist)
    try:
        profile_name = choose_next_profile_name(
            profile_names,
            active_profile_blacklist,
            BatchProfileState(),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"启动失败: {exc}", file=sys.stderr)
        return 1
    base_profile_dir = build_base_profile_dir(base_dir, profile_name)
    if not base_profile_dir.is_dir():
        print(
            f"启动失败: {build_missing_profile_error(base_profile_dir)}",
            file=sys.stderr,
        )
        return 1
    print(f"本轮基准 profile: {profile_name}")
    started_at = time.perf_counter()
    proxy_selection_state = load_proxy_selection_state(args, base_dir)
    try:
        single_run_result = execute_single_run(
            args,
            base_dir,
            base_profile_dir,
            excluded_proxy_names=proxy_selection_state.blacklisted_proxy_names,
            proxy_stats_entries=proxy_selection_state.stats_entries,
        )
    except KeyboardInterrupt:
        print(INTERRUPTED_MESSAGE, file=sys.stderr)
        return INTERRUPTED_EXIT_CODE
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
