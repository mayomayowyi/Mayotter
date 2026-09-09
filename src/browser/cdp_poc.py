

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import threading
import time
import urllib.request
from typing import Any

def cdp_poc_enabled() -> bool:
    return os.environ.get("MAYOTTER_CDP_POC", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

def remote_debugging_port() -> int | None:
    raw = os.environ.get("QTWEBENGINE_REMOTE_DEBUGGING", "").strip()
    if not raw:
        return None
    if ":" in raw:
        try:
            return int(raw.rsplit(":", 1)[-1])
        except ValueError:
            return None
    try:
        return int(raw)
    except ValueError:
        return None

def ensure_remote_debugging_env(default_port: int = 9222) -> int | None:
    if not cdp_poc_enabled():
        return None
    if remote_debugging_port() is not None:
        return remote_debugging_port()
    os.environ["QTWEBENGINE_REMOTE_DEBUGGING"] = str(default_port)
    return default_port

def _log(msg: str) -> None:
    try:
        from src.media.debug_log import media_debug

        media_debug("CDP_POC", msg)
    except Exception:
        print(f"[CDP_POC] {msg}", flush=True)

class _MiniWebSocket:

    def __init__(self, host: str, port: int, path: str, timeout: float = 10.0) -> None:
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        self._sock.sendall(req.encode("ascii"))
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("CDP WebSocket handshake closed")
            buf += chunk
        header, _, rest = buf.partition(b"\r\n\r\n")
        if b"101" not in header.split(b"\r\n", 1)[0]:
            raise ConnectionError(f"CDP handshake failed: {header[:200]!r}")
        self._pending = rest
        self._lock = threading.Lock()
        self._next_id = 1

    def close(self) -> None:
        try:
            self._sock.close()
        except Exception:
            pass

    def _recv_frame(self) -> bytes:
        def read_exact(n: int) -> bytes:
            data = b""
            while len(data) < n:
                if self._pending:
                    take = min(n - len(data), len(self._pending))
                    data += self._pending[:take]
                    self._pending = self._pending[take:]
                    continue
                chunk = self._sock.recv(max(4096, n - len(data)))
                if not chunk:
                    raise ConnectionError("CDP socket closed")
                self._pending += chunk
            return data

        hdr = read_exact(2)
        b0, b1 = hdr[0], hdr[1]
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        length = b1 & 0x7F
        if length == 126:
            length = struct.unpack("!H", read_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", read_exact(8))[0]
        mask = read_exact(4) if masked else b""
        payload = bytearray(read_exact(length))
        if masked:
            for i in range(len(payload)):
                payload[i] ^= mask[i % 4]
        if opcode == 0x8:
            raise ConnectionError("CDP WebSocket close frame")
        if opcode == 0x9:
            self._send_frame(bytes(payload), opcode=0xA)
            return self._recv_frame()
        if opcode not in (0x1, 0x2, 0x0):
            return self._recv_frame()
        return bytes(payload)

    def _send_frame(self, payload: bytes, opcode: int = 0x1) -> None:
        # mask 必須
        mask = os.urandom(4)
        header = bytearray()
        header.append(0x80 | (opcode & 0x0F))
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", n))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", n))
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(header + masked)

    def send_json(self, obj: dict[str, Any]) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        with self._lock:
            self._send_frame(data)

    def recv_json(self) -> dict[str, Any]:
        raw = self._recv_frame()
        return json.loads(raw.decode("utf-8"))

    def call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 15.0) -> Any:
        with self._lock:
            msg_id = self._next_id
            self._next_id += 1
        payload: dict[str, Any] = {"id": msg_id, "method": method}
        if params is not None:
            payload["params"] = params
        self.send_json(payload)
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = max(0.1, deadline - time.time())
            self._sock.settimeout(remaining)
            try:
                msg = self.recv_json()
            except socket.timeout:
                continue
            if msg.get("id") == msg_id:
                if "error" in msg:
                    raise RuntimeError(f"CDP {method} error: {msg['error']}")
                return msg.get("result")
        raise TimeoutError(f"CDP {method} timed out")

def list_cdp_targets(port: int) -> list[dict[str, Any]]:
    url = f"http://127.0.0.1:{port}/json"
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))

def connect_page_ws(port: int, devtools_id: str) -> _MiniWebSocket:
    targets = list_cdp_targets(port)
    _log(f"targets_count={len(targets)}")
    match = None
    for t in targets:
        tid = str(t.get("id") or "")
        ws = t.get("webSocketDebuggerUrl") or ""
        if tid == devtools_id or devtools_id in ws or devtools_id in tid:
            match = t
            break
    if match is None:
        for t in targets:
            if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                match = t
                _log(f"fallback_target id={t.get('id')} title={t.get('title')!r}")
                break
    if match is None or not match.get("webSocketDebuggerUrl"):
        raise RuntimeError(f"No CDP page target for devtools_id={devtools_id!r}")

    ws_url = match["webSocketDebuggerUrl"]
    if not ws_url.startswith("ws://"):
        raise RuntimeError(f"Unexpected ws url: {ws_url}")
    without = ws_url[5:]
    hostport, _, path = without.partition("/")
    path = "/" + path
    if ":" in hostport:
        host, port_s = hostport.rsplit(":", 1)
        port_i = int(port_s)
    else:
        host, port_i = hostport, port
    _log(f"ws_connect host={host} port={port_i} path={path}")
    return _MiniWebSocket(host, port_i, path)

