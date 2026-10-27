@echo off
rem Safe release entrypoint: build ZIP and per-user Inno Setup EXE together.
rem No existing output directory is deleted or overwritten.
setlocal EnableExtensions
pushd "%~dp0.."
if errorlevel 1 exit /b 1
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python is not available in PATH.
  popd
  exit /b 1
)
python packaging\build_release.py %*
set "RC=%ERRORLEVEL%"
popd
endlocal & exit /b %RC%
