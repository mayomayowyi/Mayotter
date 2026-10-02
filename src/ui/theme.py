

from __future__ import annotations

THEME_DARK = "dark"
THEME_NADESHIKO = "nadeshiko"
THEME_BABY_BLUE = "baby_blue"
THEME_BORDEAUX = "bordeaux"
THEME_PURE_PURPLE = "pure_purple"

# 暗い背景のテーマ（DWMのダークモード指定などに使う）
_DARK_THEMES = (THEME_DARK, THEME_BORDEAUX, THEME_PURE_PURPLE)

_THEMES = {
    THEME_DARK: {
        "BG": "#0f1117",
        "WEB_BG": "#0b111f",
        "SURFACE": "#181c26",
        "SURFACE_RAISED": "#1d2230",
        "SURFACE_HOVER": "#232a38",
        "SURFACE_SUNKEN": "#141820",
        "BORDER": "#2b3242",
        "BORDER_STRONG": "#394255",
        "BORDER_ACCENT": "#3d6aa8",
        "TEXT": "#f1f3f7",
        "TEXT_BRIGHT": "#eaf1fb",
        "TEXT_SECONDARY": "#aeb6c5",
        "TEXT_MUTED": "#7f899a",
        "ICON": "#93a5c4",
        "ACCENT": "#4a7ec7",
        "ACCENT_STRONG": "#5b8fd6",
        "ACCENT_SOFT": "#9fb4d8",
        "SUCCESS": "#7dbe96",
        "DANGER": "#e66464",
        "DANGER_BG": "#3d1a1a",
        "DANGER_BORDER": "#5d2a2a",
        "SCROLL_HANDLE": "#3d4a5e",
        "SCROLL_HANDLE_HOVER": "#5a6b84",
        "TRANSITION_BG": "#0b111f",
        "TRANSITION_FG": "#e7e9ed",
        "TRANSITION_FLARE": "#84ccff",
    },
    THEME_NADESHIKO: {
        # Milky Pink: #ffeaf4 をベースにした明るいミルキーピンク。
        # 文字・アイコンは暗い葡萄色で可読性を確保する。
        "BG": "#ffeaf4",
        "WEB_BG": "#ffeaf4",
        "SURFACE": "#fff5fa",
        "SURFACE_RAISED": "#fffafd",
        "SURFACE_HOVER": "#f8dce9",
        "SURFACE_SUNKEN": "#f5cfe0",
        "BORDER": "#e9bdd0",
        "BORDER_STRONG": "#d58eac",
        "BORDER_ACCENT": "#c96f98",
        "TEXT": "#4b303d",
        "TEXT_BRIGHT": "#2f1c26",
        "TEXT_SECONDARY": "#765361",
        "TEXT_MUTED": "#987684",
        "ICON": "#6a4857",
        "ACCENT": "#d77fa6",
        "ACCENT_STRONG": "#c96593",
        "ACCENT_SOFT": "#efb6cf",
        "SUCCESS": "#7d6a73",
        "DANGER": "#b94b72",
        "DANGER_BG": "#ffe0ea",
        "DANGER_BORDER": "#e89ab6",
        "SCROLL_HANDLE": "#d998b4",
        "SCROLL_HANDLE_HOVER": "#c5759a",
        "TRANSITION_BG": "#ffeaf4",
        "TRANSITION_FG": "#4a2d3a",
        "TRANSITION_FLARE": "#e68eb5",
    },
    THEME_BABY_BLUE: {
        # Baby Blue: #eaf4ff を基準にした白に近い淡い水色（天使界隈）。
        # 文字・アイコンは青灰色で可読性を確保し、アクセントは控えめな水色にする。
        "BG": "#eaf4ff",
        "WEB_BG": "#eaf4ff",
        "SURFACE": "#f5faff",
        "SURFACE_RAISED": "#fbfdff",
        "SURFACE_HOVER": "#dcebfb",
        "SURFACE_SUNKEN": "#d3e5f8",
        "BORDER": "#bcd3ec",
        "BORDER_STRONG": "#88abd0",
        "BORDER_ACCENT": "#6f9bc9",
        "TEXT": "#2e4257",
        "TEXT_BRIGHT": "#1d2d3f",
        "TEXT_SECONDARY": "#516a82",
        "TEXT_MUTED": "#6d859f",
        "ICON": "#48627c",
        "ACCENT": "#6fa3d8",
        "ACCENT_STRONG": "#4f8ccb",
        "ACCENT_SOFT": "#a9cdee",
        "SUCCESS": "#5e7f95",
        "DANGER": "#c0566e",
        "DANGER_BG": "#ffe3ea",
        "DANGER_BORDER": "#eba0b4",
        "SCROLL_HANDLE": "#9dbcdc",
        "SCROLL_HANDLE_HOVER": "#7aa3cc",
        "TRANSITION_BG": "#eaf4ff",
        "TRANSITION_FG": "#2b3e52",
        "TRANSITION_FLARE": "#8fbde8",
    },
    THEME_BORDEAUX: {
        # bordeaux: #600f18 を基準にした、血を思わせる暗い赤のテーマ。
        # 面・枠は基準色と同じかそれより暗く沈め、白に近い色は使わない。
        # 文字は可読性に必要な分だけ明るくした、くすんだ薄い赤にする。
        "BG": "#600f18",
        "WEB_BG": "#600f18",
        "SURFACE": "#450a11",
        "SURFACE_RAISED": "#500e15",
        "SURFACE_HOVER": "#571119",
        "SURFACE_SUNKEN": "#330609",
        "BORDER": "#7a222c",
        "BORDER_STRONG": "#93323d",
        "BORDER_ACCENT": "#ab434f",
        "TEXT": "#d8b4b8",
        "TEXT_BRIGHT": "#e6c8cb",
        "TEXT_SECONDARY": "#b58e93",
        "TEXT_MUTED": "#a17a80",
        "ICON": "#c8a2a7",
        "ACCENT": "#a63845",
        "ACCENT_STRONG": "#bf4a57",
        "ACCENT_SOFT": "#8f4a52",
        "SUCCESS": "#7a9a84",
        "DANGER": "#e57a74",
        "DANGER_BG": "#5f171c",
        "DANGER_BORDER": "#a34545",
        "SCROLL_HANDLE": "#7d2a34",
        "SCROLL_HANDLE_HOVER": "#9a3b46",
        "TRANSITION_BG": "#600f18",
        "TRANSITION_FG": "#d8b4b8",
        "TRANSITION_FLARE": "#c9505c",
    },
    THEME_PURE_PURPLE: {
        # pure purple: 星空の夜空（青紫）を面に、雲のラベンダーを枠に、
        # ふわふわした雲の淡いピンクラベンダーをアクセントにしたテーマ。
        # 文字は上着のような、わずかに紫がかった白。
        "BG": "#4b4a9c",
        "WEB_BG": "#4b4a9c",
        "SURFACE": "#524e9f",
        "SURFACE_RAISED": "#5b56a6",
        "SURFACE_HOVER": "#6560ad",
        "SURFACE_SUNKEN": "#3f4494",
        "BORDER": "#7771bb",
        "BORDER_STRONG": "#918cc4",
        "BORDER_ACCENT": "#c3aad6",
        "TEXT": "#f3eef3",
        "TEXT_BRIGHT": "#fcf9fc",
        "TEXT_SECONDARY": "#dcd0e6",
        "TEXT_MUTED": "#b9b1dc",
        "ICON": "#e0d8ef",
        "ACCENT": "#c9aedb",
        "ACCENT_STRONG": "#d9c2e3",
        "ACCENT_SOFT": "#a69dce",
        "SUCCESS": "#a3d6c6",
        "DANGER": "#ffa6bd",
        "DANGER_BG": "#6b3f82",
        "DANGER_BORDER": "#c07a9e",
        "SCROLL_HANDLE": "#7e78bf",
        "SCROLL_HANDLE_HOVER": "#9a95cb",
        "TRANSITION_BG": "#4b4a9c",
        "TRANSITION_FG": "#f3eef3",
        "TRANSITION_FLARE": "#e6d5ee",
    },
}

