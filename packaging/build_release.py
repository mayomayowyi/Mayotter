"""Build ZIP and per-user Setup from one clean PyInstaller onedir tree."""
from __future__ import annotations

import argparse
import ast
from datetime import datetime
import hashlib
import json
import os
import stat
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / 'packaging'
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(PACKAGING) not in sys.path:
    sys.path.insert(0, str(PACKAGING))


def release_version() -> str:
    for node in ast.parse((ROOT / 'src/core/version.py').read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'APP_VERSION' for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError('APP_VERSION was not found')


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(stage: Path) -> dict[str, str]:
    forbidden = {'data', 'data_dev', 'tests', 'logs', 'profiles', 'audio_visual', 'audio_visual_dev',
                 'update_tmp', '.git', '.venv', 'build', 'cache', 'packaging', 'diagnostics',
                 'mayotter-installed.ini', 'unins000.exe', 'unins000.dat'}
    if any((stage / name).exists() for name in forbidden):
        raise ValueError('The stage contains user data or installer metadata')
    required = ['Mayotter.exe', '_internal', 'tools/ffmpeg/ffmpeg.exe',
                'tools/denoise/DeepFilterNet3_onnx.tar.gz',
                'tools/denoise/LICENSE-MIT.txt', 'tools/denoise/LICENSE-APACHE.txt',
                'licenses/THIRD_PARTY_NOTICES.txt',
                'licenses/third_party_manifest.json',
                '_internal/onnxruntime', '_internal/numpy']
    for name in required:
        if not (stage / name).exists():
            raise ValueError(f'Missing runtime component: {name}')
    from src.media.denoise import MODEL_SHA256
    if sha256(stage / 'tools/denoise/DeepFilterNet3_onnx.tar.gz') != MODEL_SHA256:
        raise ValueError('DeepFilterNet3 model hash differs from the application')
    files = {}
    for path in sorted(stage.rglob('*')):
        if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError(f'Symlinks are not permitted: {path}')
        if path.is_file() and path.name != 'program-files.sha256':
            files[path.relative_to(stage).as_posix()] = sha256(path)
    return files


def make_art(destination: Path, version: str, icon_file: Path) -> None:
    from PySide6.QtCore import Qt, QRect
    from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    if app.platformName() == 'offscreen':
        # offscreen にはフォントが無く、画像内の文字が四角（□）になる
        raise RuntimeError('Run the build on the Windows platform (not QT_QPA_PLATFORM=offscreen) so the wizard image text renders.')
    icon = QIcon(str(icon_file))
    destination.mkdir(parents=True)
    image = QImage(492, 942, QImage.Format.Format_ARGB32)
    image.fill(QColor('#0b111f'))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor('#f1f3f7'))
    painter.drawRoundedRect(110, 172, 272, 272, 40, 40)
    painter.drawPixmap(118, 180, icon.pixmap(256, 256))
    painter.setPen(QColor('#f1f3f7'))
    painter.setFont(QFont('Segoe UI', 32, QFont.Weight.DemiBold))
    painter.drawText(QRect(20, 455, 452, 85), Qt.AlignmentFlag.AlignCenter, 'Mayotter')
    painter.setPen(QColor('#aeb6c5'))
    painter.setFont(QFont('Segoe UI', 14))
    painter.drawText(QRect(20, 840, 452, 60), Qt.AlignmentFlag.AlignCenter, f'v{version}')
    painter.end()
    if not image.save(str(destination / 'wizard.png')):
        raise OSError('Could not write wizard image')
    logo = QImage(256, 256, QImage.Format.Format_ARGB32)
    logo.fill(Qt.GlobalColor.transparent)
    painter = QPainter(logo)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor('#f1f3f7'))
    painter.drawRoundedRect(0, 0, 256, 256, 38, 38)
    painter.drawPixmap(8, 8, icon.pixmap(240, 240))
    painter.end()
    logo.save(str(destination / 'logo.png'))
    # ウィザード右上の小さな画像: 縁に付かないよう透明な余白を持たせる（アイコン用の logo.png とは別）
    small = QImage(256, 256, QImage.Format.Format_ARGB32)
    small.fill(Qt.GlobalColor.transparent)
    painter = QPainter(small)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor('#f1f3f7'))
    painter.drawRoundedRect(40, 40, 176, 176, 30, 30)
    painter.drawPixmap(46, 46, icon.pixmap(164, 164))
    painter.end()
    small.save(str(destination / 'logo_small.png'))
    shutil.copyfile(icon_file, destination / 'mayotter.ico')


def find_iscc(given: str | None) -> Path:
    candidates = [given, os.environ.get('ISCC'), shutil.which('ISCC.exe'),
                  str(PACKAGING / 'cache/inno-7.1.0/compiler/ISCC.exe')]
    for folder in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
        base = Path(os.environ.get(folder, ''))
        candidates.extend(str(base / sub / 'ISCC.exe') for sub in
                          ('Inno Setup 7', 'Programs/Inno Setup 7'))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    raise FileNotFoundError('Inno Setup 7 is required; set ISCC to ISCC.exe')


