"""Helpers for locating extension source files and entry URLs."""

from __future__ import annotations

import json
from pathlib import Path


def load_json_file(file_path: Path) -> dict[str, object]:
    return json.loads(file_path.read_text(encoding="utf-8"))


def read_extension_settings(profile_dir: Path, extension_id: str) -> dict[str, object]:
    secure_preferences_path = profile_dir / "Default" / "Secure Preferences"
    secure_preferences = load_json_file(secure_preferences_path)
    return (
        secure_preferences.get("extensions", {})
        .get("settings", {})
        .get(extension_id, {})
    )


def read_manifest_from_directory(extension_dir: Path) -> dict[str, object]:
    manifest_path = extension_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"找不到扩展 manifest 文件: {manifest_path}")
    return load_json_file(manifest_path)


def find_unpacked_extension_dir(profile_dir: Path, extension_id: str) -> Path | None:
    extension_settings = read_extension_settings(profile_dir, extension_id)
    extension_path = str(extension_settings.get("path", "")).strip()
    if not extension_path:
        return None

    source_path = Path(extension_path).expanduser()
    if not source_path.is_dir():
        raise FileNotFoundError(f"找不到扩展源码目录: {source_path}")
    read_manifest_from_directory(source_path)
    return source_path


def find_installed_extension_dir(profile_dir: Path, extension_id: str) -> Path | None:
    extension_versions_dir = profile_dir / "Default" / "Extensions" / extension_id
    if not extension_versions_dir.is_dir():
        return None

    version_dirs = sorted(
        (path for path in extension_versions_dir.iterdir() if path.is_dir()),
        key=lambda path: path.name,
        reverse=True,
    )
    for version_dir in version_dirs:
        if (version_dir / "manifest.json").is_file():
            return version_dir
    return None


def read_extension_source_path(profile_dir: Path, extension_id: str) -> Path:
    unpacked_extension_dir = find_unpacked_extension_dir(profile_dir, extension_id)
    if unpacked_extension_dir is not None:
        return unpacked_extension_dir

    installed_extension_dir = find_installed_extension_dir(profile_dir, extension_id)
    if installed_extension_dir is not None:
        return installed_extension_dir

    raise FileNotFoundError(
        "在基准配置中找不到目标扩展安装目录。"
        f"扩展 ID: {extension_id}"
    )


def build_extension_page_url(profile_dir: Path, extension_id: str) -> str:
    extension_source_path = read_extension_source_path(profile_dir, extension_id)
    manifest = read_manifest_from_directory(extension_source_path)
    side_panel = manifest.get("side_panel", {})
    side_panel_path = side_panel.get("default_path") if isinstance(side_panel, dict) else ""
    if not side_panel_path:
        raise RuntimeError("目标扩展没有配置 side_panel.default_path。")
    return f"chrome-extension://{extension_id}/{side_panel_path}"
