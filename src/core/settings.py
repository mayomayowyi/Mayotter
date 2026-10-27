
from __future__ import annotations
from src.core.i18n import LANGUAGES, tr

import copy
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.core.paths import SETTINGS_FILE, bundled_audio_visual_image

COLUMN_WIDTHS_KEY = "column_widths"
COLUMN_WIDTHS_BY_MODE_KEY = "column_widths_by_mode"
STOWED_COLUMNS_KEY = "stowed_column_ids"
STOW_SAVED_WIDTHS_KEY = "stow_saved_widths"
INDIVIDUALLY_STOWED_COLUMNS_KEY = "individually_stowed_column_ids"
INDIVIDUAL_STOW_WIDTHS_KEY = "individual_stow_widths"
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
PAGE_ZOOM_KEY = "page_zoom_percent"
WHEEL_SCROLL_PERCENT_KEY = "wheel_scroll_percent"
EDGE_DOCK_ALWAYS_ON_TOP_KEY = "edge_dock_always_on_top"
EDGE_DOCK_DISABLE_ON_FULLSCREEN_KEY = "edge_dock_disable_on_fullscreen"
EDGE_DOCK_UNREAD_INDICATOR_KEY = "edge_dock_unread_indicator"
EDGE_DOCK_ENABLED_KEY = "edge_dock_enabled"
EDGE_DOCK_DIRECTION_KEY = "edge_dock_direction"
SYNC_DOCK_COLUMNS_KEY = "sync_dock_columns"

EXTERNAL_SITE_POLICY_KEY = "external_site_policy"
ALLOWED_EXTERNAL_NEW_TAB_KEY = "allowed_external_new_tab"
USER_ALLOWED_EXTERNAL_KEY = "user_allowed_external"
NORMAL_COLUMN_COUNT_KEY = "normal_column_count"
AUTO_NORMALIZE_AUDIO_KEY = "auto_normalize_audio"
SAVE_RECORDED_AUDIO_KEY = "save_recorded_audio"
AUDIO_DENOISE_ENABLED_KEY = "audio_denoise_enabled"
AUDIO_DENOISE_STRENGTH_KEY = "audio_denoise_strength"
SAVE_RECORDED_WAV_KEY = "save_recorded_wav"
RECORDED_AUDIO_DIR_KEY = "recorded_audio_dir"
PREFERRED_MICROPHONE_ID_KEY = "preferred_microphone_id"
PREFERRED_MICROPHONE_NAME_KEY = "preferred_microphone_name"
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
ACCOUNT_MENU_GROUPING_KEY = "account_menu_grouping"
UI_THEME_KEY = "ui_theme"
UI_LANGUAGE_KEY = "ui_language"
SAVED_SEARCHES_KEY = "saved_searches"

# アカウント・認証・全体設定は含めない。旧キーは移行後も原本として残す。
WORKSPACE_KEYS = frozenset({
    COLUMN_WIDTHS_KEY, COLUMN_WIDTHS_BY_MODE_KEY, COLUMNS_KEY, COLUMNS_BY_MODE_KEY, "flip_selected_columns",
    STOWED_COLUMNS_KEY, STOW_SAVED_WIDTHS_KEY, INDIVIDUALLY_STOWED_COLUMNS_KEY,
    INDIVIDUAL_STOW_WIDTHS_KEY, NORMAL_COLUMN_COUNT_KEY, EDGE_DOCK_COLUMN_COUNT_KEY,
    EDGE_DOCK_COLUMN_COUNT_LR_KEY, EDGE_DOCK_COLUMN_COUNT_TB_KEY, "workspace_grok_mode",
})