_CURRENT_THEME = THEME_DARK

# 既存コードに残るdark-themeの色を意味役割へ寄せる。新テーマを追加しても
# widgetごとの色置換を増やさず、ここだけで統一できるようにする。
_LEGACY_ROLE = {
    "#0b111f": "WEB_BG", "#0f1117": "BG", "#0d1524": "WEB_BG",
    "#12151c": "BG", "#121a24": "SURFACE_SUNKEN", "#141820": "SURFACE_SUNKEN",
    "#151820": "SURFACE_SUNKEN", "#141e30": "SURFACE_SUNKEN", "#181c26": "SURFACE", "#1a2030": "SURFACE",
    "#1a2332": "SURFACE", "#1a2740": "SURFACE_HOVER", "#1d2230": "SURFACE_RAISED",
    "#222836": "SURFACE_HOVER", "#232a38": "SURFACE_HOVER", "#252b38": "SURFACE_RAISED",
    "#1d2d44": "BORDER", "#2a3140": "BORDER", "#2a3348": "BORDER", "#2b3242": "BORDER",
    "#323a4c": "BORDER_STRONG", "#394255": "BORDER_STRONG", "#3a4458": "BORDER_STRONG",
    "#3d465c": "BORDER_STRONG", "#51607a": "SCROLL_HANDLE_HOVER",
    "#3d4a5e": "SCROLL_HANDLE", "#5a6b84": "SCROLL_HANDLE_HOVER",
    "#f1f3f7": "TEXT", "#eaf1fb": "TEXT_BRIGHT", "#e8eef8": "TEXT_BRIGHT",
    "#ffffff": "TEXT_BRIGHT", "#e7e9ed": "TRANSITION_FG",
    "#aeb6c5": "TEXT_SECONDARY", "#c5d4ea": "TEXT_SECONDARY", "#c5d0e6": "TEXT_SECONDARY",
    "#93a5c4": "ICON", "#9fb4d8": "ACCENT_SOFT", "#7f899a": "TEXT_MUTED",
    "#7a8eaa": "TEXT_MUTED", "#6b7c96": "TEXT_MUTED", "#5c6474": "TEXT_MUTED", "#5a6270": "TEXT_MUTED",
    "#4a7ec7": "ACCENT", "#1d9bf0": "ACCENT", "#3d7eff": "ACCENT_STRONG",
    "#3d6aa8": "BORDER_ACCENT", "#3d6a9e": "BORDER_ACCENT", "#2f517d": "BORDER_ACCENT",
    "#33639f": "ACCENT", "#2a5f9e": "ACCENT", "#336fba": "ACCENT",
    "#1f4f88": "BORDER_ACCENT", "#3a6aad": "BORDER_ACCENT", "#3d5a80": "BORDER_ACCENT",
    "#5b8fd6": "ACCENT_STRONG", "#6a9be0": "ACCENT_STRONG", "#5a7aa8": "ACCENT_SOFT",
    "#6a8ab8": "ACCENT_SOFT", "#7aa3d9": "ACCENT_SOFT",
    "#e66464": "DANGER", "#3d1a1a": "DANGER_BG", "#5d2a2a": "DANGER_BORDER",
}

