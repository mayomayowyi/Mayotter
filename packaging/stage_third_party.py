"""Stage the bundled third-party components into the distribution folder.

Run by build_distribution.bat after PyInstaller (any OS for the verification build):

    python packaging/stage_third_party.py --out packaging/output/Mayotter --pydeps packaging/cache/pydeps

- FFmpeg (Gyan.dev build) -> <out>/tools/ffmpeg/ffmpeg.exe (+ LICENSE, build info, source info)
- Verified DeepFilterNet3 ONNX model -> <out>/tools/denoise/
- DeepFilterNet licence notices -> <out>/tools/denoise/ and <out>/licenses/DeepFilterNet/
- Licence files for onnxruntime and numpy -> <out>/licenses/python/
- <out>/THIRD_PARTY_NOTICES.txt and <out>/licenses/third_party_manifest.json
  (versions, download URLs and SHA-256 of every archive and staged file)

Every download is checked against the SHA-256 pinned in packaging/third_party.json; downloads
are cached in packaging/cache and reused. Nothing from PATH, WinGet or the system is used.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MANIFEST = ROOT / "packaging" / "third_party.json"
LICENSES_SRC = ROOT / "packaging" / "licenses"
# 簡体字中国語 UI 用フォント。mayotter.spec が src/ui/assets ごと同梱する
ZH_CN_FONT_DIR = "src/ui/assets/fonts"
ZH_CN_FONT_FILES = ("NotoSansSC-Regular.otf", "NotoSansSC-Medium.otf", "NotoSansSC-Bold.otf", "OFL.txt")


class StageError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(url: str, dest: Path, sha256: str, *, offline: bool = False) -> Path:
    """dest を用意する（キャッシュがハッシュ一致なら再利用、無ければ取得して照合）。"""
    sha256 = sha256.lower()
    if dest.is_file():
        if sha256_file(dest) == sha256:
            print(f"[stage] cached: {dest.name}")
            return dest
        print(f"[stage] cached file does not match the pinned SHA-256, discarding: {dest}")
        dest.unlink()
    if offline:
        raise StageError(f"{dest.name} is not in the cache and --offline was given ({dest})")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last: Exception | None = None
    for attempt in range(1, 4):
        try:
            print(f"[stage] downloading ({attempt}/3): {url}")
            req = urllib.request.Request(url, headers={"User-Agent": "Mayotter-build"})
            with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as fh:
                shutil.copyfileobj(resp, fh, 1 << 20)
            break
        except Exception as exc:  # retried, then reported
            last = exc
            print(f"[stage] download failed: {exc}")
    else:
        tmp.unlink(missing_ok=True)
        raise StageError(f"could not download {url}: {last}")
    got = sha256_file(tmp)
    if got != sha256:
        tmp.unlink(missing_ok=True)
        raise StageError(f"SHA-256 mismatch for {url}: expected {sha256}, got {got}")
    tmp.replace(dest)
    return dest


def _record(path: Path, out: Path) -> dict:
    return {"path": path.relative_to(out).as_posix(), "size": path.stat().st_size,
            "sha256": sha256_file(path)}


def _run_text(cmd: list[str]) -> str | None:
    try:
        kw: dict = {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace",
                    "timeout": 60}
        if sys.platform == "win32":
            kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        proc = subprocess.run(cmd, check=False, **kw)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


# --- FFmpeg -----------------------------------------------------------------------------

def _embedded_configuration(exe: Path) -> str:
    """ffmpeg の実行ファイルに埋め込まれた configure 引数（--enable-gpl ...）。"""
    import re
    data = exe.read_bytes()
    m = re.search(rb"--(?:enable-gpl|prefix|arch)[^\x00]{10,8000}", data)
    return m.group(0).decode("utf-8", "replace") if m else ""


def stage_ffmpeg(out: Path, cache: Path, spec: dict, *, zip_path: Path | None = None,
                 zip_sha256: str | None = None, offline: bool = False) -> dict:
    url, sha = spec["url"], spec["sha256"]
    if zip_path is not None:
        # 手元の ZIP を使う（ミラー・オフライン用）。照合するハッシュは明示させる
        if not zip_sha256:
            raise StageError("--ffmpeg-zip needs --ffmpeg-sha256")
        url, sha = zip_path.resolve().as_uri(), zip_sha256.lower()
        if sha256_file(zip_path) != sha:
            raise StageError(f"SHA-256 mismatch for {zip_path}")
        archive = zip_path
    else:
        archive = fetch(url, cache / "ffmpeg" / Path(url).name, sha, offline=offline)

    dest = out / "tools" / "ffmpeg"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    root = spec["archive_root"].rstrip("/")
    staged = []
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        for member, target in spec["files"].items():
            name = f"{root}/{member}"
            if name not in names:
                raise StageError(f"{name} not found in {archive.name}")
            path = dest / target
            with zf.open(name) as src, open(path, "wb") as fh:
                shutil.copyfileobj(src, fh, 1 << 20)
            staged.append(path)
    exe = dest / "ffmpeg.exe"
    if os.name != "nt":
        exe.chmod(0o755)

    # 実際に同梱したバイナリの構成（バージョン・configure・ライブラリ）を記録する
    version = _run_text([str(exe), "-hide_banner", "-version"])
    buildconf = _run_text([str(exe), "-hide_banner", "-buildconf"])
    embedded = _embedded_configuration(exe)
    if "--enable-nonfree" in embedded:
        raise StageError("the FFmpeg build has --enable-nonfree and must not be redistributed")
    info = dest / "BUILD_INFO.txt"
    if version:
        info.write_text(
            "# Output of the bundled ffmpeg.exe (-version / -buildconf), recorded at build time.\n\n"
            + version + "\n" + (buildconf or ""), encoding="utf-8")
        if "--enable-nonfree" in version or "--enable-nonfree" in (buildconf or ""):
            raise StageError("the FFmpeg build has --enable-nonfree and must not be redistributed")
        if f"version {spec['version']}" not in version.splitlines()[0]:
            print(f"[stage] WARNING: ffmpeg reports {version.splitlines()[0]!r}, expected {spec['version']}")
    else:
        # 別 OS での構築など、実行できない場合はバイナリに埋め込まれた configure を記録する
        info.write_text(
            "# ffmpeg.exe could not be run on the build machine; configuration read from the binary.\n"
            f"# Archive: {Path(url).name}  SHA-256 {sha}\n\nconfiguration: {embedded or 'not found'}\n",
            encoding="utf-8")
        print("[stage] NOTE: bundled ffmpeg not runnable here; recorded its embedded configuration")
    staged.append(info)

    src = spec.get("source", {})
    readme = dest / "README.txt"
    readme.write_text(
        f"FFmpeg {spec['version']} (https://ffmpeg.org/) is included to convert audio to MP4.\n"
        f"Build: {spec['name']}\n"
        f"Licence: {spec['license']}. See LICENSE.txt (GNU GPL version 3).\n"
        "Exact build configuration and bundled library versions: BUILD_INFO.txt and BUILD_README.txt.\n"
        "\n"
        f"Binary archive: {url}\n"
        f"Archive SHA-256: {sha}\n"
        f"ffmpeg.exe SHA-256: {sha256_file(exe)}\n"
        "\n"
        "Corresponding source code\n"
        f"- FFmpeg commit {src.get('commit', '?')} (from BUILD_README.txt): {src.get('url', '')}\n"
        f"  Release {spec['version']}: {src.get('release_tarball', 'https://ffmpeg.org/download.html')}\n"
        f"- Build scripts and library list: {src.get('build_info', 'https://www.gyan.dev/ffmpeg/builds/')}\n"
        "- The external libraries linked into this build and their versions are listed in\n"
        "  BUILD_README.txt and BUILD_INFO.txt.\n"
        "The source archive used for this release is distributed alongside the Mayotter\n"
        "release (ffmpeg_source folder) by the distributor.\n",
        encoding="utf-8")
    staged.append(readme)
    print(f"[stage] FFmpeg {spec['version']} -> {exe}")
    return {"component": "ffmpeg", "version": spec["version"], "license": spec["license"],
            "archive": {"url": url, "sha256": sha}, "files": [_record(p, out) for p in staged]}


def stage_ffmpeg_source(dest_dir: Path, cache: Path, spec: dict, *, offline: bool = False) -> dict:
    """GPL の対応ソース（FFmpeg 本体）を配布物とは別のフォルダに用意する。"""
    src = spec["source"]
    url = src["url"]
    sha = (src.get("sha256") or "").lower()
    archive = cache / "ffmpeg" / Path(url).name
    if sha:
        archive = fetch(url, archive, sha, offline=offline)
    elif not archive.is_file():
        if offline:
            raise StageError(f"{archive.name} is not in the cache")
        # 公式の SHA-256 を固定していない場合は、取得したもののハッシュを記録して追跡する
        archive.parent.mkdir(parents=True, exist_ok=True)
        print(f"[stage] downloading (hash not pinned, will be recorded): {url}")
        with urllib.request.urlopen(url, timeout=300) as resp, open(archive, "wb") as fh:
            shutil.copyfileobj(resp, fh, 1 << 20)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / archive.name
    shutil.copy2(archive, target)
    got = sha256_file(target)
    print(f"[stage] FFmpeg source -> {target} (SHA-256 {got})")
    return {"component": "ffmpeg-source", "url": url, "sha256": got, "pinned": bool(sha),
            "path": str(target)}


# --- DeepFilterNet3 ---------------------------------------------------------------

def stage_model(out: Path, cache: Path, spec: dict, *, offline: bool = False) -> dict:
    """Stage the archived ONNX model only after verifying its pinned digest."""
    from src.media.denoise import MODEL_FILENAME, MODEL_SHA256

    if (spec["file"], spec["sha256"].lower()) != (MODEL_FILENAME, MODEL_SHA256):
        raise StageError("DeepFilterNet3 manifest and application model hash disagree")

    local = ROOT / "tools" / "denoise" / MODEL_FILENAME
    if local.is_file():
        if sha256_file(local) != MODEL_SHA256:
            raise StageError(f"local model checksum mismatch: {local}")
        archive = local
    else:
        archive = fetch(spec["url"], cache / "denoise" / MODEL_FILENAME,
                        MODEL_SHA256, offline=offline)

    source_lic = LICENSES_SRC / "DeepFilterNet"
    needed = {"LICENSE-MIT": "LICENSE-MIT.txt", "LICENSE-APACHE": "LICENSE-APACHE.txt"}
    for filename in needed:
        if not (source_lic / filename).is_file():
            raise StageError(f"missing DeepFilterNet licence source: {source_lic / filename}")

    target = out / "tools" / "denoise"
    target.mkdir(parents=True, exist_ok=True)
    model = target / MODEL_FILENAME
    if model.resolve() != archive.resolve():
        shutil.copy2(archive, model)
    if sha256_file(model) != MODEL_SHA256:
        raise StageError("staged DeepFilterNet3 model checksum mismatch")

    placed = [model]
    lic_dest = out / "licenses" / "DeepFilterNet"
    lic_dest.mkdir(parents=True, exist_ok=True)
    for source, destname in needed.items():
        original = source_lic / source
        for folder, name in ((target, destname), (lic_dest, source)):
            destination = folder / name
            shutil.copy2(original, destination)
            placed.append(destination)

    notice = target / "NOTICE.txt"
    notice.write_text(
        "DeepFilterNet3 ONNX model (unmodified)\n"
        f"Source: {spec['url']}\n"
        f"SHA-256: {MODEL_SHA256}\n"
        "DeepFilterNet source code: MIT OR Apache-2.0 (licences enclosed).\n"
        "The trained weights' redistribution permission has not been independently confirmed.\n"
        "Review the upstream model terms before publicly distributing this bundle.\n",
        encoding="utf-8",
    )
    placed.append(notice)
    return {"component": "deepfilternet3", "sha256": MODEL_SHA256,
            "model_url": spec["url"], "licence_note": spec["license"],
            "files": [_record(path, out) for path in placed]}


# --- Python packages ---------------------------------------------------------------------

_LICENSE_NAMES = ("license", "licence", "copying", "notice", "thirdpartynotices", "authors", "privacy")


def stage_python_licenses(out: Path, pydeps: Path, packages: dict) -> list[dict]:
    from importlib.metadata import PathDistribution

    results = []
    for name, version in packages.items():
        infos = list(pydeps.glob(f"{name}-*.dist-info"))
        if len(infos) != 1:
            raise StageError(f"{name} is not installed in {pydeps}")
        dist = PathDistribution(infos[0])
        if dist.version != version:
            raise StageError(f"{name} {dist.version} in {pydeps}, pinned {version}")
        dest = out / "licenses" / "python" / f"{name}-{version}"
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        copied = []
        for rel in dist.files or []:
            low = Path(str(rel)).name.lower()
            if not low.startswith(_LICENSE_NAMES):
                continue
            src = Path(str(dist.locate_file(rel)))
            if not src.is_file():
                continue
            parts = Path(str(rel)).parts
            # dist-info/licenses/<path> は元の階層のまま、パッケージ直下の LICENSE 等は直下へ
            if "licenses" in parts:
                target = dest.joinpath(*parts[parts.index("licenses") + 1:])
            else:
                target = dest / Path(str(rel)).name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            copied.append(target)
        if not copied:
            raise StageError(f"no licence files found for {name}")
        results.append({"component": name, "version": version, "license": dist.metadata.get("License-Expression")
                        or dist.metadata.get("License") or "see licence files",
                        "files": [_record(p, out) for p in copied]})
        print(f"[stage] licences: {name} {version} ({len(copied)} files)")
    return results


# --- Notices / verification --------------------------------------------------------------

def write_notices(out: Path, manifest: dict, records: list[dict]) -> None:
    ff, model = manifest["ffmpeg"], manifest["deepfilternet3"]
    py = manifest["python"]["packages"]
    text = f"""Mayotter - third-party components
