
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.core.paths import SETTINGS_FILE

COLUMN_WIDTHS_KEY = "column_widths"
COLUMN_WIDTHS_BY_MODE_KEY = "column_widths_by_mode"
STOWED_COLUMNS_KEY = "stowed_column_ids"
STOW_SAVED_WIDTHS_KEY = "stow_saved_widths"
WINDOW_GEOMETRY_KEY = "window_geometry"
WINDOW_GEOMETRY_NORMAL_KEY = "window_geometry_normal"
WINDOW_GEOMETRY_DOCK_KEY = "window_geometry_dock"
ACCOUNTS_KEY = "accounts"
COLUMNS_KEY = "columns"
COLUMNS_BY_MODE_KEY = "columns_by_mode"
DOWNLOAD_HISTORY_KEY = "download_history"
EDGE_DOCK_COLUMN_COUNT_KEY = "edge_dock_column_count"
EDGE_DOCK_COLUMN_COUNT_LR_KEY = "edge_dock_column_count_lr"
EDGE_DOCK_COLUMN_COUNT_TB_KEY = "edge_dock_column_count_tb"
EDGE_DOCK_ZOOM_KEY = "edge_dock_zoom_percent"
EDGE_DOCK_ALWAYS_ON_TOP_KEY = "edge_dock_always_on_top"
EDGE_DOCK_DISABLE_ON_FULLSCREEN_KEY = "edge_dock_disable_on_fullscreen"
EDGE_DOCK_UNREAD_INDICATOR_KEY = "edge_dock_unread_indicator"
EDGE_DOCK_ENABLED_KEY = "edge_dock_enabled"
EDGE_DOCK_DIRECTION_KEY = "edge_dock_direction"
EDGE_DOCK_WIDTH_LR_KEY = "edge_dock_width_lr"
EDGE_DOCK_HEIGHT_LR_KEY = "edge_dock_height_lr"
EDGE_DOCK_WIDTH_TB_KEY = "edge_dock_width_tb"
EDGE_DOCK_HEIGHT_TB_KEY = "edge_dock_height_tb"
EDGE_DOCK_PANEL_HEIGHT_RATIO_KEY = "edge_dock_panel_height_ratio"
EDGE_DOCK_EDGE_OFFSET_KEY = "edge_dock_edge_offset"
EDGE_DOCK_MONITOR_INDEX_KEY = "edge_dock_monitor_index"

EXTERNAL_SITE_POLICY_KEY = "external_site_policy"
ALLOWED_EXTERNAL_NEW_TAB_KEY = "allowed_external_new_tab"
USER_ALLOWED_EXTERNAL_KEY = "user_allowed_external"
NORMAL_COLUMN_COUNT_KEY = "normal_column_count"
AUTO_NORMALIZE_AUDIO_KEY = "auto_normalize_audio"
SAVE_RECORDED_AUDIO_KEY = "save_recorded_audio"
RECORDED_AUDIO_DIR_KEY = "recorded_audio_dir"
DOWNLOAD_DIR_KEY = "download_dir"
AUDIO_VISUAL_IMAGE_KEY = "audio_visual_image"
AUDIO_VISUAL_IMAGE_CROP_X_KEY = "audio_visual_image_crop_x"
AUDIO_VISUAL_IMAGE_CROP_Y_KEY = "audio_visual_image_crop_y"
AUDIO_VISUAL_IMAGE_SCALE_KEY = "audio_visual_image_scale"
AUDIO_VISUAL_IMAGE_ROTATION_KEY = "audio_visual_image_rotation"
AUDIO_VISUAL_IMAGE_ORIGINAL_KEY = "audio_visual_image_original"
SAVE_CROPPED_VISUAL_IMAGE_KEY = "save_cropped_visual_image"
CROPPED_VISUAL_DIR_KEY = "cropped_visual_dir"
AUTO_CHECK_UPDATES_KEY = "auto_check_updates"
GITHUB_REPO_KEY = "github_repo"
DISABLE_X_KEYBOARD_SHORTCUTS_KEY = "disable_x_keyboard_shortcuts"