_RGBA_ROLE = {
    (148, 178, 230): "BLUE_148",
    (122, 158, 218): "BLUE_122",
    (29, 155, 240): "BLUE_29",
    (230, 100, 100): "DANGER",
    (238, 187, 203): "BLUE_148",
    (217, 156, 178): "BLUE_122",
    (224, 142, 170): "BLUE_29",
    (220, 117, 133): "DANGER",
    (215, 127, 166): "BLUE_148",
    (201, 101, 147): "BLUE_122",
    (185, 75, 114): "DANGER",
    (111, 163, 216): "BLUE_148",
    (79, 140, 203): "BLUE_122",
    (192, 86, 110): "DANGER",
    (166, 56, 69): "BLUE_148",
    (191, 74, 87): "BLUE_122",
    (229, 122, 116): "DANGER",
    (201, 174, 219): "BLUE_148",
    (217, 194, 227): "BLUE_122",
    (255, 166, 189): "DANGER",
}

_RGBA_TARGET = {
    THEME_DARK: {
        "BLUE_148": (148, 178, 230),
        "BLUE_122": (122, 158, 218),
        "BLUE_29": (29, 155, 240),
        "DANGER": (230, 100, 100),
    },
    THEME_NADESHIKO: {
        "BLUE_148": (215, 127, 166),
        "BLUE_122": (201, 101, 147),
        "BLUE_29": (215, 127, 166),
        "DANGER": (185, 75, 114),
    },
    THEME_BABY_BLUE: {
        "BLUE_148": (111, 163, 216),
        "BLUE_122": (79, 140, 203),
        "BLUE_29": (111, 163, 216),
        "DANGER": (192, 86, 110),
    },
    THEME_BORDEAUX: {
        "BLUE_148": (166, 56, 69),
        "BLUE_122": (191, 74, 87),
        "BLUE_29": (166, 56, 69),
        "DANGER": (229, 122, 116),
    },
    THEME_PURE_PURPLE: {
        "BLUE_148": (201, 174, 219),
        "BLUE_122": (217, 194, 227),
        "BLUE_29": (201, 174, 219),
        "DANGER": (255, 166, 189),
    },
}

RADIUS_SM = 6
RADIUS_MD = 8

def _apply_theme_tokens() -> None:
    values = _THEMES[_CURRENT_THEME]
    globals().update(values)

def _sync_loaded_theme_modules() -> None:
    import sys
    module_tokens = {
        "src.ui.smooth_tooltip": ("BORDER", "SURFACE_RAISED", "TEXT"),
        "src.ui.update_dialog": ("SURFACE", "BORDER", "TEXT", "ACCENT", "SURFACE_RAISED"),
        "src.ui.external_site_confirm_dialog": (
            "SURFACE", "BORDER", "TEXT", "TEXT_MUTED", "TEXT_SECONDARY"
        ),
        "src.ui.avatar_edit": ("TEXT", "TEXT_SECONDARY", "BORDER_ACCENT"),
    }
    for module_name, names in module_tokens.items():
        module = sys.modules.get(module_name)
        if module is None:
            continue
        for name in names:
            try:
                setattr(module, name, globals()[name])
            except Exception:
                pass

def set_theme(theme_id: str | None) -> str:
    global _CURRENT_THEME
    key = str(theme_id or THEME_DARK).strip().lower()
    if key not in _THEMES:
        key = THEME_DARK
    _CURRENT_THEME = key
    _apply_theme_tokens()
    _sync_loaded_theme_modules()
    return key

def get_theme_id() -> str:
    return _CURRENT_THEME

def available_themes() -> tuple[tuple[str, str], ...]:
    return (
        (THEME_DARK, "dark navy"),
        (THEME_NADESHIKO, "milky pink"),
        (THEME_BABY_BLUE, "baby blue"),
        (THEME_BORDEAUX, "bordeaux"),
        (THEME_PURE_PURPLE, "pure purple"),
    )

def color(role: str) -> str:
    return str(_THEMES[_CURRENT_THEME].get(role, role))

def map_color(value: str) -> str:
    s = str(value or "").strip()
    low = s.lower()
    role = _LEGACY_ROLE.get(low)
    if _CURRENT_THEME == THEME_DARK and role is not None:
        return s
    if role is None:
        for theme_values in _THEMES.values():
            for candidate_role, candidate in theme_values.items():
                if low == str(candidate).lower():
                    role = candidate_role
                    break
            if role is not None:
                break
    return color(role) if role else s

def themed_qcolor(value: str):
    from PySide6.QtGui import QColor
    return QColor(map_color(value))