==================================

Licences, origin URLs, versions and file checksums are recorded in
licenses/third_party_manifest.json.

1. FFmpeg {ff['version']} ({ff['name']})
   Licence: {ff['license']}
   Files: tools/ffmpeg/ (LICENSE.txt, README.txt, BUILD_INFO.txt, BUILD_README.txt)
   Corresponding-source obligation: see packaging/licenses/README.md in the source tree.

2. DeepFilterNet3 ONNX ({model['file']})
   Code: MIT OR Apache-2.0; see licenses/DeepFilterNet/
   Model archive: tools/denoise/{model['file']}
   Trained-weight redistribution terms have NOT been conclusively verified.
   Review the upstream terms before public distribution.

3. ONNX Runtime {py['onnxruntime']}
   Licences: licenses/python/onnxruntime-{py['onnxruntime']}/

4. NumPy {py['numpy']}
   Licences: licenses/python/numpy-{py['numpy']}/

5. Noto Sans SC 2.004 (notofonts/noto-cjk SC subset OTF, unmodified)
   Licence: SIL Open Font License 1.1
   Files: {ZH_CN_FONT_DIR}/ ({', '.join(ZH_CN_FONT_FILES)})
"""
    (out / "THIRD_PARTY_NOTICES.txt").write_text(text, encoding="utf-8")
    data = {"generated": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "build_python": sys.version.split()[0], "build_platform": sys.platform,
            "components": records}
    path = out / "licenses" / "third_party_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def verify(out: Path) -> list[str]:
    """Check bundled runtime components; accept notices before or after placement."""
    problems: list[str] = []
    must = ["tools/ffmpeg/ffmpeg.exe", "tools/ffmpeg/LICENSE.txt",
            "tools/ffmpeg/README.txt", "tools/ffmpeg/BUILD_INFO.txt",
            "tools/denoise/DeepFilterNet3_onnx.tar.gz", "tools/denoise/NOTICE.txt",
            "tools/denoise/LICENSE-MIT.txt", "tools/denoise/LICENSE-APACHE.txt",
            "licenses/DeepFilterNet/LICENSE-MIT", "licenses/DeepFilterNet/LICENSE-APACHE",
            "licenses/third_party_manifest.json"]
    for rel in must:
        if not (out / rel).is_file():
            problems.append(f"missing {rel}")
    if not ((out / "THIRD_PARTY_NOTICES.txt").is_file() or
            (out / "licenses" / "THIRD_PARTY_NOTICES.txt").is_file()):
        problems.append("missing THIRD_PARTY_NOTICES.txt")

    model = out / "tools" / "denoise" / "DeepFilterNet3_onnx.tar.gz"
    if model.is_file():
        from src.media.denoise import MODEL_SHA256
        if sha256_file(model) != MODEL_SHA256:
            problems.append("DeepFilterNet3 model SHA-256 mismatch")

    internal = out / "_internal" if (out / "_internal").is_dir() else out
    for pkg in ("numpy", "onnxruntime"):
        if not (internal / pkg).is_dir():
            problems.append(f"{pkg} not found in the bundle")
    for rel in ZH_CN_FONT_FILES:
        if not (internal / ZH_CN_FONT_DIR / rel).is_file():
            problems.append(f"missing {ZH_CN_FONT_DIR}/{rel} in the bundle")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, type=Path, help="distribution folder (contains Mayotter.exe)")
    ap.add_argument("--cache", type=Path, default=ROOT / "packaging" / "cache")
    ap.add_argument("--pydeps", type=Path, default=ROOT / "packaging" / "cache" / "pydeps")
    ap.add_argument("--ffmpeg-zip", type=Path, help="use this local FFmpeg ZIP instead of downloading")
    ap.add_argument("--ffmpeg-sha256", help="SHA-256 that --ffmpeg-zip must match")
    ap.add_argument("--ffmpeg-source", type=Path, help="also put the FFmpeg source archive in this folder")
    ap.add_argument("--offline", action="store_true", help="only use files already in the cache")
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args(argv)

    out = args.out.resolve()
    if not out.is_dir():
        print(f"[stage] ERROR: {out} does not exist")
        return 1
    if not args.verify_only:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        try:
            records = [
                stage_ffmpeg(out, args.cache, manifest["ffmpeg"], zip_path=args.ffmpeg_zip,
                             zip_sha256=args.ffmpeg_sha256, offline=args.offline),
                stage_model(out, args.cache, manifest["deepfilternet3"], offline=args.offline),
                *stage_python_licenses(out, args.pydeps.resolve(), manifest["python"]["packages"]),
            ]
            if args.ffmpeg_source:
                records.append(stage_ffmpeg_source(args.ffmpeg_source.resolve(), args.cache,
                                                   manifest["ffmpeg"], offline=args.offline))
        except StageError as exc:
            print(f"[stage] ERROR: {exc}")
            return 1
        write_notices(out, manifest, records)
    problems = verify(out)
    for p in problems:
        print(f"[stage] ERROR: {p}")
    if not problems:
        print("[stage] third-party components verified")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
