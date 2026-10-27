"""Non-destructive verification of a completed Mayotter Windows release.

Usage: python packaging/verify_release.py <release-output-directory>
Does not start Mayotter, install software or access user profiles.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path, PurePosixPath
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.media.denoise import MODEL_FILENAME, MODEL_SHA256


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open('rb') as fp:
        for part in iter(lambda: fp.read(1024 * 1024), b''):
            hasher.update(part)
    return hasher.hexdigest()


def measure_sizes(root: Path) -> dict:
    groups = {}
    duplicates = {}
    unreadable = []
    count = 0
    for folder, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(folder) / d).is_symlink() and not (
            getattr((Path(folder) / d).lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)]
        for name in names:
            path = Path(folder) / name
            if path.is_symlink():
                continue
            relative = path.relative_to(root).as_posix()
            try:
                size = path.stat().st_size
            except OSError as exc:
                unreadable.append({'path': relative, 'operation': 'size', 'error': type(exc).__name__})
                continue
            group = '/'.join(relative.split('/')[:2]) if '/' in relative else '[files]'
            groups[group] = groups.get(group, 0) + size
            count += 1
            if size >= 1024 * 1024:
                duplicates.setdefault(size, []).append(relative)
    same = []
    for size, names in duplicates.items():
        if len(names) < 2:
            continue
        hashes = {}
        for name in names:
            try:
                hashes.setdefault(digest(root / name), []).append(name)
            except OSError as exc:
                unreadable.append({'path': name, 'operation': 'hash', 'error': type(exc).__name__})
        same.extend({'bytes_each': size, 'paths': paths} for paths in hashes.values() if len(paths) > 1)
    return {'path': str(root.resolve()), 'bytes': sum(groups.values()), 'files': count,
            'groups': dict(sorted(groups.items(), key=lambda item: -item[1])), 'duplicates': same,
            'unreadable': unreadable}


def check_release(release: Path) -> list[str]:
    errors: list[str] = []
    release = release.resolve()
    manifest = release / 'payload-manifest.json'
    if not manifest.is_file():
        return [f'Missing: {manifest}']
    try:
        info = json.loads(manifest.read_text(encoding='utf-8'))
        version = info['version']
        files = info['files']
        if not isinstance(version, str) or not isinstance(files, dict) or not files:
            raise ValueError('Invalid release metadata')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f'Invalid payload manifest: {exc}']

    stage = release / 'Mayotter'
    archive = release / f'Mayotter_v{version}_Windows_x64.zip'
    setup = release / f'Mayotter_Setup_v{version}_Windows_x64.exe'
    required = (
        'Mayotter.exe', 'tools/ffmpeg/ffmpeg.exe',
        'tools/denoise/' + MODEL_FILENAME,
        'licenses/THIRD_PARTY_NOTICES.txt',
        'licenses/third_party_manifest.json',
    )
    for name in required:
        if name not in files:
            errors.append(f'Missing from payload manifest: {name}')
    bad_roots = {'data', 'data_dev', 'profiles', 'tests', 'cache', 'logs', 'update_tmp', '.git'}
    if any(PurePosixPath(path).parts[0].lower() in bad_roots for path in files):
        errors.append('User data or development files are in the payload manifest')
    for name, expected in files.items():
        parts = PurePosixPath(name).parts
        if not parts or name.startswith('/') or '..' in parts or '\\' in name or ':' in name:
            errors.append(f'Unsafe payload path: {name!r}')
            continue
        target = stage.joinpath(*parts)
        if not target.is_file() or target.is_symlink():
            errors.append(f'Missing/nonregular payload file: {name}')
        elif digest(target) != expected:
            errors.append(f'Payload hash mismatch: {name}')
    if stage.is_dir():
        actual = {p.relative_to(stage).as_posix() for p in stage.rglob('*') if p.is_file()}
        extra = actual - set(files) - {'program-files.sha256'}
        if extra:
            errors.append('Unmanifested files: ' + ', '.join(sorted(extra)[:8]))
        if (stage / 'mayotter-installed.ini').exists():
            errors.append('Installer-only marker is inside portable payload')
        engine = [p for p in actual if p.endswith('/QtWebEngineProcess.exe') or p == '_internal/QtWebEngineProcess.exe']
        if not engine:
            errors.append('QtWebEngineProcess.exe missing from payload')
        if not any(p.startswith('_internal/onnxruntime/') for p in actual):
            errors.append('ONNX Runtime package missing from payload')
        if not any(p.startswith('_internal/numpy/') for p in actual):
            errors.append('NumPy package missing from payload')
        hashes = stage / 'program-files.sha256'
        if not hashes.is_file():
            errors.append('Missing program-files.sha256')
        else:
            entries = set(hashes.read_text(encoding='utf-8-sig').splitlines())
            expected_lines = {f"{h}  {n.replace('/', chr(92))}" for n, h in files.items()}
            if entries != expected_lines:
                errors.append('program-files.sha256 does not match payload manifest')
    model = stage / 'tools/denoise' / MODEL_FILENAME
    if model.is_file() and digest(model) != MODEL_SHA256:
        errors.append('DeepFilterNet3 model checksum mismatch')

    if not archive.is_file():
        errors.append(f'Missing ZIP: {archive.name}')
    else:
        try:
            with ZipFile(archive) as z:
                names = z.namelist()
                if z.testzip() is not None:
                    errors.append('Corrupt ZIP entry')
                if len(names) != len(set(names)):
                    errors.append('Duplicate ZIP entry names')
                all_names = set(names)
                if all_names != set(files) | {'program-files.sha256'}:
                    errors.append('ZIP file list differs from payload manifest')
                for name in names:
                    if name in files and hashlib.sha256(z.read(name)).hexdigest() != files[name]:
                        errors.append(f'ZIP hash mismatch: {name}')
                    elif name == 'program-files.sha256' and (stage / name).is_file():
                        if z.read(name) != (stage / name).read_bytes():
                            errors.append('ZIP program-files.sha256 mismatch')
        except (OSError, ValueError, KeyError) as exc:
            errors.append(f'Cannot validate ZIP: {exc}')

    if not setup.is_file() or setup.stat().st_size == 0:
        errors.append(f'Missing Setup EXE: {setup.name}')
    sums = release / 'SHA256SUMS.txt'
    if not sums.is_file():
        errors.append('Missing SHA256SUMS.txt')
    else:
        expected = {f'{digest(p)}  {p.name}' for p in (archive, setup) if p.is_file()}
        if set(sums.read_text(encoding='ascii').splitlines()) != expected:
            errors.append('Release SHA256SUMS.txt mismatch')
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('release', type=Path)
    parser.add_argument('--sizes-only', action='store_true', help='Measure this directory without running any program')
    args = parser.parse_args()
    if args.sizes_only:
        print(json.dumps(measure_sizes(args.release), ensure_ascii=True, indent=2))
        return 0
    errors = check_release(args.release)
    for item in errors:
        print('[FAIL]', item)
    if not errors:
        print('[OK] ZIP, Setup, manifest, runtime assets and checksums agree.')
        print('Note: this does not verify EXE startup, GUI, installer execution or licences.')
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
