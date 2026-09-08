from __future__ import annotations

import os
import sys
import time

def main() -> int:
    os.environ.setdefault("MAYOTTER_MEDIA_DEBUG", "1")
    from src.media.debug_log import media_debug, media_log_path

    media_debug("REC", f"recorder_test start log={media_log_path()}")

    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer

    app = QApplication(sys.argv)

    from src.media.recorder import AudioRecorder

    rec = AudioRecorder()
    result: dict = {"wav": None, "err": None}

    def on_started():
        media_debug("REC", "test started signal")

    def on_level(peak, rms):
        media_debug("REC", f"test level peak={peak:.3f} rms={rms:.3f}")

    def on_stopped(path):
        result["wav"] = path
        media_debug("REC", f"test stopped wav={path}")
        app.quit()

    def on_failed(msg):
        result["err"] = msg
        media_debug("REC", f"test failed {msg}")
        app.quit()

    rec.started.connect(on_started)
    rec.level.connect(on_level)
    rec.stopped.connect(on_stopped)
    rec.failed.connect(on_failed)

    def stop_later():
        media_debug("REC", "test stop_later")
        rec.stop()

    rec.start()
    QTimer.singleShot(3000, stop_later)
    QTimer.singleShot(8000, app.quit)
    app.exec()

    if result["err"]:
        print("FAILED:", result["err"])
        return 1
    if result["wav"]:
        print("OK:", result["wav"])
        return 0
    print("NO RESULT")
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
