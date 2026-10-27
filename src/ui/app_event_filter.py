"""アプリ全体に常駐する Python イベントフィルタを、Qt へは 1 つだけ登録する。

app.installEventFilter() に Python オブジェクトを登録すると、全イベントで C++→Python の
変換が登録数だけ起きる。アクセシビリティが有効な環境では WebEngine が DOM ごとに内部
QObject を作り、それが初めて Python に渡るたびに PySide の補助オブジェクトの生成・破棄
イベントも連鎖するため、フィルタの数がそのまま UI の停止時間になる（Dock 復帰で数百 ms）。
"""
from __future__ import annotations

import weakref

from PySide6.QtCore import QObject


class _AppEventFilterHub(QObject):
    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        # 弱参照で持つ。ここが登録先の寿命を延ばさないようにする
        self._filters: list[weakref.ref] = []

    def add(self, target: QObject) -> None:
        self.remove(target)
        # Qt のアプリフィルタと同じく、後から登録したものを先に呼ぶ
        self._filters.insert(0, weakref.ref(target))

    def remove(self, target: QObject) -> None:
        self._filters = [ref for ref in self._filters if ref() is not None and ref() is not target]

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt override
        for ref in tuple(self._filters):
            target = ref()
            if target is None:
                continue
            try:
                if target.eventFilter(obj, event):
                    return True
            except RuntimeError:
                # C++ 側が破棄済み
                self._filters = [r for r in self._filters if r is not ref]
        return False


def install_app_event_filter(app, target: QObject) -> None:
    """app.installEventFilter(target) の代わり。常駐するフィルタや、登録・解除を繰り返すフィルタに使う。"""
    if app is None:
        return
    hub = getattr(app, "_mayotter_app_event_filter_hub", None)
    if hub is None:
        hub = _AppEventFilterHub(app)
        app._mayotter_app_event_filter_hub = hub
    hub.add(target)
    # 登録・解除を繰り返しても破棄時の接続は 1 本だけにする
    if not getattr(target, "_mayotter_app_filter_hooked", False):
        try:
            target.destroyed.connect(lambda *_args, ref=weakref.ref(target): _forget(hub, ref))
            target._mayotter_app_filter_hooked = True
        except Exception:
            pass
    # 同じフィルタの再登録は Qt 側で重複しない（登録が無効化されていた場合にも備える）
    app.installEventFilter(hub)


def _forget(hub: _AppEventFilterHub, ref: weakref.ref) -> None:
    target = ref()
    try:
        hub._filters = [r for r in hub._filters if r() is not None and r() is not target]
    except RuntimeError:
        pass


def remove_app_event_filter(app, target: QObject) -> None:
    """install_app_event_filter() で登録したものを外す（Qt 側の登録は 1 つのまま残す）。"""
    hub = getattr(app, "_mayotter_app_event_filter_hub", None) if app is not None else None
    if hub is not None:
        hub.remove(target)
