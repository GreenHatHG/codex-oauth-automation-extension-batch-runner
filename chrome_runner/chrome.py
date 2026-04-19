"""Chrome process and profile helpers."""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .constants import (
    CHROME_EXECUTABLE,
    CHROME_FLAGS,
    CHROME_NO_STARTUP_WINDOW_FLAG,
    CHROME_SHUTDOWN_TIMEOUT_SECONDS,
    DEVTOOLS_HOST,
    PROCESS_TERMINATION_POLL_SECONDS,
    PROFILE_DELETE_TIMEOUT_SECONDS,
    RUNTIME_PROFILE_PREFIX,
    STALE_LOCK_FILE_NAMES,
    START_PAGE,
)


def ensure_chrome_exists() -> None:
    if CHROME_EXECUTABLE.is_file():
        return
    raise FileNotFoundError(f"找不到 Chrome 可执行文件: {CHROME_EXECUTABLE}")


def create_profile_directory(profile_dir: Path) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)


def build_runtime_profile_dir(base_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dir_name = f"{RUNTIME_PROFILE_PREFIX}-{timestamp}-{os.getpid()}"
    return base_dir / dir_name


def remove_stale_lock_files(profile_dir: Path) -> None:
    for file_name in STALE_LOCK_FILE_NAMES:
        file_path = profile_dir / file_name
        if not file_path.exists() and not file_path.is_symlink():
            continue
        if file_path.is_dir() and not file_path.is_symlink():
            shutil.rmtree(file_path)
            continue
        file_path.unlink()


def copy_profile_directory(source_dir: Path, target_dir: Path) -> None:
    shutil.copytree(source_dir, target_dir)
    remove_stale_lock_files(target_dir)

def build_command(
    profile_dir: Path,
    *,
    start_page: str = START_PAGE,
    remote_debugging_port: int | None = None,
    suppress_startup_window: bool = False,
) -> list[str]:
    command = [
        str(CHROME_EXECUTABLE),
        f"--user-data-dir={profile_dir}",
        *CHROME_FLAGS,
    ]
    if remote_debugging_port is not None:
        command.append(f"--remote-debugging-port={remote_debugging_port}")
    if suppress_startup_window:
        command.append(CHROME_NO_STARTUP_WINDOW_FLAG)
    else:
        command.append(start_page)
    return command


def launch_chrome(
    command: list[str],
) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        command,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_for_chrome_exit(process: subprocess.Popen[bytes]) -> int:
    return process.wait()


def _is_process_group_alive(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False
    return True


def shutdown_chrome_process(
    process: subprocess.Popen[bytes],
    timeout_seconds: float = CHROME_SHUTDOWN_TIMEOUT_SECONDS,
) -> None:
    process_group_id = process.pid
    if not _is_process_group_alive(process_group_id):
        return

    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not _is_process_group_alive(process_group_id):
            if process.poll() is None:
                process.wait(timeout=timeout_seconds)
            return
        time.sleep(PROCESS_TERMINATION_POLL_SECONDS)

    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not _is_process_group_alive(process_group_id):
            break
        time.sleep(PROCESS_TERMINATION_POLL_SECONDS)

    if process.poll() is None:
        process.wait(timeout=timeout_seconds)


def delete_profile_directory(
    profile_dir: Path,
    timeout_seconds: float = PROFILE_DELETE_TIMEOUT_SECONDS,
) -> None:
    if not profile_dir.exists():
        return

    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            shutil.rmtree(profile_dir)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            last_error = exc
            time.sleep(PROCESS_TERMINATION_POLL_SECONDS)

    if last_error is not None:
        raise RuntimeError(f"删除运行目录失败：{last_error}") from last_error


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe_socket:
        probe_socket.bind((DEVTOOLS_HOST, 0))
        return int(probe_socket.getsockname()[1])