def remap_stylesheet(css: str, target_theme: str | None = None) -> str:
    import re
    if not css:
        return css
    theme_id = str(target_theme or _CURRENT_THEME).strip().lower()
    if theme_id not in _THEMES:
        theme_id = THEME_DARK
    target_values = _THEMES[theme_id]
    role_by_hex = dict(_LEGACY_ROLE)
    for values in _THEMES.values():
        for role, value in values.items():
            if isinstance(value, str) and value.startswith("#"):
                role_by_hex.setdefault(value.lower(), role)

    placeholders: dict[str, str] = {}
    def repl_hex(match):
        raw = match.group(0).lower()
        role = role_by_hex.get(raw)
        if not role:
            return match.group(0)
        if theme_id == THEME_DARK and raw in _LEGACY_ROLE:
            return match.group(0)
        token = f"__MAYOTTER_THEME_{len(placeholders)}__"
        placeholders[token] = str(target_values.get(role, raw))
        return token

    out = re.sub(r"#[0-9A-Fa-f]{6}", repl_hex, css)

    def repl_rgba(match):
        r, g, b = (int(match.group(i)) for i in range(1, 4))
        alpha = match.group(4)
        role = _RGBA_ROLE.get((r, g, b))
        if role is None:
            return match.group(0)
        rr, gg, bb = _RGBA_TARGET[theme_id][role]
        return f"rgba({rr}, {gg}, {bb}, {alpha})"

    out = re.sub(
        r"rgba\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*([0-9.]+)\s*\)",
        repl_rgba, out, flags=re.IGNORECASE,
    )
    for token, target in placeholders.items():
        out = out.replace(token, target)
    return out

_apply_theme_tokens()


def _refresh_widget_icons(widget) -> None:
    try:
        from src.ui.icons import (
            make_settings_icon, make_close_icon, make_edit_icon,
            make_edge_dock_icon, make_minimize_icon, make_maximize_icon,
            make_restore_icon, make_stop_icon, make_mic_icon,
            make_chevron_left_icon, make_plus_icon, make_forward_icon,
            make_back_icon, make_home_icon, make_download_icon,
            make_folder_icon, make_chevron_down_icon,
            _COLOR_SECONDARY, _COLOR_TEXT, _COLOR_ACCENT_SOFT,
            _COLOR_DANGER, _COLOR_TEXT_SECONDARY,
        )
    except Exception:
        return

    if widget.inherits("QToolButton"):
        try:
            obj_name = widget.objectName()
            if obj_name == "settings_btn":
                widget.setIcon(make_settings_icon(_COLOR_TEXT_SECONDARY, 14))
            elif obj_name in ("win_min_btn", "win_max_btn", "win_close_btn"):
                if obj_name == "win_min_btn":
                    widget.setIcon(make_minimize_icon(_COLOR_SECONDARY, 12))
                elif obj_name == "win_max_btn":
                    win = widget.window()
                    if win is not None and win.isMaximized():
                        widget.setIcon(make_restore_icon(_COLOR_SECONDARY, 12))
                    else:
                        widget.setIcon(make_maximize_icon(_COLOR_SECONDARY, 12))
                elif obj_name == "win_close_btn":
                    widget.setIcon(make_close_icon(_COLOR_SECONDARY, 12))
            elif obj_name == "dock_chrome_chevron":
                widget.setIcon(make_chevron_left_icon(_COLOR_SECONDARY, 12))
            elif obj_name == "record_btn":
                rec = widget.property("recording")
                if rec == "true" or str(rec).lower() == "true":
                    widget.setIcon(make_stop_icon(_COLOR_DANGER, 14))
                else:
                    widget.setIcon(make_mic_icon(_COLOR_ACCENT_SOFT, 14))
            elif obj_name == "edge_dock_toggle_btn":
                win = widget.window()
                dock_enabled = getattr(win, "_edge_dock_enabled", False) if win else False
                widget.setIcon(
                    make_edge_dock_icon(
                        _COLOR_TEXT if dock_enabled else _COLOR_SECONDARY,
                        14 if dock_enabled else 12
                    )
                )
            elif obj_name == "download_icon_btn":
                widget.setIcon(make_download_icon(_COLOR_ACCENT_SOFT, 14))
            elif obj_name in ("back_btn", "forward_btn", "reload_btn", "home_btn", "stow_self_btn"):
                if obj_name == "back_btn":
                    widget.setIcon(make_back_icon(_COLOR_SECONDARY, 14))
                elif obj_name == "forward_btn":
                    widget.setIcon(make_forward_icon(_COLOR_SECONDARY, 14))
                elif obj_name == "reload_btn":
                    # 独自描画なのでアイコン更新は不要
                    pass
                elif obj_name == "home_btn":
                    widget.setIcon(make_home_icon(_COLOR_SECONDARY, 16))
                elif obj_name == "stow_self_btn":
                    widget.setIcon(make_chevron_down_icon(_COLOR_SECONDARY, 14))
            elif obj_name == "tab_add_btn":
                widget.setIcon(make_plus_icon(_COLOR_SECONDARY, 10))
            elif obj_name == "download_action_btn":
                widget.setIcon(make_download_icon(_COLOR_ACCENT_SOFT, 14))
            elif obj_name == "download_item_close":
                widget.setIcon(make_close_icon(_COLOR_TEXT_SECONDARY, 10))
            elif obj_name == "open_folder_btn":
                widget.setIcon(make_folder_icon(_COLOR_SECONDARY, 12))
            elif obj_name in ("service_menu_edit_btn", "service_menu_del_btn"):
                if obj_name == "service_menu_edit_btn":
                    widget.setIcon(make_edit_icon(_COLOR_TEXT_SECONDARY, 12))
                else:
                    widget.setIcon(make_close_icon(_COLOR_TEXT_SECONDARY, 10))
            elif obj_name in ("col_drag_handle"):
                widget.update()  # Custom painted
            widget.update()
        except Exception:
            pass

    if widget.inherits("QPushButton"):
        try:
            obj_name = widget.objectName()
            if obj_name == "add_twitter_btn":
                pass
            elif obj_name == "add_column_btn":
                pass
            elif obj_name == "edge_dock_toggle_btn":
                win = widget.window()
                dock_enabled = getattr(widget.window(), "_edge_dock_enabled", False) if widget.window() else False
                widget.setIcon(
                    make_edge_dock_icon(
                        _COLOR_TEXT if dock_enabled else _COLOR_SECONDARY,
                        12
                    )
                )
            elif obj_name == "download_icon_btn":
                widget.setIcon(make_download_icon(_COLOR_ACCENT_SOFT, 14))
            elif obj_name == "open_folder_btn":
                widget.setIcon(make_folder_icon(_COLOR_SECONDARY, 12))
            widget.update()
        except Exception:
            pass

    try:
        for child in widget.children():
            if hasattr(child, 'inherits'):
                _refresh_widget_icons(child)
    except Exception:
        pass


