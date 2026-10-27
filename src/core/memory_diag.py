"""メモリ診断（opt-in）。環境変数 MAYOTTER_MEMORY_DIAG=1 のときだけ記録する。

記録先は edition の logs/memory_diag.jsonl（1 行 1 JSON、既存の休止確認タイマーで 60 秒ごと）。
URL はホスト種別（x.com / grok.com / other）のみ、Cookie・認証情報・入力内容は記録しない。
集計表示: python -m src.core.memory_diag summarize <memory_diag.jsonl>
外部から測定（変更前のコードにも使える）:
    python -m src.core.memory_diag sample [--pid PID] [--interval 60] [--out FILE]
    本体は「QtWebEngineProcess を直接の子に持つプロセス」として特定する。PID 省略時は
    src.app.main で起動中の Python か Mayotter.exe とその子孫から探す（venv / py ランチャーの
    親プロセスを本体と誤認しない）。一意に決まらなければエラーにする。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ENV = "MAYOTTER_MEMORY_DIAG"
FILE_NAME = "memory_diag.jsonl"
MAX_BYTES = 5 * 1024 * 1024


def enabled() -> bool:
    return os.environ.get(ENV, "").strip().lower() in ("1", "true", "yes", "on")


def _mem_row(proc, main: bool) -> dict | None:
    import psutil
    try:
        try:
            mem = proc.memory_full_info()
        except psutil.AccessDenied:
            mem = proc.memory_info()
        # Windows: private = Private Bytes、uss = Private Working Set。
        return {"pid": proc.pid, "main": main, "private_bytes": getattr(mem, "private", None),
                "uss": getattr(mem, "uss", None), "rss": mem.rss}
    except psutil.Error:
        return None


def process_memory(pid: int | None = None) -> dict | None:
    """本体と QtWebEngineProcess 子プロセスのメモリ。psutil が無ければ None。"""
    try:
        import psutil
    except ImportError:
        return None
    me = psutil.Process(pid)
    rows = [_mem_row(me, True)]
    for child in me.children(recursive=True):
        try:
            if not child.name().lower().startswith("qtwebengine"):
                continue
        except psutil.Error:
            continue
        rows.append(_mem_row(child, False))
    rows = [r for r in rows if r is not None]

    def total(key, items):
        values = [r[key] for r in items if r.get(key) is not None]
        return sum(values) if values else None

    children = [r for r in rows if not r["main"]]
    return {"main": next((r for r in rows if r["main"]), None), "webengine": children,
            "webengine_private_bytes": total("private_bytes", children),
            "webengine_uss": total("uss", children)}


def append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists() and path.stat().st_size > MAX_BYTES:
            os.replace(path, path.with_name(path.name + ".1"))
    except OSError:
        pass
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def _mib(value) -> str:
    return "-" if value is None else f"{value / 2**20:.1f}"


def summarize(path: Path) -> str:
    lines = ["time      main_priv  main_uss  we_priv  we_uss  we_n  views  states / holds / retained_ws"]
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        proc = rec.get("process") or {}
        main = proc.get("main") or {}
        s = rec.get("summary") or {}
        lines.append(
            f"{rec.get('time', '')[11:19]:9s} {_mib(main.get('private_bytes')):>9s} {_mib(main.get('uss')):>9s}"
            f" {_mib(proc.get('webengine_private_bytes')):>8s} {_mib(proc.get('webengine_uss')):>7s}"
            f" {len(proc.get('webengine') or []):>4d} {s.get('views', 0):>6d}  {s.get('states')}"
            f" / {s.get('holds')} / {s.get('retained_workspaces')}")
    return "\n".join(lines)


def _is_webengine(proc) -> bool:
    import psutil
    try:
        return proc.name().lower().startswith("qtwebengine")
    except psutil.Error:
        return False


def _owns_webengine(proc) -> bool:
    import psutil
    try:
        return any(_is_webengine(child) for child in proc.children())
    except psutil.Error:
        return False


def _launch_candidates() -> list:
    import psutil
    me = psutil.Process()
    skip = {me.pid} | {p.pid for p in me.parents()}
    found = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info["name"] or "").lower()
            cmd = " ".join(proc.info["cmdline"] or [])
        except psutil.Error:
            continue
        if proc.info["pid"] in skip:
            continue
        if name.startswith("mayotter") or ("src.app.main" in cmd and "python" in name):
            found.append(proc)
    return found


def resolve_app_process(pid: int | None = None):
    """QtWebEngineProcess を直接の子に持つ Mayotter 本体を返す。一意でなければ LookupError。"""
    import psutil
    if pid is not None:
        try:
            roots = [psutil.Process(pid)]
        except psutil.Error as exc:
            raise LookupError(f"PID {pid} のプロセスを開けません: {exc}") from exc
    else:
        roots = _launch_candidates()
    owners = {}
    for root in roots:
        try:
            family = [root] + root.children(recursive=True)
        except psutil.Error:
            continue
        for proc in family:
            if not _is_webengine(proc) and _owns_webengine(proc):
                owners[proc.pid] = proc
    if len(owners) == 1:
        return next(iter(owners.values()))
    where = f"PID {pid} とその子孫" if pid is not None else "起動中の Mayotter"
    if not owners:
        raise LookupError(f"{where}に、QtWebEngineProcess を子に持つ本体が見つかりません。"
                          "Mayotter の起動完了後に実行するか、タスクマネージャーの PID を --pid で指定してください。")
    raise LookupError(f"{where}に本体の候補が複数あります（PID {sorted(owners)}）。--pid で指定してください。")


def sample(pid: int | None, interval: float, out: Path, count: int | None = None) -> None:
    import time
    from datetime import datetime
    try:
        app = resolve_app_process(pid)
    except LookupError as exc:
        raise SystemExit(str(exc)) from exc
    if pid is not None and app.pid != pid:
        print(f"PID {pid} の子プロセス PID {app.pid} を本体として測定します。", flush=True)
    else:
        print(f"本体 PID {app.pid} を測定します。", flush=True)
    done = 0
    while count is None or done < count:
        try:
            proc = process_memory(app.pid)
        except Exception as exc:
            raise SystemExit(f"本体 PID {app.pid} を測定できません（終了した可能性があります）: {exc}") from exc
        record = {"time": datetime.now().isoformat(timespec="seconds"), "pid": app.pid,
                  "requested_pid": pid, "process": proc}
        append(out, record)
        main = (proc or {}).get("main") or {}
        print(f"{record['time']} main_private={_mib(main.get('private_bytes'))}MiB "
              f"main_uss={_mib(main.get('uss'))}MiB "
              f"webengine_private={_mib((proc or {}).get('webengine_private_bytes'))}MiB "
              f"webengine_uss={_mib((proc or {}).get('webengine_uss'))}MiB "
              f"webengine_n={len((proc or {}).get('webengine') or [])}", flush=True)
        done += 1
        if count is None or done < count:
            time.sleep(interval)


def main(argv: list[str]) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="python -m src.core.memory_diag")
    sub_parsers = parser.add_subparsers(dest="command", required=True)
    summary_parser = sub_parsers.add_parser("summarize")
    summary_parser.add_argument("file", type=Path)
    sample_parser = sub_parsers.add_parser("sample")
    sample_parser.add_argument("--pid", type=int)
    sample_parser.add_argument("--interval", type=float, default=60.0)
    sample_parser.add_argument("--count", type=int)
    sample_parser.add_argument("--out", type=Path, default=Path("memory_sample.jsonl"))
    args = parser.parse_args(argv)
    if args.command == "summarize":
        print(summarize(args.file))
    else:
        sample(args.pid, args.interval, args.out, args.count)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