def find_file_input_backend_node(ws: _MiniWebSocket) -> dict[str, Any]:
    ws.call("DOM.enable")
    doc = ws.call("DOM.getDocument", {"depth": -1, "pierce": True})
    root_id = doc["root"]["nodeId"]

    selectors = [
        'input[data-testid="fileInput"]',
        'input[type="file"][accept*="video"]',
        'input[type="file"][accept*="image"]',
        'input[type="file"]',
    ]
    node_id = None
    used_sel = None
    for sel in selectors:
        try:
            res = ws.call("DOM.querySelector", {"nodeId": root_id, "selector": sel})
            nid = res.get("nodeId")
            if nid:
                node_id = nid
                used_sel = sel
                break
        except Exception as exc:
            _log(f"querySelector {sel!r} err={exc!r}")

    if not node_id:
        return {"found": False}

    desc = ws.call("DOM.describeNode", {"nodeId": node_id, "depth": 0})
    node = desc.get("node") or {}
    backend = node.get("backendNodeId")
    return {
        "found": True,
        "selector": used_sel,
        "nodeId": node_id,
        "backendNodeId": backend,
        "nodeName": node.get("nodeName"),
        "attributes": node.get("attributes"),
    }

def set_file_input_files(
    ws: _MiniWebSocket,
    *,
    files: list[str],
    node_id: int | None = None,
    backend_node_id: int | None = None,
) -> Any:
    params: dict[str, Any] = {"files": files}
    if backend_node_id is not None:
        params["backendNodeId"] = backend_node_id
    elif node_id is not None:
        params["nodeId"] = node_id
    else:
        raise ValueError("nodeId or backendNodeId required")
    _log(f"set_file_begin path={files!r} params_keys={list(params.keys())}")
    return ws.call("DOM.setFileInputFiles", params)

def eval_input_files_info(ws: _MiniWebSocket) -> dict[str, Any]:
    expr = r"""
    (() => {
      const input = document.querySelector('input[data-testid="fileInput"], input[type="file"]');
      if (!input || !input.files) return {length: -1};
      const f = input.files[0];
      return {
        length: input.files.length,
        name: f ? f.name : null,
        size: f ? f.size : null,
        type: f ? f.type : null
      };
    })()
    """
    res = ws.call("Runtime.evaluate", {"expression": expr, "returnByValue": True})
    return (res or {}).get("result", {}).get("value") or {}

def run_set_files_for_page(
    *,
    devtools_id: str,
    mp4_path: str,
    port: int | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "connected": False,
        "set_ok": False,
        "error": None,
    }
    port = port or remote_debugging_port()
    if not port:
        out["error"] = "no_remote_debugging_port"
        _log("abort reason=no_remote_debugging_port")
        return out
    if not os.path.isfile(mp4_path):
        out["error"] = "mp4_missing"
        _log(f"abort reason=mp4_missing path={mp4_path}")
        return out

    abs_path = os.path.abspath(mp4_path)
    _log(f"devtools_id={devtools_id}")
    _log(f"mp4_abs={abs_path} size={os.path.getsize(abs_path)}")

    ws = None
    try:
        for i in range(20):
            try:
                list_cdp_targets(port)
                break
            except Exception:
                time.sleep(0.25)
        else:
            out["error"] = "debug_server_unreachable"
            _log("abort reason=debug_server_unreachable")
            return out

        ws = connect_page_ws(port, str(devtools_id))
        out["connected"] = True
        _log("connected=True")

        try:
            ver = ws.call("Browser.getVersion")
            out["browser_version"] = ver
            _log(f"browser_version={ver}")
        except Exception as exc:
            _log(f"Browser.getVersion skipped/err={exc!r}")
            try:
                ws.call("Runtime.evaluate", {"expression": "1+1", "returnByValue": True})
                _log("connected=True runtime_ping_ok")
            except Exception as exc2:
                out["error"] = f"ping_failed:{exc2!r}"
                _log(f"ping_failed={exc2!r}")
                return out

        info = find_file_input_backend_node(ws)
        _log(f"file_input_found={info.get('found')} selector={info.get('selector')}")
        _log(
            f"nodeId={info.get('nodeId')} backendNodeId={info.get('backendNodeId')}"
        )
        out["file_input"] = info
        if not info.get("found"):
            out["error"] = "file_input_not_found"
            return out

        result = set_file_input_files(
            ws,
            files=[abs_path],
            node_id=info.get("nodeId"),
            backend_node_id=info.get("backendNodeId"),
        )
        out["set_result"] = result
        out["set_ok"] = True
        _log(f"set_file_result={result!r}")

        try:
            files_info = eval_input_files_info(ws)
            out["input_files_after"] = files_info
            _log(f"input_files_after={files_info}")
        except Exception as exc:
            _log(f"input_files_after_err={exc!r}")

        return out
    except Exception as exc:
        out["error"] = repr(exc)
        _log(f"fatal={exc!r}")
        return out
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
            _log("disconnected")
