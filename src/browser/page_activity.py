"""ページ内容を読み出さず、休止・破棄の安全性を判定する隔離 world のスクリプト。"""

ACTIVITY_SCRIPT = r"""
(function () {
  const state = {edited: false, upload: false, frameUsed: false, editedControls: new WeakSet()};
  state.isSearchField = field => field.matches(
    'input[type="search"],[role="searchbox"],input[name="q"],input[name="query"],input[name="search"],' +
    '[data-testid="searchBox"],[data-testid="SearchBox_Search_Input"]') || !!field.closest('[role="search"]');
  globalThis.__mayotterPageActivity = state;
  const edited = ev => {
    state.edited = true;
    if (ev.target instanceof Element) state.editedControls.add(ev.target);
  };
  document.addEventListener('input', edited, true);
  document.addEventListener('change', ev => {
    edited(ev);
    if (ev.target && ev.target.type === 'file') state.upload = true;
  }, true);
  document.addEventListener('paste', ev => {
    edited(ev);
    if (ev.clipboardData && ev.clipboardData.files.length) state.upload = true;
  }, true);
  document.addEventListener('drop', ev => {
    edited(ev);
    if (ev.dataTransfer && ev.dataTransfer.files.length) state.upload = true;
  }, true);
  // 埋め込み（iframe 等）にフォーカスが入ると親 window は blur する。中の入力は見えないため記録する。
  const markFrame = () => {
    const el = document.activeElement;
    if (el && /^(IFRAME|FRAME|OBJECT|EMBED)$/.test(el.tagName)) state.frameUsed = true;
  };
  window.addEventListener('blur', () => { markFrame(); setTimeout(markFrame, 0); }, true);
  document.addEventListener('focusin', markFrame, true);
})();
"""

# 戻り値は "<判定>[:<理由>]"（理由は検出したものを + で連結）。判定の優先順は
# unknown（判定不能）→ busy（使用中）→ retain（入力履歴あり）→ safe。
# 理由は診断用の固定コードのみで、入力内容・URL は返さない。
# - iframe-used: 埋め込みにフォーカスが入ったことがある（中の入力・送信を確認できない）→ unknown
# - iframe / progress: 存在するだけ（操作していない埋め込み・読込表示）→ 判定に影響しない情報
#   投稿送信は入力（edited）、アップロードはファイル選択・貼付・ドロップ（upload）で別に保護する。
_SAFETY_PROBE = r"""
function (restarting) {
  try {
    const state = globalThis.__mayotterPageActivity;
    if (!state) return 'unknown:no-tracker';
    if (document.readyState !== 'complete') return 'unknown:loading';
    const unknown = [], busy = [], info = [];
    const active = document.activeElement;
    const frameFocused = !!(active && /^(IFRAME|FRAME|OBJECT|EMBED)$/.test(active.tagName));
    if (document.querySelector('iframe,frame,object,embed')) {
      if (state.frameUsed || frameFocused) unknown.push('iframe-used'); else info.push('iframe');
    }
    if (state.upload) busy.push('upload');
    if (document.querySelector('[role="progressbar"],[aria-busy="true"]')) info.push('progress');
    for (const media of document.querySelectorAll('audio,video')) {
      if ((!media.paused && !media.ended) || (media.srcObject && media.srcObject.active)) {
        busy.push('media');
        break;
      }
    }
    let file = false, text = false;
    for (const field of document.querySelectorAll('input,textarea,[contenteditable]')) {
      if (restarting && (field.readOnly || field.disabled || state.isSearchField(field))) continue;
      // range/color は未操作でも値を持つ。変更されたコントロールだけを保護する。
      if (restarting && ['range','color'].includes(field.type) && !state.editedControls.has(field)) continue;
      if (field.type === 'file' && field.files && field.files.length) file = true;
      else if (field.isContentEditable && field.textContent.trim()) text = true;
      else if (field.tagName === 'TEXTAREA' && field.value.trim()) text = true;
      else if (field.tagName === 'INPUT' && !['hidden','button','submit','reset','checkbox','radio'].includes(field.type)
          && field.value) text = true;
    }
    if (file) busy.push('file');
    if (text) busy.push('text');
    const detail = unknown.concat(busy, info);
    const edited = !restarting && state.edited;
    if (edited) detail.push('edited');
    const suffix = detail.length ? ':' + detail.join('+') : '';
    if (unknown.length) return 'unknown' + suffix;
    if (busy.length) return 'busy' + suffix;
    // 入力後に DOM が空でも、サイト内部の未送信データは判別できないため破棄しない。
    return (edited ? 'retain' : 'safe') + suffix;
  } catch (_) { return 'unknown:error'; }
}
"""

SAFETY_PROBE = f'({_SAFETY_PROBE})(false);'

# 休止（Frozen）はページを保持したまま処理を止めるだけなので、未送信文があっても失わない。
# 休止させないのは、進行中の処理を止めてしまう場合（アップロード・ファイル選択・再生）と判定不能のとき。
_FREEZE_OK_BUSY = {"text"}
_INFO_REASONS = {"iframe", "progress", "edited"}


def probe_kind(result) -> str:
    """SAFETY_PROBE の戻り値から判定（safe / retain / busy / unknown）だけを取り出す。"""
    kind = str(result or "unknown").split(":", 1)[0]
    return kind if kind in ("safe", "retain", "busy") else "unknown"


def probe_reasons(result) -> set[str]:
    text = str(result or "")
    return set(text.split(":", 1)[1].split("+")) if ":" in text else set()


def probe_allows_freeze(result) -> bool:
    kind = probe_kind(result)
    if kind in ("safe", "retain"):
        return True
    if kind == "busy":
        return (probe_reasons(result) - _INFO_REASONS) <= _FREEZE_OK_BUSY
    return False


def probe_allows_discard(result) -> bool:
    """破棄（再読み込みあり）は、入力・送信・再生・判定不能のどれも無いときだけ。"""
    return probe_kind(result) == "safe"
