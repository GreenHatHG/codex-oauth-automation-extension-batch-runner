"""Minimal Chrome DevTools Protocol helpers."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import time
import urllib.error
import urllib.parse
import urllib.request

from .constants import (
    DEVTOOLS_HOST,
    DEVTOOLS_HTTP_TIMEOUT_SECONDS,
    DEVTOOLS_POLL_INTERVAL_SECONDS,
    DEVTOOLS_TARGET_DISCOVERY_TIMEOUT_SECONDS,
)


class DevToolsClient:
    """Minimal Chrome DevTools Protocol client over raw WebSocket."""

    def __init__(self, websocket_url: str, timeout_seconds: float) -> None:
        parsed_url = urllib.parse.urlparse(websocket_url)
        if parsed_url.scheme != "ws":
            raise ValueError(f"不支持的 WebSocket 协议: {parsed_url.scheme}")

        self._socket = socket.create_connection(
            (parsed_url.hostname or DEVTOOLS_HOST, parsed_url.port or 80),
            timeout_seconds,
        )
        self._socket.settimeout(timeout_seconds)
        self._pending_events: list[dict[str, object]] = []
        self._next_message_id = 0
        self._handshake(parsed_url)

    def close(self) -> None:
        try:
            self._send_frame(b"", opcode=0x8)
        except OSError:
            pass
        self._socket.close()

    def call(
        self, method: str, params: dict[str, object] | None = None
    ) -> dict[str, object]:
        self._next_message_id += 1
        message_id = self._next_message_id
        payload: dict[str, object] = {"id": message_id, "method": method}
        if params:
            payload["params"] = params
        self._send_json(payload)

        while True:
            message = self._receive_json()
            if message.get("id") == message_id:
                return message
            self._pending_events.append(message)

    def wait_for_event(self, method: str, timeout_seconds: float) -> dict[str, object]:
        deadline = time.time() + timeout_seconds
        for index, pending_event in enumerate(self._pending_events):
            if pending_event.get("method") == method:
                return self._pending_events.pop(index)

        while time.time() < deadline:
            self._socket.settimeout(max(deadline - time.time(), 0.1))
            message = self._receive_json()
            if message.get("method") == method:
                return message
            self._pending_events.append(message)

        raise TimeoutError(f"等待 DevTools 事件超时: {method}")

    def _handshake(self, parsed_url: urllib.parse.ParseResult) -> None:
        websocket_key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {parsed_url.path or '/'}"
            f"{'?' + parsed_url.query if parsed_url.query else ''} HTTP/1.1\r\n"
            f"Host: {parsed_url.hostname}:{parsed_url.port or 80}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {websocket_key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self._socket.sendall(request.encode("ascii"))

        response = self._read_http_headers()
        status_line = response.splitlines()[0] if response else ""
        status_parts = status_line.split()
        if len(status_parts) < 2 or status_parts[1] != "101":
            raise RuntimeError(f"WebSocket 握手失败: {status_line}")

        accept_seed = (websocket_key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode(
            "ascii"
        )
        expected_accept = base64.b64encode(hashlib.sha1(accept_seed).digest()).decode(
            "ascii"
        )
        if f"sec-websocket-accept: {expected_accept.lower()}" not in response.lower():
            raise RuntimeError("WebSocket 握手返回了错误的 Sec-WebSocket-Accept。")

    def _read_http_headers(self) -> str:
        data = bytearray()
        while b"\r\n\r\n" not in data:
            chunk = self._socket.recv(4096)
            if not chunk:
                break
            data.extend(chunk)
        return data.decode("utf-8", errors="replace")

    def _send_json(self, payload: dict[str, object]) -> None:
        self._send_frame(json.dumps(payload).encode("utf-8"))

    def _send_frame(self, payload: bytes, opcode: int = 0x1) -> None:
        frame = bytearray()
        frame.append(0x80 | opcode)
        payload_length = len(payload)
        mask_bit = 0x80

        if payload_length < 126:
            frame.append(mask_bit | payload_length)
        elif payload_length < 65536:
            frame.append(mask_bit | 126)
            frame.extend(struct.pack("!H", payload_length))
        else:
            frame.append(mask_bit | 127)
            frame.extend(struct.pack("!Q", payload_length))

        mask = os.urandom(4)
        frame.extend(mask)
        frame.extend(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self._socket.sendall(frame)

    def _receive_json(self) -> dict[str, object]:
        while True:
            opcode, payload = self._read_frame()
            if opcode == 0x1:
                return json.loads(payload.decode("utf-8"))
            if opcode == 0x8:
                raise RuntimeError("DevTools WebSocket 已关闭。")
            if opcode == 0x9:
                self._send_frame(payload, opcode=0xA)

    def _read_frame(self) -> tuple[int, bytes]:
        header = self._read_exact(2)
        first_byte, second_byte = header[0], header[1]
        payload_length = second_byte & 0x7F

        if payload_length == 126:
            payload_length = struct.unpack("!H", self._read_exact(2))[0]
        elif payload_length == 127:
            payload_length = struct.unpack("!Q", self._read_exact(8))[0]

        mask = b""
        if second_byte & 0x80:
            mask = self._read_exact(4)
        payload = self._read_exact(payload_length)

        if mask:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))

        return first_byte & 0x0F, payload

    def _read_exact(self, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = self._socket.recv(size - len(data))
            if not chunk:
                raise RuntimeError("读取 DevTools 数据失败，连接已断开。")
            data.extend(chunk)
        return bytes(data)


def fetch_json(url: str) -> object:
    with urllib.request.urlopen(url, timeout=DEVTOOLS_HTTP_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_devtools_ready(port: int, timeout_seconds: float) -> None:
    deadline = time.time() + timeout_seconds
    version_url = f"http://{DEVTOOLS_HOST}:{port}/json/version"

    while time.time() < deadline:
        try:
            fetch_json(version_url)
            return
        except (TimeoutError, urllib.error.URLError, json.JSONDecodeError):
            time.sleep(DEVTOOLS_POLL_INTERVAL_SECONDS)

    raise TimeoutError("Chrome DevTools 调试端口未在预期时间内就绪。")


def fetch_browser_websocket_url(port: int) -> str:
    version_url = f"http://{DEVTOOLS_HOST}:{port}/json/version"
    payload = fetch_json(version_url)
    if not isinstance(payload, dict):
        raise RuntimeError("Chrome DevTools 返回了非预期的版本信息。")
    websocket_url = payload.get("webSocketDebuggerUrl")
    if not websocket_url:
        raise RuntimeError("没有找到可用的 Chrome browser 调试目标。")
    return str(websocket_url)


def fetch_page_websocket_url(port: int) -> str:
    targets_url = f"http://{DEVTOOLS_HOST}:{port}/json/list"
    targets = fetch_json(targets_url)
    if not isinstance(targets, list):
        raise RuntimeError("Chrome DevTools 返回了非预期的 targets 数据。")

    for target in targets:
        if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
            return str(target["webSocketDebuggerUrl"])

    raise RuntimeError("没有找到可用的 Chrome 页面调试目标。")


def wait_for_target_websocket_url(
    port: int,
    target_id: str,
    timeout_seconds: float = DEVTOOLS_TARGET_DISCOVERY_TIMEOUT_SECONDS,
) -> str:
    deadline = time.time() + timeout_seconds
    targets_url = f"http://{DEVTOOLS_HOST}:{port}/json/list"

    while time.time() < deadline:
        targets = fetch_json(targets_url)
        if isinstance(targets, list):
            for target in targets:
                if (
                    target.get("id") == target_id
                    and target.get("type") == "page"
                    and target.get("webSocketDebuggerUrl")
                ):
                    return str(target["webSocketDebuggerUrl"])
        time.sleep(DEVTOOLS_POLL_INTERVAL_SECONDS)

    raise TimeoutError(f"没有找到目标页调试连接: {target_id}")


def evaluate_javascript(devtools_client: DevToolsClient, expression: str) -> object:
    response = devtools_client.call(
        "Runtime.evaluate",
        {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        },
    )
    if response.get("error"):
        raise RuntimeError(f"执行页面脚本失败: {response['error']}")

    result = response.get("result", {}).get("result", {})
    if result.get("subtype") == "error":
        raise RuntimeError(f"页面脚本执行出错: {result.get('description', '未知错误')}")
    return result.get("value")
