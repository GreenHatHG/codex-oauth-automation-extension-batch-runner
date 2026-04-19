#!/usr/bin/env python3
"""Manual test helper for the local SMS receiver socket."""

from __future__ import annotations

import argparse
import sys

from chrome_runner.constants import (
    DEFAULT_SMS_CODE_REGEX,
    DEFAULT_SMS_CODE_TIMEOUT_SECONDS,
    DEFAULT_SMS_SOCKET_HOST,
)
from chrome_runner.sms import SmsCodeReceiver, send_socket_message


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="独立测试本地短信验证码接收。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    listen_parser = subparsers.add_parser("listen", help="启动监听并等待验证码。")
    listen_parser.add_argument(
        "--host",
        default=DEFAULT_SMS_SOCKET_HOST,
        help="监听地址。",
    )
    listen_parser.add_argument(
        "--port",
        type=int,
        required=True,
        help="监听端口。",
    )
    listen_parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_SMS_CODE_TIMEOUT_SECONDS,
        help="等待验证码的超时时间。",
    )
    listen_parser.add_argument(
        "--code-regex",
        default=DEFAULT_SMS_CODE_REGEX,
        help="提取验证码使用的正则，第 1 个捕获组为验证码。",
    )

    send_parser = subparsers.add_parser("send", help="发送一条测试短信。")
    send_parser.add_argument(
        "--host",
        default=DEFAULT_SMS_SOCKET_HOST,
        help="接收端地址。",
    )
    send_parser.add_argument(
        "--port",
        type=int,
        required=True,
        help="接收端端口。",
    )
    send_parser.add_argument(
        "--message",
        required=True,
        help="要发送的短信正文。",
    )
    return parser


def run_listen(args: argparse.Namespace) -> int:
    receiver = SmsCodeReceiver(
        args.host,
        args.port,
        code_regex=args.code_regex,
    )
    receiver.start()
    print(f"短信监听已启动：{args.host}:{receiver.port}")
    print(f"正在等待验证码，超时 {args.timeout_seconds} 秒。")
    try:
        received = receiver.wait_for_code(args.timeout_seconds)
    except Exception as exc:  # noqa: BLE001
        print(f"测试失败: {exc}", file=sys.stderr)
        return 1
    finally:
        receiver.close()
    print(f"收到短信正文: {received.message}")
    print(f"提取到验证码: {received.code}")
    return 0


def run_send(args: argparse.Namespace) -> int:
    try:
        send_socket_message(args.host, args.port, args.message)
    except Exception as exc:  # noqa: BLE001
        print(f"发送失败: {exc}", file=sys.stderr)
        return 1
    print("测试短信已发送。")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "listen":
        return run_listen(args)
    if args.command == "send":
        return run_send(args)
    parser.error("未知命令。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
