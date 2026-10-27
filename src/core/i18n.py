from __future__ import annotations

import logging
from string import Formatter

from src.core.translations_en import EN
from src.core.translations_zh_cn import ZH_CN

LANGUAGES = {'ja': '日本語', 'en': 'English', 'zh-CN': '简体中文'}
CATALOGS = {'en': EN, 'zh-CN': ZH_CN}
_language = 'ja'
_missing: set[tuple[str, str]] = set()


def get_language() -> str:
    return _language


def set_language(language: str) -> None:
    global _language
    _language = language if language == 'ja' or language in CATALOGS else 'ja'


def tr(source: str, *, context: str = '', language: str | None = None, **values) -> str:
    text = source
    target = _language if language is None else language
    catalog = CATALOGS.get(target, {})
    if target != 'ja':
        key = context + '\x04' + source if context else source
        text = catalog.get(key, source)
        if key not in catalog and (target, key) not in _missing and any(ch.isalpha() for ch in source):
            _missing.add((target, key))
            logging.getLogger(__name__).warning('Missing %s translation: %r', target, key)
    if not values:
        return text
    try:
        return text.format(**values)
    except (KeyError, ValueError, IndexError):
        logging.getLogger(__name__).error('Invalid translation placeholders: %r', source)
        try:
            return source.format(**values)
        except (KeyError, ValueError, IndexError):
            return source


def catalog_errors() -> list[str]:
    formatter = Formatter()
    errors = []
    for language, catalog in CATALOGS.items():
        for source, translated in catalog.items():
            try:
                fields = lambda text: sorted((name, spec, conversion) for _, name, spec, conversion in formatter.parse(text) if name is not None)
                if fields(source) != fields(translated):
                    errors.append(f'{language}: {source}')
            except ValueError:
                errors.append(f'{language}: {source}')
    return errors


def accept_language(language: str | None = None) -> str:
    if (language or _language) == 'zh-CN':
        return 'zh-CN,zh;q=0.9'
    if (language or _language) == 'en':
        return 'en-US,en;q=0.9,ja-JP;q=0.6,ja;q=0.5'
    return 'ja-JP,ja;q=0.9,en-US;q=0.7,en;q=0.6'
