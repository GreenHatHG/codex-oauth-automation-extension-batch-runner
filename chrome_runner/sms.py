"""Local socket helpers for receiving SMS verification codes."""

from __future__ import annotations

import queue
import re
import socket
import threading
import time
from dataclasses import dataclass

from .constants import (
    DEFAULT_SMS_CODE_REGEX,
    SMS_RECEIVER_ACCEPT_TIMEOUT_SECONDS,
    SMS_RECEIVER_BUFFER_SIZE,
    SMS_RECEIVER_CONNECTION_TIMEOUT_SECONDS,
    SMS_RECEIVER_LISTEN_BACKLOG,
)


@dataclass(frozen=True)
class ReceivedSmsCode:
    """A matched verification code extracted from one SMS message."""

    code: str
    message: str


class SmsCodeReceiver:
    """Receive SMS content over a local TCP socket and extract codes."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        code_regex: str = DEFAULT_SMS_CODE_REGEX,
    ) -> None:
        self._host = host
        self._port = port
        self._code_pattern = re.compile(code_regex)
        self._messages: queue.Queue[str] = queue.Queue()
        self._stop_event = threading.Event()
        self._server_socket: socket.socket | None = None
        self._server_thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        """Return the bound listening port."""

        if self._server_socket is None:
            return self._port
        bound_host, bound_port = self._server_socket.getsockname()[:2]
        del bound_host
        return int(bound_port)

    def start(self) -> None:
        """Start the background socket server."""

        if self._server_thread is not None:
            return

        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((self._host, self._port))
        server_socket.listen(SMS_RECEIVER_LISTEN_BACKLOG)
        server_socket.settimeout(SMS_RECEIVER_ACCEPT_TIMEOUT_SECONDS)
        self._server_socket = server_socket

        server_thread = threading.Thread(
            target=self._serve,
            name="sms-code-receiver",
            daemon=True,
        )
        server_thread.start()
        self._server_thread = server_thread

    def close(self) -> None:
        """Stop the background socket server."""

        self._stop_event.set()
        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except OSError:
                pass
            self._server_socket = None
        if self._server_thread is not None:
            self._server_thread.join(timeout=1.0)
            self._server_thread = None

    def wait_for_code(self, timeout_seconds: float) -> ReceivedSmsCode:
        """Block until a message containing a verification code is received."""

        if self._server_thread is None:
            raise RuntimeError("短信接收服务尚未启动。")

        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                raise TimeoutError(
                    f"等待短信验证码超时：{int(timeout_seconds)} 秒内没有收到有效验证码。"
                )
            try:
                message = self._messages.get(timeout=remaining_seconds)
            except queue.Empty as exc:
                raise TimeoutError(
                    f"等待短信验证码超时：{int(timeout_seconds)} 秒内没有收到有效验证码。"
                ) from exc
            match = self._code_pattern.search(message)
            if match is None:
                continue
            return ReceivedSmsCode(code=match.group(1), message=message)

    def _serve(self) -> None:
        while not self._stop_event.is_set():
            server_socket = self._server_socket
            if server_socket is None:
                return
            try:
                connection, _ = server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with connection:
                message = self._read_connection_message(connection)
            if message:
                self._messages.put(message)

    def _read_connection_message(self, connection: socket.socket) -> str:
        connection.settimeout(SMS_RECEIVER_CONNECTION_TIMEOUT_SECONDS)
        chunks: list[bytes] = []
        while True:
            try:
                chunk = connection.recv(SMS_RECEIVER_BUFFER_SIZE)
            except socket.timeout:
                break
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="replace").strip()


def send_socket_message(host: str, port: int, message: str) -> None:
    """Send one UTF-8 message to the local SMS receiver socket."""

    with socket.create_connection((host, port), timeout=5.0) as connection:
        connection.sendall(message.encode("utf-8"))