def overlay_stylesheet(theme_id: str | None = None) -> str:
    from pathlib import Path
    target = str(theme_id or _CURRENT_THEME).strip().lower()
    if target not in _THEMES:
        target = THEME_DARK
    values = _THEMES[target]
    SURFACE = values["SURFACE"]
    SURFACE_RAISED = values["SURFACE_RAISED"]
    BORDER = values["BORDER"]
    BORDER_STRONG = values["BORDER_STRONG"]
    BORDER_ACCENT = values["BORDER_ACCENT"]
    TEXT = values["TEXT"]
    TEXT_SECONDARY = values["TEXT_SECONDARY"]
    TEXT_MUTED = values["TEXT_MUTED"]
    ACCENT = values["ACCENT"]
    _assets = Path(__file__).resolve().parent / "assets"
    _plus = (_assets / "spin_plus.png").as_posix()
    _minus = (_assets / "spin_minus.png").as_posix()
    css = f"""
        QWidget#mayotter_settings_dialog, QWidget#download_overlay,
        QWidget#url_overlay, QWidget#text_prompt_overlay,
        QWidget#confirm_overlay, QWidget#column_add_overlay {{
            background-color: {SURFACE};
            color: {TEXT};
            border: 1px solid {BORDER};
            border-radius: {RADIUS_MD}px;
        }}
        QWidget#mayotter_settings_dialog[mayotterNativeRounded="true"],
        QWidget#download_overlay[mayotterNativeRounded="true"],
        QWidget#url_overlay[mayotterNativeRounded="true"],
        QWidget#text_prompt_overlay[mayotterNativeRounded="true"],
        QWidget#confirm_overlay[mayotterNativeRounded="true"],
        QWidget#column_add_overlay[mayotterNativeRounded="true"] {{
            border-radius: 0px;
        }}
        QLabel {{ color: {TEXT}; background: transparent; }}
        QLabel#download_overlay_title, QLabel#settings_title {{
            color: {TEXT}; font-size: 13px; font-weight: 600;
        }}
        QLabel#download_item_name {{ color: {TEXT}; font-size: 12px; }}
        QLabel#download_item_status {{ color: {TEXT_SECONDARY}; font-size: 11px; }}
        QGroupBox {{
            color: {TEXT}; border: 1px solid {BORDER}; border-radius: {RADIUS_SM}px;
            margin-top: 8px; padding-top: 6px; background-color: {SURFACE_RAISED};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin; left: 8px; padding: 0 3px; color: {TEXT_SECONDARY};
        }}
        QCheckBox {{ color: {TEXT}; spacing: 6px; background: transparent; }}
        QCheckBox:disabled {{ color: {TEXT_MUTED}; }}
        QCheckBox::indicator {{
            width: 14px; height: 14px; border-radius: 3px;
            border: 1px solid {BORDER_STRONG}; background: {SURFACE};
        }}
        QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
        QRadioButton {{ color: {TEXT}; spacing: 6px; background: transparent; }}
        QRadioButton:disabled {{ color: {TEXT_MUTED}; }}
        QRadioButton::indicator {{
            width: 14px; height: 14px; border-radius: 7px;
            border: 1px solid {BORDER_STRONG}; background: {SURFACE};
        }}
        QRadioButton::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
        QSpinBox, QComboBox, QLineEdit {{
            background-color: {SURFACE}; border: 1px solid {BORDER};
            border-radius: {RADIUS_SM}px; color: {TEXT}; padding: 2px 6px;
            min-height: 22px; selection-background-color: {BORDER_ACCENT};
        }}
        QSpinBox {{
            padding-right: 18px;
        }}
        QSpinBox::up-button, QSpinBox::down-button {{
            subcontrol-origin: border;
            width: 16px;
            background-color: #252b38;
            border-left: 1px solid {BORDER};
        }}
        QSpinBox::up-button {{
            subcontrol-position: top right;
            border-top-right-radius: {RADIUS_SM}px;
            border-bottom: 1px solid {BORDER};
        }}
        QSpinBox::down-button {{
            subcontrol-position: bottom right;
            border-bottom-right-radius: {RADIUS_SM}px;
        }}
        QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
            background-color: #323a4c;
        }}
        QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {{
            background-color: {BORDER_STRONG};
        }}
        QSpinBox::up-arrow {{
            image: url("__SPIN_PLUS__");
            width: 8px;
            height: 8px;
            margin: 1px;
        }}
        QSpinBox::down-arrow {{
            image: url("__SPIN_MINUS__");
            width: 8px;
            height: 8px;
            margin: 1px;
        }}
        QSpinBox:hover, QComboBox:hover, QLineEdit:hover {{ border-color: {BORDER_STRONG}; }}
        QPushButton {{
            background-color: {SURFACE_RAISED}; border: 1px solid {BORDER};
            border-radius: {RADIUS_SM}px; color: {TEXT}; padding: 3px 10px; min-height: 22px;
        }}
        QPushButton:hover {{ background-color: {BORDER}; border-color: {BORDER_STRONG}; }}
        QPushButton:pressed {{ background-color: {BORDER_STRONG}; }}
        QToolButton {{ background: transparent; border: none; border-radius: 4px; color: {TEXT_SECONDARY}; }}
        QToolButton:hover {{ background-color: rgba(148, 178, 230, 0.12); }}
        QToolButton#download_action_btn {{
            background-color: transparent; border: 1px solid transparent; border-radius: 5px;
        }}
        QToolButton#download_action_btn:hover {{
            background-color: rgba(148, 178, 230, 0.14); border: 1px solid transparent;
        }}
        QToolButton#download_action_btn_danger {{
            background-color: transparent; border: 1px solid transparent; border-radius: 5px;
        }}
        QToolButton#download_action_btn_danger:hover {{
            background-color: rgba(230, 100, 100, 0.16); border: 1px solid transparent;
        }}
        QListWidget {{ background-color: transparent; border: none; color: {TEXT}; outline: none; }}
        QListWidget::item {{
            background-color: {SURFACE_RAISED}; border: 1px solid {BORDER};
            border-radius: {RADIUS_SM}px; margin: 3px 2px; padding: 2px;
        }}
        QListWidget::item:selected {{ border-color: {BORDER_ACCENT}; background-color: #222836; }}
        QListWidget#download_overlay_list {{
            outline: none;
            show-decoration-selected: 0;
        }}
        QListWidget#download_overlay_list::item {{
            background-color: transparent;
            border: none;
            margin: 0px;
            padding: 0px;
            outline: none;
        }}
        QListWidget#download_overlay_list::item:selected {{
            background-color: transparent;
            border: none;
            outline: none;
        }}
        QListWidget#download_overlay_list::item:hover {{
            background-color: transparent;
            border: none;
            outline: none;
        }}
        QDialogButtonBox QPushButton {{ min-width: 56px; padding: 2px 8px; min-height: 22px; font-size: 11px; }}
        QToolTip {{
            background-color: {SURFACE_RAISED};
            color: {TEXT};
            border: 1px solid {BORDER};
            border-radius: 6px;
            padding: 4px 8px;
            font-size: 11px;
        }}
        /* WA_NativeWindow overlay は親 QSS を継承しないことがあるため共通スクロールバーを明示 */
        QScrollBar:vertical {{
            background: {SURFACE_SUNKEN};
            background-color: {SURFACE_SUNKEN};
            width: 8px;
            border: none;
            margin: 0;
        }}
        QScrollBar::groove:vertical {{
            background: {SURFACE_SUNKEN};
            background-color: {SURFACE_SUNKEN};
            border: none;
        }}
        QScrollBar::handle:vertical {{
            background: {SCROLL_HANDLE};
            background-color: {SCROLL_HANDLE};
            border-radius: 4px;
            min-height: 30px;
            border: none;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {SCROLL_HANDLE_HOVER};
            background-color: {SCROLL_HANDLE_HOVER};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0; width: 0; background: transparent; border: none;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: {SURFACE_SUNKEN};
            background-color: {SURFACE_SUNKEN};
        }}
        QScrollBar:horizontal {{
            background: {SURFACE_SUNKEN};
            background-color: {SURFACE_SUNKEN};
            height: 8px;
            border: none;
            margin: 0;
        }}
        QScrollBar::groove:horizontal {{
            background: {SURFACE_SUNKEN};
            background-color: {SURFACE_SUNKEN};
            border: none;
        }}
        QScrollBar::handle:horizontal {{
            background: {SCROLL_HANDLE};
            background-color: {SCROLL_HANDLE};
            border-radius: 4px;
            min-width: 30px;
            border: none;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {SCROLL_HANDLE_HOVER};
            background-color: {SCROLL_HANDLE_HOVER};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0; height: 0; background: transparent; border: none;
        }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
            background: {SURFACE_SUNKEN};
            background-color: {SURFACE_SUNKEN};
        }}
    """
    return remap_stylesheet(
        css.replace("__SPIN_PLUS__", _plus).replace("__SPIN_MINUS__", _minus),
        target_theme=target,
    )