class SettingsManager:

    #: 初期Work名。旧版の「デフォルト」は起動時に移行する。
    DEFAULT_WORKSPACE_NAME = "Work"

    def __init__(self, settings_path: Path | None = None) -> None:
        self._settings_path = settings_path or SETTINGS_FILE
        self._new_settings_file = not self._settings_path.exists()
        self._cache: dict[str, Any] | None = None
        self._cache_mtime_ns: int | None = None
        self._workspace_preview: str | None = None
        self._batch_data: dict[str, Any] | None = None

    def _disk_mtime_ns(self) -> int | None:
        try:
            return self._settings_path.stat().st_mtime_ns
        except OSError:
            return None

    def _load_raw(self) -> dict[str, Any]:
        """設定のコピーを返す（getter ごとに app.json を読み直さない）。"""
        if self._batch_data is not None:
            return copy.deepcopy(self._batch_data)
        mtime_ns = self._disk_mtime_ns()
        if self._cache is not None and mtime_ns == self._cache_mtime_ns:
            return copy.deepcopy(self._cache)
        if mtime_ns is None:
            self._cache = {}
            self._cache_mtime_ns = None
            return {}
        try:
            with open(self._settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._cache = data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError, UnicodeError):
            self._cache = {}
        self._cache_mtime_ns = self._disk_mtime_ns()
        return copy.deepcopy(self._cache)

    def load(self) -> dict[str, Any]:
        data = self._load_raw()
        if "workspaces" in data:
            workspaces = self._validate_workspaces(data)
            state = workspaces[self._workspace_preview or data["active_workspace_id"]]["state"]
            for key in WORKSPACE_KEYS:
                data.pop(key, None)
            data.update(copy.deepcopy(state))
        return data

    def _default_sync_dock_columns(self, data: dict) -> bool:
        if not self._new_settings_file:
            return False
        states = [data] + [w.get("state", {}) for w in (data.get("workspaces") or {}).values()]
        return not any(
            any(mode in (state.get(COLUMNS_BY_MODE_KEY) or {}) for mode in ("lr", "tb"))
            or any(mode in (state.get(COLUMN_WIDTHS_BY_MODE_KEY) or {}) for mode in ("lr", "tb"))
            or any(key in state for key in (EDGE_DOCK_COLUMN_COUNT_KEY,
                                           EDGE_DOCK_COLUMN_COUNT_LR_KEY, EDGE_DOCK_COLUMN_COUNT_TB_KEY))
            for state in states
        )

    def get_sync_dock_columns(self) -> bool:
        data = self._load_raw()
        return bool(data.get(SYNC_DOCK_COLUMNS_KEY, self._default_sync_dock_columns(data)))

    def get_ui_language(self) -> str:
        language = self._load_raw().get(UI_LANGUAGE_KEY, 'ja')
        return language if language in LANGUAGES else 'ja'

    def save_ui_language(self, language: str) -> None:
        self.save({UI_LANGUAGE_KEY: language if language in LANGUAGES else 'ja'})

    def needs_language_selection(self, profiles_dir: Path) -> bool:
        if not self._new_settings_file or self._load_raw():
            return False
        return not (profiles_dir.exists() and any(profiles_dir.iterdir()))

    def save_sync_dock_columns(self, enabled: bool) -> None:
        self.save({SYNC_DOCK_COLUMNS_KEY: bool(enabled)})

    @staticmethod
    def _sync_dock_column_state(state: dict) -> None:
        modes = state.get(COLUMNS_BY_MODE_KEY) or {}
        normal = modes.get("normal", state.get(COLUMNS_KEY, []))
        if not isinstance(normal, list):
            return
        state[COLUMNS_KEY] = copy.deepcopy(normal)
        state[COLUMNS_BY_MODE_KEY] = {mode: copy.deepcopy(normal) for mode in ("normal", "lr", "tb")}
        widths = (state.get(COLUMN_WIDTHS_BY_MODE_KEY) or {}).get("normal", state.get(COLUMN_WIDTHS_KEY) or {})
        state[COLUMN_WIDTHS_BY_MODE_KEY] = {mode: copy.deepcopy(widths) for mode in ("normal", "lr", "tb")}
        for key in (NORMAL_COLUMN_COUNT_KEY, EDGE_DOCK_COLUMN_COUNT_KEY,
                    EDGE_DOCK_COLUMN_COUNT_LR_KEY, EDGE_DOCK_COLUMN_COUNT_TB_KEY):
            state[key] = len(normal)

    @staticmethod
    def _validate_workspaces(data: dict) -> dict:
        workspaces = data.get("workspaces")
        if (data.get("workspace_schema_version") != 1 or not isinstance(workspaces, dict)
                or not workspaces or data.get("active_workspace_id") not in workspaces):
            raise ValueError(tr('Workの保存形式が不正です。元の設定を確認してください。'))
        for wid, item in workspaces.items():
            if (not isinstance(wid, str) or not isinstance(item, dict)
                    or not isinstance(item.get("name"), str) or not item["name"].strip()
                    or not isinstance(item.get("state"), dict)
                    or not set(item["state"]).issubset(WORKSPACE_KEYS)):
                raise ValueError(tr('Workの保存データが不正です。'))
            state = item["state"]
            if COLUMNS_KEY in state and (not isinstance(state[COLUMNS_KEY], list)
                    or any(not isinstance(c, dict) for c in state[COLUMNS_KEY])):
                raise ValueError(tr('カラムの保存データが不正です。'))
            modes = state.get(COLUMNS_BY_MODE_KEY, {})
            if (not isinstance(modes, dict) or any(
                    not isinstance(cols, list) or any(not isinstance(c, dict) for c in cols)
                    for cols in modes.values())):
                raise ValueError(tr('表示モードの保存データが不正です。'))
        return workspaces

    def initialize_workspaces(self) -> None:
        # load() の破損時既定値では移行しない。読めない原本は一切上書きしない。
        if self._settings_path.exists():
            with self._settings_path.open(encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise TypeError(tr('設定ファイルの形式が不正です。'))
        else:
            data = {}
        if "workspaces" in data:
            self._validate_workspaces(data)
            if self._migrate_default_workspace_name(data):
                self._write_raw(data)
            return
        state = {key: copy.deepcopy(data[key]) for key in WORKSPACE_KEYS if key in data}
        # accounts だけの旧形式に限り、既存の起動時補完と同じ構成を引き継ぐ。
        by_mode = state.get(COLUMNS_BY_MODE_KEY, {})
        if not isinstance(by_mode, dict):
            raise ValueError(tr('表示モードの保存データが不正です。'))
        if COLUMNS_KEY not in state and "normal" not in by_mode:
            state[COLUMNS_KEY] = [
                {"column_id": str(uuid4()), "source_account_id": a["account_id"],
                 "source_url": a.get("initial_url", "https://x.com/"),
                 "title": a.get("display_name", ""), "column_type": "home"}
                for a in data.get(ACCOUNTS_KEY, [])
                if isinstance(a, dict) and a.get("account_id") and a.get("open", True)
            ]
        data.update(workspace_schema_version=1, active_workspace_id="default",
                    workspaces={"default": {"name": tr(self.DEFAULT_WORKSPACE_NAME) if self._new_settings_file else self.DEFAULT_WORKSPACE_NAME, "state": state}})
        self._validate_workspaces(data)
        self._write_raw(data)

    def _migrate_default_workspace_name(self, data: dict) -> bool:
        """旧版の初期名「デフォルト」を「Work」へ移す。ユーザー改名済みは触らない。"""
        try:
            workspaces = data.get("workspaces") or {}
            default = workspaces.get("default")
            if not isinstance(default, dict) or default.get("name") != "デフォルト":
                return False
            if any(wid != "default" and isinstance(item, dict) and item.get("name") == self.DEFAULT_WORKSPACE_NAME
                    for wid, item in workspaces.items()):
                return False
            default["name"] = self.DEFAULT_WORKSPACE_NAME
            return True
        except Exception:
            return False

    def suggest_workspace_name(self, base: str | None = None) -> str:
        """新規ワーク入力欄の初期値。既存名と重ならない最初の候補を返す。"""
        data = self._load_raw()
        try:
            names = {item.get("name") for item in self._validate_workspaces(data).values()}
        except ValueError:
            names = set()
        base = (base or tr(self.DEFAULT_WORKSPACE_NAME)).strip() or tr(self.DEFAULT_WORKSPACE_NAME)
        if base not in names:
            return base
        index = 2
        while f"{base}{index}" in names:
            index += 1
        return f"{base}{index}"

    def get_workspaces(self) -> dict[str, str]:
        data = self._load_raw()
        return {wid: item["name"] for wid, item in self._validate_workspaces(data).items()}

    def initialize_account_menu_groups(self, account_ids: list[str]) -> dict[str, str]:
        data = self._load_raw()
        workspaces = self._validate_workspaces(data)
        saved = data.get("account_menu_groups", {})
        groups = {
            aid: wid if isinstance(wid, str) and wid in workspaces else ""
            for aid, wid in saved.items()
        } if isinstance(saved, dict) else {}
        missing = set(account_ids) - groups.keys()
        for wid, workspace in workspaces.items():
            if not missing:
                break
            state = workspace["state"]
            modes = state.get(COLUMNS_BY_MODE_KEY, {})
            columns = [column for entries in modes.values() for column in entries]
            if "normal" not in modes:
                columns.extend(state.get(COLUMNS_KEY, []))
            for column in columns:
                aid = column.get("source_account_id")
                if isinstance(aid, str) and aid in missing:
                    groups[aid] = wid
                    missing.remove(aid)
        # 空文字も確定済みの分類。次回の起動やカラム変更で再分類しない。
        groups.update({aid: "" for aid in account_ids if aid in missing})
        if groups != saved:
            data["account_menu_groups"] = groups
            self._write_raw(data)
        return groups

    def get_active_workspace_id(self) -> str:
        data = self._load_raw()
        self._validate_workspaces(data)
        return data["active_workspace_id"]

    def reorder_workspaces(self, workspace_ids: list[str]) -> None:
        data = self._load_raw()
        workspaces = self._validate_workspaces(data)
        if len(workspace_ids) != len(workspaces) or set(workspace_ids) != set(workspaces):
            raise ValueError(tr('Workの並び順が不正です。'))
        if workspace_ids == list(workspaces):
            return
        data["workspaces"] = {wid: workspaces[wid] for wid in workspace_ids}
        self._write_raw(data)

    def select_workspace(self, workspace_id: str, *, persist: bool = True) -> None:
        data = self._load_raw()
        if workspace_id not in self._validate_workspaces(data):
            raise ValueError(tr('Workが見つかりません。'))
        if not persist:
            self._workspace_preview = workspace_id
            return
        data["active_workspace_id"] = workspace_id
        self._write_raw(data)
        self._workspace_preview = None

    def cancel_workspace_selection(self) -> None:
        self._workspace_preview = None

    def create_workspace(self, name: str) -> str:
        data = self._load_raw()
        workspaces = self._validate_workspaces(data)
        name = self._workspace_name(name, workspaces)
        wid = uuid4().hex
        workspaces[wid] = {"name": name, "state": {
            COLUMNS_KEY: [], COLUMNS_BY_MODE_KEY: {m: [] for m in ("normal", "lr", "tb")},
            COLUMN_WIDTHS_BY_MODE_KEY: {}, NORMAL_COLUMN_COUNT_KEY: 0,
            EDGE_DOCK_COLUMN_COUNT_LR_KEY: 0, EDGE_DOCK_COLUMN_COUNT_TB_KEY: 0,
        }}
        self._write_raw(data)
        return wid

    @staticmethod
    def _workspace_name(name: str, workspaces: dict, exclude: str = "") -> str:
        name = name.strip()
        if not name or len(name) > 40:
            raise ValueError(tr('Work名は1〜40文字で入力してください。'))
        if any(wid != exclude and w["name"] == name for wid, w in workspaces.items()):
            raise ValueError(tr('同じ名前のWorkがあります。'))
        return name

    def rename_workspace(self, workspace_id: str, name: str) -> None:
        data = self._load_raw()
        workspaces = self._validate_workspaces(data)
        workspaces[workspace_id]["name"] = self._workspace_name(name, workspaces, workspace_id)
        self._write_raw(data)

    def delete_workspace(self, workspace_id: str) -> None:
        data = self._load_raw()
        workspaces = self._validate_workspaces(data)
        if len(workspaces) == 1:
            raise ValueError(tr('最後のWorkは削除できません。'))
        if workspace_id == data["active_workspace_id"]:
            raise ValueError(tr('別のWorkへ切り替えてから削除してください。'))
        del workspaces[workspace_id]
        groups = data.get("account_menu_groups")
        if isinstance(groups, dict):
            data["account_menu_groups"] = {
                aid: "" if wid == workspace_id else wid for aid, wid in groups.items()}
        self._write_raw(data)

    def get_column_widths(self) -> dict[str, int]:
        settings = self.load()
        by_mode = settings.get(COLUMN_WIDTHS_BY_MODE_KEY) or {}
        # 明示的な {} とキー不存在を区別する。[]/{} は有効な保存状態。
        if isinstance(by_mode, dict) and "normal" in by_mode and isinstance(by_mode.get("normal"), dict):
            return dict(by_mode.get("normal") or {})
        return settings.get(COLUMN_WIDTHS_KEY, {}) or {}

    def save_column_widths(self, widths: dict[str, int]) -> None:
        self.save_column_widths_for_mode("normal", widths)

    def get_column_widths_for_mode(self, mode: str) -> dict[str, int]:
        settings = self.load()
        by_mode = settings.get(COLUMN_WIDTHS_BY_MODE_KEY) or {}
        if isinstance(by_mode, dict) and mode in by_mode and isinstance(by_mode.get(mode), dict):
            return dict(by_mode.get(mode) or {})
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

    def get_individually_stowed_state(self) -> dict[str, Any]:
        settings = self.load()
        ids = settings.get(INDIVIDUALLY_STOWED_COLUMNS_KEY) or []
        if not isinstance(ids, list):
            ids = []
        widths = settings.get(INDIVIDUAL_STOW_WIDTHS_KEY) or {}
        if not isinstance(widths, dict):
            widths = {}
        return {
            "column_ids": [str(x) for x in ids if x],
            "widths": {str(k): int(v) for k, v in widths.items() if v},
        }

    def save_individually_stowed_state(self, column_ids: list, widths: dict | None = None) -> None:
        settings = self.load()
        settings[INDIVIDUALLY_STOWED_COLUMNS_KEY] = [str(x) for x in (column_ids or []) if x]
        clean_w = {}
        for k, v in (widths or {}).items():
            try:
                clean_w[str(k)] = int(v)
            except (TypeError, ValueError):
                continue
        settings[INDIVIDUAL_STOW_WIDTHS_KEY] = clean_w
        self.save(settings)

    def save(self, settings: dict[str, Any]) -> None:
        if self._workspace_preview is not None:
            raise RuntimeError(tr('Workの復元中は設定を保存できません。'))
        current = self._load_raw()
        old_sync = bool(current.get(SYNC_DOCK_COLUMNS_KEY, self._default_sync_dock_columns(current)))
        state = current
        if "workspaces" in current:
            workspaces = self._validate_workspaces(current)
            state = workspaces[current["active_workspace_id"]]["state"]
            for key, value in settings.items():
                if key in WORKSPACE_KEYS:
                    state[key] = copy.deepcopy(value)
                elif key not in ("workspaces", "active_workspace_id", "workspace_schema_version"):
                    current[key] = copy.deepcopy(value)
        else:
            current.update(settings)
        sync = bool(current.get(SYNC_DOCK_COLUMNS_KEY, self._default_sync_dock_columns(current)))
        current.setdefault(SYNC_DOCK_COLUMNS_KEY, sync)
        if SYNC_DOCK_COLUMNS_KEY in settings and sync != old_sync:
            # ON 時はメインを正とし、OFF 時も最後の共有状態から独立させる。
            states = [w["state"] for w in current["workspaces"].values()] if "workspaces" in current else [current]
            for workspace_state in states:
                self._sync_dock_column_state(workspace_state)
        elif sync and any(key in WORKSPACE_KEYS for key in settings):
            self._sync_dock_column_state(state)
        previous = self._batch_data if self._batch_data is not None else self._cache
        if current == previous and self._cache_mtime_ns is not None:
            return
        self._write_raw(current)

    @contextmanager
    def batch(self):
        """同期保存を一度にまとめる。失敗時は未確定値を捨て、例外を呼び出し元へ返す。"""
        if self._workspace_preview is not None or self._batch_data is not None:
            raise RuntimeError(tr('設定の復元中・保存中は保存処理を開始できません。'))
        original = self._load_raw()
        self._batch_data = original
        try:
            yield self
            pending = self._batch_data
        finally:
            self._batch_data = None
        if pending != original or self._cache_mtime_ns is None:
            self._write_raw(pending)

    def _write_raw(self, current: dict[str, Any]) -> None:
        current.setdefault(SYNC_DOCK_COLUMNS_KEY, self._default_sync_dock_columns(current))
        if self._batch_data is not None:
            self._batch_data = copy.deepcopy(current)
            return
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        # 途中終了で app.json が壊れるのを避けるため一時ファイルへ書いてから差し替える
        tmp_path = self._settings_path.with_suffix(self._settings_path.suffix + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2, ensure_ascii=False)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_path, self._settings_path)
        self._cache = copy.deepcopy(current)
        self._cache_mtime_ns = self._disk_mtime_ns()

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
        # 明示的な [] とキー不存在を区別する。[] は全削除という有効な保存状態。
        if isinstance(by_mode, dict) and "normal" in by_mode and isinstance(by_mode.get("normal"), list):
            return list(by_mode.get("normal") or [])
        return settings.get(COLUMNS_KEY, []) or []

    def save_columns(self, columns: list[dict[str, Any]]) -> None:
        self.save_columns_for_mode("normal", columns)

    def get_columns_for_mode(self, mode: str) -> list[dict[str, Any]]:
        settings = self.load()
        by_mode = settings.get(COLUMNS_BY_MODE_KEY) or {}
        if isinstance(by_mode, dict) and mode in by_mode and isinstance(by_mode.get(mode), list):
            return list(by_mode.get(mode) or [])
        if mode == "normal":
            return settings.get(COLUMNS_KEY, []) or []
        return []

    def save_columns_for_mode(self, mode: str, columns: list[dict[str, Any]]) -> None:
        if self.get_sync_dock_columns():
            mode = "normal"
        settings = self.load()
        by_mode = settings.get(COLUMNS_BY_MODE_KEY) or {}
        if not isinstance(by_mode, dict):
            by_mode = {}
        by_mode[mode] = list(columns or [])
        settings[COLUMNS_BY_MODE_KEY] = by_mode
        if mode == "normal":
            settings[COLUMNS_KEY] = list(columns or [])
        self.save(settings)

    def save_columns_for_modes(self, modes: dict[str, list[dict[str, Any]]]) -> None:
        """複数 mode の pack を app.json へ 1 回の書き込みで保存する。"""
        if not isinstance(modes, dict) or not modes:
            return
        settings = self.load()
        by_mode = settings.get(COLUMNS_BY_MODE_KEY) or {}
        if not isinstance(by_mode, dict):
            by_mode = {}
        for mode, columns in modes.items():
            if mode not in ("normal", "lr", "tb"):
                continue
            by_mode[mode] = list(columns or [])
            if mode == "normal":
                settings[COLUMNS_KEY] = list(columns or [])
        settings[COLUMNS_BY_MODE_KEY] = by_mode
        self.save(settings)

    def has_columns_for_mode(self, mode: str) -> bool:
        """その mode のカラム保存が存在するかを返す。明示的な [] も True。

        get_* が [] を返すだけでは「未初期化」と「全削除済み」を区別できないため、
        seed 生成すべきか（未初期化のみ）判定するために使う。
        """
        settings = self.load()
        by_mode = settings.get(COLUMNS_BY_MODE_KEY) or {}
        if isinstance(by_mode, dict) and mode in by_mode:
            return True
        if mode == "normal" and COLUMNS_KEY in settings:
            return True
        return False

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
        # 0 は全削除という正当な状態。負値・非数値だけ既定値へ戻す。
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            return 1
        return count

    def get_edge_dock_column_count_lr(self) -> int:
        settings = self.load()
        count = settings.get(EDGE_DOCK_COLUMN_COUNT_LR_KEY, settings.get(EDGE_DOCK_COLUMN_COUNT_KEY, 1))
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            return 1
        return min(count, 8)

    def get_edge_dock_column_count_tb(self) -> int:
        settings = self.load()
        count = settings.get(EDGE_DOCK_COLUMN_COUNT_TB_KEY, 2)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            return 2
        return min(count, 8)

    def get_page_zoom_percent(self) -> int:
        # 旧版のメイン表示は100%。Dock専用の旧値は同期設定へ引き継がない。
        z = self._load_raw().get(PAGE_ZOOM_KEY, 100)
        if not isinstance(z, int) or isinstance(z, bool):
            return 100
        return max(50, min(150, z))

    def get_edge_dock_zoom_percent(self) -> int:
        return self.get_page_zoom_percent()

    def get_wheel_scroll_percent(self) -> int:
        settings = self.load()
        v = settings.get(WHEEL_SCROLL_PERCENT_KEY, 200)
        try:
            v = int(v)
        except (TypeError, ValueError):
            return 200
        if isinstance(v, bool):
            return 200
        return max(50, min(400, v))

    def save_wheel_scroll_percent(self, percent: int) -> None:
        try:
            v = int(percent)
        except (TypeError, ValueError):
            v = 200
        v = max(50, min(400, v))
        self.save({WHEEL_SCROLL_PERCENT_KEY: v})

    def get_edge_dock_always_on_top(self) -> bool:
        settings = self.load()
        if EDGE_DOCK_ALWAYS_ON_TOP_KEY not in settings:
            return True
        return bool(settings.get(EDGE_DOCK_ALWAYS_ON_TOP_KEY, True))

    def get_edge_dock_disable_on_fullscreen(self) -> bool:
        settings = self.load()
        if EDGE_DOCK_DISABLE_ON_FULLSCREEN_KEY not in settings:
            return True
        return bool(settings.get(EDGE_DOCK_DISABLE_ON_FULLSCREEN_KEY, True))

    def get_edge_dock_unread_indicator(self) -> bool:
        settings = self.load()
        if EDGE_DOCK_UNREAD_INDICATOR_KEY not in settings:
            return True
        return bool(settings.get(EDGE_DOCK_UNREAD_INDICATOR_KEY, True))

    def get_edge_dock_enabled(self) -> bool:
        settings = self.load()
        val = settings.get(EDGE_DOCK_ENABLED_KEY, False)
        return bool(val)

    def get_edge_dock_direction(self) -> str:
        settings = self.load()
        direction = settings.get(EDGE_DOCK_DIRECTION_KEY, "right")
        if direction not in ("left", "right", "top", "bottom"):
            return "right"
        return direction

    def get(self, key: str, default: Any = None) -> Any:
        settings = self.load()
        return settings.get(key, default)

    def get_display_mode(self) -> str:
        mode = self.get("display_mode")
        if mode in ("column", "dock", "flip"):
            return mode
        return "dock" if self.get_edge_dock_enabled() else "column"

    def save_display_mode(self, mode: str) -> None:
        if mode not in ("column", "dock", "flip"):
            raise ValueError(mode)
        self.save({"display_mode": mode, EDGE_DOCK_ENABLED_KEY: mode == "dock"})

    def get_flip_column(self, grok: bool = False) -> str:
        selected = self.get("flip_selected_columns", {})
        return str(selected.get("grok" if grok else "x", "")) if isinstance(selected, dict) else ""

    def save_flip_column(self, column_id: str, grok: bool = False) -> None:
        if self.get_flip_column(grok) == column_id:
            return
        selected = self.get("flip_selected_columns", {})
        selected = dict(selected) if isinstance(selected, dict) else {}
        selected["grok" if grok else "x"] = column_id
        self.save({"flip_selected_columns": selected})

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
        return max(0, count)

    def get_saved_searches(self) -> list[dict[str, str]]:
        """保存した検索条件 [{"name", "query"}]。壊れた項目は読み飛ばす。"""
        raw = self.load().get(SAVED_SEARCHES_KEY)
        out: list[dict[str, str]] = []
        if not isinstance(raw, list):
            return out
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            query = str(item.get("query") or "").strip()
            if name and query:
                out.append({"name": name, "query": query})
        return out

    def save_saved_searches(self, searches: list[dict[str, str]]) -> None:
        clean = []
        seen = set()
        for item in searches or []:
            name = str((item or {}).get("name") or "").strip()
            query = str((item or {}).get("query") or "").strip()
            if name and query and name not in seen:
                seen.add(name)
                clean.append({"name": name, "query": query})
        self.save({SAVED_SEARCHES_KEY: clean})

    def get_ui_theme(self) -> str:
        settings = self.load()
        theme = str(settings.get(UI_THEME_KEY, "dark") or "dark").strip().lower()
        return theme if theme in ("dark", "nadeshiko", "baby_blue", "bordeaux", "pure_purple", "grape_purple") else "dark"

    def save_ui_theme(self, theme: str) -> None:
        value = str(theme or "dark").strip().lower()
        if value not in ("dark", "nadeshiko", "baby_blue", "bordeaux", "pure_purple", "grape_purple"):
            value = "dark"
        settings = self.load()
        settings[UI_THEME_KEY] = value
        self.save(settings)

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

    def get_audio_denoise_enabled(self) -> bool:
        """音声投稿の AI ノイズキャンセリング（DeepFilterNet3）。既定 ON（OFF の間はモデルを読み込まない）。"""
        return bool(self.load().get(AUDIO_DENOISE_ENABLED_KEY, True))

    def save_audio_denoise_enabled(self, enabled: bool) -> None:
        self.save({AUDIO_DENOISE_ENABLED_KEY: bool(enabled)})

    def get_save_recorded_wav(self) -> bool:
        return bool(self.load().get(SAVE_RECORDED_WAV_KEY, True))

    def save_save_recorded_wav(self, enabled: bool) -> None:
        self.save({SAVE_RECORDED_WAV_KEY: bool(enabled)})

    def get_audio_denoise_strength(self) -> str:
        value = str(self.load().get(AUDIO_DENOISE_STRENGTH_KEY, "standard") or "standard")
        return value if value in ("weak", "standard", "strong") else "standard"

    def save_audio_denoise_strength(self, strength: str) -> None:
        value = str(strength or "standard")
        self.save({AUDIO_DENOISE_STRENGTH_KEY: value if value in ("weak", "standard", "strong")
                   else "standard"})

    def get_preferred_microphone(self) -> tuple[str, str]:
        """(デバイスID, 表示名)。IDが空なら Windows の既定。表示名は未接続時の表示用で識別には使わない。"""
        settings = self.load()
        return (
            str(settings.get(PREFERRED_MICROPHONE_ID_KEY, "") or ""),
            str(settings.get(PREFERRED_MICROPHONE_NAME_KEY, "") or ""),
        )

    def save_preferred_microphone(self, device_id: str, name: str = "") -> None:
        self.save({
            PREFERRED_MICROPHONE_ID_KEY: str(device_id or ""),
            PREFERRED_MICROPHONE_NAME_KEY: str(name or "") if device_id else "",
        })

    def get_recorded_audio_dir(self) -> str:
        settings = self.load()
        return str(settings.get(RECORDED_AUDIO_DIR_KEY, "") or "").strip()

    def save_recorded_audio_dir(self, path: str) -> None:
        self.save({RECORDED_AUDIO_DIR_KEY: str(path or "").strip()})

    def get_audio_visual_image(self) -> str:
        settings = self.load()
        if AUDIO_VISUAL_IMAGE_KEY not in settings:
            # 未選択の初回起動だけ同梱画像を初期画像にする。利用者が消した後は空のまま。
            bundled = bundled_audio_visual_image()
            return str(bundled) if bundled.is_file() else ""
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

    def get_disable_x_keyboard_shortcuts(self) -> bool:
        settings = self.load()
        if DISABLE_X_KEYBOARD_SHORTCUTS_KEY not in settings:
            return True
        return bool(settings.get(DISABLE_X_KEYBOARD_SHORTCUTS_KEY))

    def get_account_menu_grouping(self) -> bool:
        settings = self.load()
        if ACCOUNT_MENU_GROUPING_KEY not in settings:
            return True
        return bool(settings.get(ACCOUNT_MENU_GROUPING_KEY))

    def save_disable_x_keyboard_shortcuts(self, enabled: bool) -> None:
        settings = self.load()
        settings[DISABLE_X_KEYBOARD_SHORTCUTS_KEY] = bool(enabled)
        self.save(settings)