class SettingsManager:

    def __init__(self, settings_path: Path | None = None) -> None:
        self._settings_path = settings_path or SETTINGS_FILE

    def load(self) -> dict[str, Any]:
        if not self._settings_path.exists():
            return {}
        with open(self._settings_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_column_widths(self) -> dict[str, int]:
        settings = self.load()
        by_mode = settings.get(COLUMN_WIDTHS_BY_MODE_KEY) or {}
        if isinstance(by_mode, dict) and by_mode.get("normal"):
            return dict(by_mode.get("normal") or {})
        return settings.get(COLUMN_WIDTHS_KEY, {}) or {}

    def save_column_widths(self, widths: dict[str, int]) -> None:
        self.save_column_widths_for_mode("normal", widths)

    def get_column_widths_for_mode(self, mode: str) -> dict[str, int]:
        settings = self.load()
        by_mode = settings.get(COLUMN_WIDTHS_BY_MODE_KEY) or {}
        if isinstance(by_mode, dict) and mode in by_mode and by_mode[mode]:
            return dict(by_mode[mode] or {})
        if mode == "normal":
            return settings.get(COLUMN_WIDTHS_KEY, {}) or {}
        return {}

    def save_column_widths_for_mode(self, mode: str, widths: dict[str, int]) -> None:
        settings = self.load()
        by_mode = settings.get(COLUMN_WIDTHS_BY_MODE_KEY) or {}
        if not isinstance(by_mode, dict):
            by_mode = {}
        by_mode[mode] = dict(widths or {})
        settings[COLUMN_WIDTHS_BY_MODE_KEY] = by_mode
        if mode == "normal":
            settings[COLUMN_WIDTHS_KEY] = dict(widths or {})
        self.save(settings)

    def get_stowed_state(self) -> dict[str, Any]:
        settings = self.load()
        ids = settings.get(STOWED_COLUMNS_KEY) or []
        if not isinstance(ids, list):
            ids = []
        widths = settings.get(STOW_SAVED_WIDTHS_KEY) or {}
        if not isinstance(widths, dict):
            widths = {}
        return {
            "column_ids": [str(x) for x in ids if x],
            "widths": {str(k): int(v) for k, v in widths.items() if v},
        }

    def save_stowed_state(self, column_ids: list, widths: dict) -> None:
        settings = self.load()
        settings[STOWED_COLUMNS_KEY] = [str(x) for x in (column_ids or []) if x]
        clean_w = {}
        for k, v in (widths or {}).items():
            try:
                clean_w[str(k)] = int(v)
            except (TypeError, ValueError):
                continue
        settings[STOW_SAVED_WIDTHS_KEY] = clean_w
        self.save(settings)

    def clear_stowed_state(self) -> None:
        settings = self.load()
        settings[STOWED_COLUMNS_KEY] = []
        settings[STOW_SAVED_WIDTHS_KEY] = {}
        self.save(settings)

    def save(self, settings: dict[str, Any]) -> None:
        current = self.load()
        current.update(settings)
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._settings_path, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2, ensure_ascii=False)

    def get_window_geometry(self) -> bytes | None:
        settings = self.load()
        geometry_data = settings.get(WINDOW_GEOMETRY_KEY)
        if geometry_data:
            return bytes.fromhex(geometry_data)
        return None

    def save_window_geometry(self, geometry) -> None:
        if geometry:
            geometry_hex = bytes(geometry).hex()
            self.save({
                WINDOW_GEOMETRY_KEY: geometry_hex,
                WINDOW_GEOMETRY_NORMAL_KEY: geometry_hex,
            })

    def get_window_geometry_normal(self) -> bytes | None:
        settings = self.load()
        data = settings.get(WINDOW_GEOMETRY_NORMAL_KEY) or settings.get(WINDOW_GEOMETRY_KEY)
        if data:
            return bytes.fromhex(data)
        return None

    def save_window_geometry_normal(self, geometry) -> None:
        if geometry:
            geometry_hex = bytes(geometry).hex()
            self.save({
                WINDOW_GEOMETRY_NORMAL_KEY: geometry_hex,
                WINDOW_GEOMETRY_KEY: geometry_hex,
            })

    def get_window_geometry_dock(self) -> bytes | None:
        settings = self.load()
        data = settings.get(WINDOW_GEOMETRY_DOCK_KEY)
        if data:
            return bytes.fromhex(data)
        return None

    def save_window_geometry_dock(self, geometry) -> None:
        if geometry:
            self.save({WINDOW_GEOMETRY_DOCK_KEY: bytes(geometry).hex()})

    def get_accounts(self) -> list[dict[str, Any]]:
        settings = self.load()
        return settings.get(ACCOUNTS_KEY, [])

    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        settings = self.load()
        settings[ACCOUNTS_KEY] = accounts
        self.save(settings)

    def get_columns(self) -> list[dict[str, Any]]:
        settings = self.load()
        by_mode = settings.get(COLUMNS_BY_MODE_KEY) or {}
        if isinstance(by_mode, dict) and by_mode.get("normal"):
            return list(by_mode.get("normal") or [])
        return settings.get(COLUMNS_KEY, []) or []

    def save_columns(self, columns: list[dict[str, Any]]) -> None:
        self.save_columns_for_mode("normal", columns)

    def get_columns_for_mode(self, mode: str) -> list[dict[str, Any]]:
        settings = self.load()
        by_mode = settings.get(COLUMNS_BY_MODE_KEY) or {}
        if isinstance(by_mode, dict) and mode in by_mode and by_mode[mode]:
            return list(by_mode[mode] or [])
        if mode == "normal":
            return settings.get(COLUMNS_KEY, []) or []
        return []

    def save_columns_for_mode(self, mode: str, columns: list[dict[str, Any]]) -> None:
        settings = self.load()
        by_mode = settings.get(COLUMNS_BY_MODE_KEY) or {}
        if not isinstance(by_mode, dict):
            by_mode = {}
        by_mode[mode] = list(columns or [])
        settings[COLUMNS_BY_MODE_KEY] = by_mode
        if mode == "normal":
            settings[COLUMNS_KEY] = list(columns or [])
        self.save(settings)

    def get_download_history(self) -> list[dict[str, Any]]:
        settings = self.load()
        return settings.get(DOWNLOAD_HISTORY_KEY, [])

    def save_download_history(self, history: list[dict[str, Any]]) -> None:
        settings = self.load()
        settings[DOWNLOAD_HISTORY_KEY] = history
        self.save(settings)

    def get_edge_dock_column_count(self) -> int:
        settings = self.load()
        count = settings.get(EDGE_DOCK_COLUMN_COUNT_KEY, 1)
        if not isinstance(count, int) or count < 1:
            return 1
        return count

    def save_edge_dock_column_count(self, count: int) -> None:
        if not isinstance(count, int) or count < 1:
            count = 1
        self.save({EDGE_DOCK_COLUMN_COUNT_KEY: count})

    def get_edge_dock_column_count_lr(self) -> int:
        settings = self.load()
        count = settings.get(EDGE_DOCK_COLUMN_COUNT_LR_KEY, settings.get(EDGE_DOCK_COLUMN_COUNT_KEY, 1))
        if not isinstance(count, int) or count < 1:
            return 1
        return min(count, 8)

    def save_edge_dock_column_count_lr(self, count: int) -> None:
        if not isinstance(count, int) or count < 1:
            count = 1
        self.save({EDGE_DOCK_COLUMN_COUNT_LR_KEY: count})

    def get_edge_dock_column_count_tb(self) -> int:
        settings = self.load()
        count = settings.get(EDGE_DOCK_COLUMN_COUNT_TB_KEY, 2)
        if not isinstance(count, int) or count < 1:
            return 2
        return min(count, 8)

    def save_edge_dock_column_count_tb(self, count: int) -> None:
        if not isinstance(count, int) or count < 1:
            count = 2
        self.save({EDGE_DOCK_COLUMN_COUNT_TB_KEY: count})

    def get_edge_dock_zoom_percent(self) -> int:
        settings = self.load()
        z = settings.get(EDGE_DOCK_ZOOM_KEY, 90)
        if not isinstance(z, int):
            return 90
        return max(50, min(150, z))

    def save_edge_dock_zoom_percent(self, percent: int) -> None:
        percent = max(50, min(150, int(percent)))
        percent = int(round(percent / 5) * 5)
        self.save({EDGE_DOCK_ZOOM_KEY: percent})

    def get_edge_dock_always_on_top(self) -> bool:
        settings = self.load()
        if EDGE_DOCK_ALWAYS_ON_TOP_KEY not in settings:
            return True
        return bool(settings.get(EDGE_DOCK_ALWAYS_ON_TOP_KEY, True))

    def save_edge_dock_always_on_top(self, enabled: bool) -> None:
        self.save({EDGE_DOCK_ALWAYS_ON_TOP_KEY: bool(enabled)})

    def get_edge_dock_disable_on_fullscreen(self) -> bool:
        settings = self.load()
        if EDGE_DOCK_DISABLE_ON_FULLSCREEN_KEY not in settings:
            return True
        return bool(settings.get(EDGE_DOCK_DISABLE_ON_FULLSCREEN_KEY, True))

    def save_edge_dock_disable_on_fullscreen(self, enabled: bool) -> None:
        self.save({EDGE_DOCK_DISABLE_ON_FULLSCREEN_KEY: bool(enabled)})

    def get_edge_dock_unread_indicator(self) -> bool:
        settings = self.load()
        if EDGE_DOCK_UNREAD_INDICATOR_KEY not in settings:
            return True
        return bool(settings.get(EDGE_DOCK_UNREAD_INDICATOR_KEY, True))

    def save_edge_dock_unread_indicator(self, enabled: bool) -> None:
        self.save({EDGE_DOCK_UNREAD_INDICATOR_KEY: bool(enabled)})

    def get_edge_dock_enabled(self) -> bool:
        settings = self.load()
        val = settings.get(EDGE_DOCK_ENABLED_KEY, False)
        return bool(val)

    def save_edge_dock_enabled(self, enabled: bool) -> None:
        self.save({EDGE_DOCK_ENABLED_KEY: bool(enabled)})

    def get_edge_dock_direction(self) -> str:
        settings = self.load()
        direction = settings.get(EDGE_DOCK_DIRECTION_KEY, "right")
        if direction not in ("left", "right", "top", "bottom"):
            return "right"
        return direction

    def save_edge_dock_direction(self, direction: str) -> None:
        if direction not in ("left", "right", "top", "bottom"):
            direction = "right"
        self.save({EDGE_DOCK_DIRECTION_KEY: direction})

    def get(self, key: str, default: Any = None) -> Any:
        settings = self.load()
        return settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        settings = self.load()
        settings[key] = value
        self.save(settings)

    def get_external_site_policy(self) -> str:
        from src.browser.url_policy import (
            DEFAULT_EXTERNAL_SITE_POLICY,
            POLICY_VALUES,
        )
        settings = self.load()
        val = settings.get(EXTERNAL_SITE_POLICY_KEY, DEFAULT_EXTERNAL_SITE_POLICY)
        if val not in POLICY_VALUES:
            return DEFAULT_EXTERNAL_SITE_POLICY
        return val

    def save_external_site_policy(self, policy: str) -> None:
        from src.browser.url_policy import (
            DEFAULT_EXTERNAL_SITE_POLICY,
            POLICY_VALUES,
        )
        if policy not in POLICY_VALUES:
            policy = DEFAULT_EXTERNAL_SITE_POLICY
        self.save({EXTERNAL_SITE_POLICY_KEY: policy})

    def get_allowed_external_new_tab(self) -> bool:
        settings = self.load()
        if ALLOWED_EXTERNAL_NEW_TAB_KEY not in settings:
            return True
        return bool(settings.get(ALLOWED_EXTERNAL_NEW_TAB_KEY, True))

    def save_allowed_external_new_tab(self, enabled: bool) -> None:
        self.save({ALLOWED_EXTERNAL_NEW_TAB_KEY: bool(enabled)})

    def get_user_allowed_external(self) -> list[dict]:
        settings = self.load()
        raw = settings.get(USER_ALLOWED_EXTERNAL_KEY, [])
        if not isinstance(raw, list):
            return []
        out: list[dict] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            domain = str(item.get("domain") or "").strip().lower()
            if not domain:
                continue
            name = str(item.get("name") or domain).strip() or domain
            out.append({"name": name, "domain": domain})
        return out

    def save_user_allowed_external(self, entries: list) -> None:
        cleaned: list[dict] = []
        seen: set[str] = set()
        for item in entries or []:
            if not isinstance(item, dict):
                continue
            domain = str(item.get("domain") or "").strip().lower()
            if not domain or domain in seen:
                continue
            seen.add(domain)
            name = str(item.get("name") or domain).strip() or domain
            cleaned.append({"name": name, "domain": domain})
        self.save({USER_ALLOWED_EXTERNAL_KEY: cleaned})

    def get_normal_column_count(self) -> int:
        settings = self.load()
        count = settings.get(NORMAL_COLUMN_COUNT_KEY, 2)
        try:
            count = int(count)
        except (TypeError, ValueError):
            count = 2
        return max(1, count)

    def save_normal_column_count(self, count: int) -> None:
        self.save({NORMAL_COLUMN_COUNT_KEY: max(1, int(count))})

    def get_auto_normalize_audio(self) -> bool:
        settings = self.load()
        if AUTO_NORMALIZE_AUDIO_KEY not in settings:
            return True
        return bool(settings.get(AUTO_NORMALIZE_AUDIO_KEY, True))

    def save_auto_normalize_audio(self, enabled: bool) -> None:
        self.save({AUTO_NORMALIZE_AUDIO_KEY: bool(enabled)})

    def get_save_recorded_audio(self) -> bool:
        settings = self.load()
        if SAVE_RECORDED_AUDIO_KEY not in settings:
            return True
        return bool(settings.get(SAVE_RECORDED_AUDIO_KEY, True))

    def save_save_recorded_audio(self, enabled: bool) -> None:
        self.save({SAVE_RECORDED_AUDIO_KEY: bool(enabled)})

    def get_recorded_audio_dir(self) -> str:
        settings = self.load()
        return str(settings.get(RECORDED_AUDIO_DIR_KEY, "") or "").strip()

    def save_recorded_audio_dir(self, path: str) -> None:
        self.save({RECORDED_AUDIO_DIR_KEY: str(path or "").strip()})

    def get_audio_visual_image(self) -> str:
        settings = self.load()
        return str(settings.get(AUDIO_VISUAL_IMAGE_KEY, "") or "").strip()

    def save_audio_visual_image(self, path: str) -> None:
        self.save({AUDIO_VISUAL_IMAGE_KEY: str(path or "").strip()})

    def get_audio_visual_image_crop(self) -> tuple[float, float]:
        settings = self.load()
        try:
            x = float(settings.get(AUDIO_VISUAL_IMAGE_CROP_X_KEY, 0.0) or 0.0)
        except Exception:
            x = 0.0
        try:
            y = float(settings.get(AUDIO_VISUAL_IMAGE_CROP_Y_KEY, 0.0) or 0.0)
        except Exception:
            y = 0.0
        return (max(-1.0, min(1.0, x)), max(-1.0, min(1.0, y)))

    def save_audio_visual_image_crop(self, x: float, y: float) -> None:
        try:
            x = max(-1.0, min(1.0, float(x)))
        except Exception:
            x = 0.0
        try:
            y = max(-1.0, min(1.0, float(y)))
        except Exception:
            y = 0.0
        self.save({AUDIO_VISUAL_IMAGE_CROP_X_KEY: x, AUDIO_VISUAL_IMAGE_CROP_Y_KEY: y})

    def get_audio_visual_image_transform(self) -> tuple[float, float, float, float]:
        cx, cy = self.get_audio_visual_image_crop()
        settings = self.load()
        try:
            scale = float(settings.get(AUDIO_VISUAL_IMAGE_SCALE_KEY, 1.0) or 1.0)
        except Exception:
            scale = 1.0
        try:
            rot = float(settings.get(AUDIO_VISUAL_IMAGE_ROTATION_KEY, 0.0) or 0.0)
        except Exception:
            rot = 0.0
        scale = max(1.0, min(8.0, scale))
        return (cx, cy, scale, rot)

    def save_audio_visual_image_transform(
        self, crop_x: float, crop_y: float, scale: float = 1.0, rotation: float = 0.0
    ) -> None:
        try:
            crop_x = max(-1.0, min(1.0, float(crop_x)))
        except Exception:
            crop_x = 0.0
        try:
            crop_y = max(-1.0, min(1.0, float(crop_y)))
        except Exception:
            crop_y = 0.0
        try:
            scale = max(1.0, min(8.0, float(scale)))
        except Exception:
            scale = 1.0
        try:
            rotation = float(rotation) % 360.0
        except Exception:
            rotation = 0.0
        self.save({
            AUDIO_VISUAL_IMAGE_CROP_X_KEY: crop_x,
            AUDIO_VISUAL_IMAGE_CROP_Y_KEY: crop_y,
            AUDIO_VISUAL_IMAGE_SCALE_KEY: scale,
            AUDIO_VISUAL_IMAGE_ROTATION_KEY: rotation,
        })

    def get_audio_visual_image_original(self) -> str:
        settings = self.load()
        return str(settings.get(AUDIO_VISUAL_IMAGE_ORIGINAL_KEY, "") or "").strip()

    def save_audio_visual_image_original(self, path: str) -> None:
        self.save({AUDIO_VISUAL_IMAGE_ORIGINAL_KEY: str(path or "").strip()})

    def get_save_cropped_visual_image(self) -> bool:
        settings = self.load()
        return bool(settings.get(SAVE_CROPPED_VISUAL_IMAGE_KEY, False))

    def save_save_cropped_visual_image(self, enabled: bool) -> None:
        self.save({SAVE_CROPPED_VISUAL_IMAGE_KEY: bool(enabled)})

    def get_cropped_visual_dir(self) -> str:
        settings = self.load()
        val = str(settings.get(CROPPED_VISUAL_DIR_KEY, "") or "").strip()
        if val:
            return val
        try:
            from src.core.paths import default_audio_visual_dir
            return str(default_audio_visual_dir())
        except Exception:
            return ""

    def save_cropped_visual_dir(self, path: str) -> None:
        self.save({CROPPED_VISUAL_DIR_KEY: str(path or "").strip()})

    def get_download_dir(self) -> str:
        settings = self.load()
        return str(settings.get(DOWNLOAD_DIR_KEY, "") or "")

    def save_download_dir(self, path: str) -> None:
        self.save({DOWNLOAD_DIR_KEY: str(path or "").strip()})

    def get_auto_check_updates(self) -> bool:
        settings = self.load()
        return bool(settings.get(AUTO_CHECK_UPDATES_KEY, False))

    def save_auto_check_updates(self, enabled: bool) -> None:
        self.save({AUTO_CHECK_UPDATES_KEY: bool(enabled)})

    def get_github_repo(self) -> str:
        settings = self.load()
        return str(settings.get(GITHUB_REPO_KEY, "") or "").strip()

    def save_github_repo(self, repo: str) -> None:
        self.save({GITHUB_REPO_KEY: str(repo or "").strip()})

    def get_disable_x_keyboard_shortcuts(self) -> bool:
        settings = self.load()
        if DISABLE_X_KEYBOARD_SHORTCUTS_KEY not in settings:
            return True
        return bool(settings.get(DISABLE_X_KEYBOARD_SHORTCUTS_KEY))

    def save_disable_x_keyboard_shortcuts(self, enabled: bool) -> None:
        settings = self.load()
        settings[DISABLE_X_KEYBOARD_SHORTCUTS_KEY] = bool(enabled)
        self.save(settings)

