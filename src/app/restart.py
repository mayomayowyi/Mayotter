from __future__ import annotations

import base64
import os
from pathlib import Path
import subprocess
import sys


def restart_command() -> list[str]:
    if getattr(sys, 'frozen', False):
        return [sys.executable, *sys.argv[1:]]
    return [sys.executable, *sys.orig_argv[1:]]


def launch_after_exit() -> None:
    command = restart_command()

    def literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    # 別プロセスで親の終了を待つ。固定時間の待機やロックの先取りは行わない。
    script = f"""$ErrorActionPreference = 'Stop'
$parentProcess = $null
try {{
    $parentProcess = [System.Diagnostics.Process]::GetProcessById({os.getpid()})
}} catch [System.ArgumentException] {{}}
if ($null -ne $parentProcess) {{
    $parentProcess.WaitForExit()
    $parentProcess.Dispose()
}}
$start = New-Object System.Diagnostics.ProcessStartInfo
$start.FileName = {literal(command[0])}
$start.Arguments = {literal(subprocess.list2cmdline(command[1:]))}
$start.WorkingDirectory = {literal(os.getcwd())}
$start.UseShellExecute = $false
try {{
    [System.Diagnostics.Process]::Start($start) | Out-Null
}} catch {{
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Mayotter') | Out-Null
    exit 1
}}
"""
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    environment = os.environ.copy()
    if getattr(sys, 'frozen', False):
        environment['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    subprocess.Popen(
        [str(powershell), '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden',
         '-EncodedCommand', base64.b64encode(script.encode('utf-16-le')).decode('ascii')],
        env=environment,
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