def dark_palette():
    from PySide6.QtGui import QColor, QPalette
    p = QPalette()
    text = QColor(TEXT)
    muted = QColor(TEXT_MUTED)
    surface = QColor(SURFACE)
    bg = QColor(BG)
    raised = QColor(SURFACE_RAISED)
    accent = QColor(ACCENT)
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
        c = muted if group == QPalette.ColorGroup.Disabled else text
        p.setColor(group, QPalette.ColorRole.WindowText, c)
        p.setColor(group, QPalette.ColorRole.Text, c)
        p.setColor(group, QPalette.ColorRole.ButtonText, c)
        p.setColor(group, QPalette.ColorRole.Window, surface)
        p.setColor(group, QPalette.ColorRole.Base, bg)
        p.setColor(group, QPalette.ColorRole.Button, raised)
        p.setColor(group, QPalette.ColorRole.Highlight, accent)
        p.setColor(group, QPalette.ColorRole.HighlightedText, text)
    return p

def _retint_widget_stylesheet(widget) -> None:
    try:
        if bool(widget.property("_mayotter_theme_rewrite")):
            return
        sheet = str(widget.styleSheet() or "")
        if not sheet:
            return

        source_prop = widget.property("_mayotter_theme_source_stylesheet")
        rendered_prop = widget.property("_mayotter_theme_rendered_stylesheet")
        source = str(source_prop) if source_prop is not None else ""
        rendered = str(rendered_prop) if rendered_prop is not None else ""

        # source は dark の意味色へ正規化して保持し、Pink中に生成された
        # widget でもテーマ往復で現在色をsourceとして固定しない。
        if not source or (rendered and sheet != rendered):
            source = remap_stylesheet(sheet, target_theme=THEME_DARK)
            widget.setProperty("_mayotter_theme_source_stylesheet", source)

        mapped = remap_stylesheet(source)
        widget.setProperty("_mayotter_theme_rendered_stylesheet", mapped)
        if mapped == sheet:
            return
        widget.setProperty("_mayotter_theme_rewrite", True)
        try:
            widget.setStyleSheet(mapped)
        finally:
            widget.setProperty("_mayotter_theme_rewrite", False)
    except Exception:
        pass

