"""表示言語に応じた Mayotter UI のフォント。

簡体字中国語では同梱の Noto Sans SC を使う。Windows 既定の UI フォント（日本語環境では
Yu Gothic UI）のままだと、日本語字形の漢字と、日本語フォントに無い簡体字だけが
別フォントへ代替された文字が混在するため。日本語をはじめ他の言語は OS 既定の UI フォントを
そのまま使い、輪郭のアンチエイリアスだけを全言語で有効にする。
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

# notofonts/noto-cjk の SC サブセット静的 OTF（OFL-1.1、ライセンスは同じフォルダの OFL.txt）。
# 可変フォントは Qt の登録時に名前付きインスタンスごとにメモリを確保し、
# 3 ウェイトの静的フォントより 2〜3 倍重いため使わない。
ZH_CN_FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
ZH_CN_FONT_FILES = ("NotoSansSC-Regular.otf", "NotoSansSC-Medium.otf", "NotoSansSC-Bold.otf")
ZH_CN_FAMILY = "Noto Sans SC"

_log = logging.getLogger(__name__)
_default_font: QFont | None = None
_zh_family: str | None = None
_zh_load_attempted = False


def _zh_cn_family() -> str | None:
    """同梱フォントを一度だけ登録する。失敗時は None（既定フォントのまま表示する）。"""
    global _zh_family, _zh_load_attempted
    if not _zh_load_attempted:
        _zh_load_attempted = True
        loaded = []
        for name in ZH_CN_FONT_FILES:
            font_id = QFontDatabase.addApplicationFont(str(ZH_CN_FONT_DIR / name))
            if font_id >= 0 and ZH_CN_FAMILY in QFontDatabase.applicationFontFamilies(font_id):
                loaded.append(name)
            else:
                _log.warning("Noto Sans SC could not be loaded from %s", ZH_CN_FONT_DIR / name)
        # Regular が無いと本文が別ウェイトで描かれるので、その場合は既定フォントのままにする
        if ZH_CN_FONT_FILES[0] in loaded:
            _zh_family = ZH_CN_FAMILY
    return _zh_family


def language_font(language: str) -> QFont:
    """その言語の UI に使うフォント。サイズは起動時のアプリ既定フォントを引き継ぐ。"""
    global _default_font
    if _default_font is None:
        _default_font = QFont(QApplication.font())
    font = QFont(_default_font)
    if language == "zh-CN":
        family = _zh_cn_family()
        if family:
            # 既定フォントは Noto Sans SC に無い記号・絵文字の代替先として残す
            font.setFamilies([family, *_default_font.families()])
    # 日本語を含む既定フォントは OS の UI フォント（日本語環境では Yu Gothic UI）のままにして、
    # 文字の輪郭だけアンチエイリアスする（ClearType が無効な環境でも輪郭が刻まない）。
    font.setStyleStrategy(font.styleStrategy() | QFont.StyleStrategy.PreferAntialias)
    return font


def apply_language_font(app: QApplication, language: str) -> None:
    """アプリ既定フォントを言語に合わせる。ウィジェット生成前に呼ぶ。

    QApplication.setStyleSheet() は QMenu・QAbstractItemView 等のクラス別フォントを
    OS テーマの値へ戻すため、アプリの QSS を設定した後にも呼ぶ。
    """
    font = language_font(language)
    if font == _default_font and app.font() == font:
        # 既定フォントのままなら、OSのクラス別フォントにも触れない
        return
    # クラス名なしの setFont はクラス別フォントも消すので、メニュー等も同じフォントになる
    app.setFont(font)