def run(command: list, **kwargs) -> None:
    print(subprocess.list2cmdline([str(arg) for arg in command]), flush=True)
    subprocess.run([str(arg) for arg in command], check=True, cwd=ROOT, **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--iscc')
    parser.add_argument('--pydeps', type=Path)
    parser.add_argument('--stage', type=Path, help='Use an already clean release stage; do not rebuild')
    args = parser.parse_args()
    version = release_version()
    output = (args.output_dir or PACKAGING / 'output' / ('release-' + datetime.now().strftime('%Y%m%d-%H%M%S'))).resolve()
    iscc = find_iscc(args.iscc)
    output.mkdir(parents=True, exist_ok=False)
    work = output / 'work'
    work.mkdir()
    # Keep build subprocesses and the bundled audio self-test off the user's
    # normal TEMP directory. This is especially important during recovery.
    temporary = work / 'temp'
    temporary.mkdir()
    pip_cache = work / 'pip-cache'
    pip_cache.mkdir()
    for variable in ('TMP', 'TEMP', 'TMPDIR'):
        os.environ[variable] = str(temporary)
    os.environ['PIP_CACHE_DIR'] = str(pip_cache)
    # EXE（PyInstaller）と Setup が同じ ICO を使うよう、ビルドごとに元ロゴから作り直す（過去の ICO は再利用しない）
    from app_icon import write_ico
    icon_file = write_ico(work / 'icon/mayotter.ico')
    stage = output / 'Mayotter'
    if args.stage:
        inventory(args.stage)
        shutil.copytree(args.stage, stage)
    else:
        pydeps = (args.pydeps or PACKAGING / 'cache/pydeps-dfn').resolve()
        if not (pydeps / 'onnxruntime').is_dir() or not (pydeps / 'numpy').is_dir():
            pydeps = work / 'pydeps'
            run([sys.executable, '-m', 'pip', 'install', '--no-deps', '--require-hashes', '--only-binary=:all:',
                 '--target', pydeps, '-r', PACKAGING / 'requirements-dist.txt'])
        environment = {**os.environ, 'MAYOTTER_PYDEPS': str(pydeps), 'MAYOTTER_REQUIRE_DENOISE': '1',
                       'MAYOTTER_ICON': str(icon_file)}
        environment.pop('MAYOTTER_APP_VERSION', None)
        run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--distpath', work / 'dist',
             '--workpath', work / 'build', PACKAGING / 'mayotter.spec'], env=environment)
        shutil.move(str(work / 'dist/Mayotter'), stage)
        run([sys.executable, PACKAGING / 'stage_third_party.py', '--out', stage, '--pydeps', pydeps,
             '--ffmpeg-source', output / 'ffmpeg_source'])
        shutil.move(str(stage / 'THIRD_PARTY_NOTICES.txt'), stage / 'licenses/THIRD_PARTY_NOTICES.txt')
        environment = {**environment, 'PATH': os.environ['SystemRoot'] + '\\System32;' + os.environ['SystemRoot']}
        for name in ('PYTHONPATH', 'PYTHONHOME', 'MAYOTTER_FFMPEG', 'MAYOTTER_DENOISE_MODEL'):
            environment.pop(name, None)
        run([stage / 'Mayotter.exe', '--mayotter-selftest', output / 'selftest'], env=environment)
    (stage / 'release-info.json').write_text(json.dumps({'version': version}), encoding='utf-8')
    files = inventory(stage)
    (stage / 'program-files.sha256').write_text(''.join(f'{digest}  {name.replace(chr(47), chr(92))}\n'
                                                      for name, digest in files.items()), encoding='utf-8-sig')
    (output / 'payload-manifest.json').write_text(json.dumps({'version': version, 'files': files}, indent=2), encoding='utf-8')
    make_art(work / 'art', version, icon_file)
    archive = output / f'Mayotter_v{version}_Windows_x64.zip'
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for path in sorted(stage.rglob('*')):
            if path.is_file():
                zipped.write(path, path.relative_to(stage).as_posix())
    run([iscc, '/Qp', f'/DAppVersion={version}', f'/DStageDir={stage}', f'/DArtDir={work / "art"}',
         f'/O{output}', PACKAGING / 'mayotter.iss'])
    setup = output / f'Mayotter_Setup_v{version}_Windows_x64.exe'
    (output / 'SHA256SUMS.txt').write_text(''.join(f'{sha256(path)}  {path.name}\n' for path in (archive, setup)), encoding='ascii')
    from verify_release import check_release
    problems = check_release(output)
    if problems:
        raise RuntimeError('Release verification failed:\n' + '\n'.join(problems))
    from verify_release import measure_sizes
    (output / 'size-report.json').write_text(json.dumps(measure_sizes(stage), indent=2), encoding='utf-8')
    print(f'ZIP and Setup passed archive/hash/asset verification: {output}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