def apply_theme_to_application(app) -> None:
    try:
        app.setPalette(dark_palette())
    except Exception:
        pass
    try:
        pal = dark_palette()
        for widget in app.allWidgets():
            _retint_widget_stylesheet(widget)
            try:
                if widget.__class__.__name__ != "XWebView" and not widget.inherits("QWebEngineView"):
                    widget.setPalette(pal)
            except Exception:
                pass
            try:
                _refresh_widget_icons(widget)
            except Exception:
                pass
            try:
                widget.update()
            except Exception:
                pass
    except Exception:
        pass
    # allWidgets に含まれないトップレベルも更新する
    try:
        for widget in app.topLevelWidgets():
            _refresh_widget_icons(widget)
            widget.update()
    except Exception:
        pass

def install_theme_filter(app) -> None:
    try:
        from PySide6.QtCore import QObject, QEvent
        from PySide6.QtWidgets import QWidget
    except Exception:
        return
    if getattr(app, "_mayotter_theme_filter", None) is not None:
        return

    class _ThemeFilter(QObject):
        def eventFilter(self, obj, event):
            try:
                if isinstance(obj, QWidget) and event.type() in (
                    QEvent.Type.StyleChange,
                    QEvent.Type.Polish,
                    QEvent.Type.Show,
                ):
                    _retint_widget_stylesheet(obj)
            except Exception:
                pass
            return False

    filt = _ThemeFilter(app)
    app.installEventFilter(filt)
    app._mayotter_theme_filter = filt

def apply_overlay_theme(widget) -> None:
    try:
        from PySide6.QtCore import Qt
        widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    except Exception:
        pass
    try:
        if bool(widget.isWindow()):
            from src.ui.window_polish import prepare_popup_chrome
            prepare_popup_chrome(
                widget, background=SURFACE, border_color=BORDER, corner="round"
            )
    except Exception:
        pass
    try:
        source = overlay_stylesheet(THEME_DARK)
        mapped = remap_stylesheet(source)
        widget.setProperty("_mayotter_theme_source_stylesheet", source)
        widget.setProperty("_mayotter_theme_rendered_stylesheet", mapped)
        widget.setProperty("_mayotter_theme_rewrite", True)
        try:
            widget.setStyleSheet(mapped)
        finally:
            widget.setProperty("_mayotter_theme_rewrite", False)
    except Exception:
        pass
    try:
        pal = dark_palette()
        widget.setPalette(pal)
        from PySide6.QtWidgets import QAbstractButton, QLabel, QGroupBox
        for child in widget.findChildren(QAbstractButton):
            child.setPalette(pal)
            child.setAutoFillBackground(False)
        for child in widget.findChildren(QLabel):
            child.setPalette(pal)
        for child in widget.findChildren(QGroupBox):
            child.setPalette(pal)
    except Exception:
        pass

POPOVER_OPEN_MS = 170
POPOVER_CLOSE_MS = 120


def menu_dropdown_show(widget, *, duration_ms: int = POPOVER_OPEN_MS) -> None:
    try:
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve, Qt as _Qt

        for attr in (
            "_mayotter_hide_anim",
            "_mayotter_show_anim",
            "_mayotter_show_group",
            "_mayotter_hide_group",
        ):
            old = getattr(widget, attr, None)
            if old is not None:
                try:
                    old.stop()
                except Exception:
                    pass

        # effect を外す
        try:
            widget.setGraphicsEffect(None)
        except Exception:
            pass
        try:
            widget.setAttribute(_Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
            widget.setAutoFillBackground(False)
        except Exception:
            pass
        try:
            widget.setAttribute(_Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        except Exception:
            pass

        flags = int(widget.windowFlags())
        is_top = bool(widget.isWindow()) or bool(
            flags & int(_Qt.WindowType.Popup | _Qt.WindowType.Tool | _Qt.WindowType.Window)
        )
        is_native_child = (not is_top) and bool(
            widget.testAttribute(_Qt.WidgetAttribute.WA_NativeWindow)
        )

        # native 子では effect 禁止
        if is_native_child:
            try:
                widget.setWindowOpacity(1.0)
            except Exception:
                pass
            widget.show()
            widget.raise_()
            try:
                widget._mayotter_fading_out = False
            except Exception:
                pass
            return

        if is_top:
            try:
                was_visible = bool(widget.isVisible())
                start_opacity = float(widget.windowOpacity()) if was_visible else 0.0
            except Exception:
                was_visible, start_opacity = False, 0.0
            start_opacity = max(0.0, min(1.0, start_opacity))
            try:
                widget._mayotter_fading_out = False
            except Exception:
                pass
            if not was_visible:
                widget.setWindowOpacity(0.0)
            widget.show()
            widget.raise_()
            opacity = QPropertyAnimation(widget, b"windowOpacity", widget)
            opacity.setDuration(max(45, int(duration_ms * (1.0 - start_opacity))))
            opacity.setStartValue(start_opacity)
            opacity.setEndValue(1.0)
            opacity.setEasingCurve(QEasingCurve.Type.OutCubic)

            def _after():
                try:
                    widget.setWindowOpacity(1.0)
                except Exception:
                    pass
                try:
                    widget.setAttribute(_Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
                except Exception:
                    pass
                try:
                    widget._mayotter_fading_out = False
                except Exception:
                    pass

            opacity.finished.connect(_after)
            opacity.start()
            widget._mayotter_show_anim = opacity
            widget._mayotter_show_group = opacity
            return

        widget.show()
        widget.raise_()
        try:
            widget._mayotter_fading_out = False
        except Exception:
            pass
    except Exception:
        try:
            widget.setGraphicsEffect(None)
        except Exception:
            pass
        try:
            widget.setWindowOpacity(1.0)
            widget.show()
            widget.raise_()
        except Exception:
            pass

def menu_dropdown_hide(widget, *, duration_ms: int = POPOVER_CLOSE_MS, on_finished=None) -> None:
    try:
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve, Qt as _Qt

        if not widget.isVisible():
            if callable(on_finished):
                try:
                    on_finished()
                except Exception:
                    pass
            return

        def _done():
            try:
                try:
                    widget.setGraphicsEffect(None)
                except Exception:
                    pass
                try:
                    widget._mayotter_allow_hide = True
                except Exception:
                    pass
                widget.hide()
                try:
                    widget.setWindowOpacity(1.0)
                except Exception:
                    pass
                try:
                    widget._mayotter_allow_hide = False
                except Exception:
                    pass
                try:
                    widget.setAttribute(_Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
                    widget.setAttribute(_Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
                    widget.setAutoFillBackground(False)
                except Exception:
                    pass
            except Exception:
                pass
            try:
                widget._mayotter_fading_out = False
            except Exception:
                pass
            if callable(on_finished):
                try:
                    on_finished()
                except Exception:
                    pass

        for attr in (
            "_mayotter_hide_anim",
            "_mayotter_show_anim",
            "_mayotter_show_group",
            "_mayotter_hide_group",
        ):
            old = getattr(widget, attr, None)
            if old is not None:
                try:
                    old.stop()
                except Exception:
                    pass

        try:
            widget.setAttribute(_Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        except Exception:
            pass
        try:
            widget.clearFocus()
        except Exception:
            pass

        flags = int(widget.windowFlags())
        is_top = bool(widget.isWindow()) or bool(
            flags & int(_Qt.WindowType.Popup | _Qt.WindowType.Tool | _Qt.WindowType.Window)
        )
        is_native_child = (not is_top) and bool(
            widget.testAttribute(_Qt.WidgetAttribute.WA_NativeWindow)
        )
        try:
            widget._mayotter_fading_out = True
        except Exception:
            pass

        # effect を外す
        try:
            widget.setGraphicsEffect(None)
        except Exception:
            pass

        if is_native_child or not is_top:
            _done()
            return

        opacity = QPropertyAnimation(widget, b"windowOpacity", widget)
        try:
            start_op = float(widget.windowOpacity())
        except Exception:
            start_op = 1.0
        if start_op <= 0.0:
            start_op = 1.0
        opacity.setDuration(max(40, int(duration_ms * min(1.0, start_op))))
        opacity.setStartValue(start_op)
        opacity.setEndValue(0.0)
        opacity.setEasingCurve(QEasingCurve.Type.InCubic)
        opacity.finished.connect(_done)
        opacity.start()
        widget._mayotter_hide_anim = opacity
        widget._mayotter_hide_group = opacity
    except Exception:
        try:
            try:
                widget.setGraphicsEffect(None)
            except Exception:
                pass
            try:
                widget._mayotter_allow_hide = True
            except Exception:
                pass
            widget.hide()
            try:
                widget._mayotter_allow_hide = False
            except Exception:
                pass
        except Exception:
            pass
        if callable(on_finished):
            try:
                on_finished()
            except Exception:
                pass

def popover_show(widget, *, duration_ms: int = POPOVER_OPEN_MS) -> None:
    menu_dropdown_show(widget, duration_ms=duration_ms)

def popover_hide(widget, *, duration_ms: int = POPOVER_CLOSE_MS, on_finished=None) -> None:
    menu_dropdown_hide(widget, duration_ms=duration_ms, on_finished=on_finished)



def install_fade_tooltips(app):
    """ツールチップを共通の角丸サーフェスで表示するようにする。"""
    from src.ui.smooth_tooltip import install_smooth_tooltips
    return install_smooth_tooltips(app)
