"""Prepare the native Pango runtime required by WeasyPrint on Windows."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


RUNTIME_VERSION = "msys2-mingw64-pango-20260718"
RUNTIME_DIRECTORY_NAME = f"weasyprint-{RUNTIME_VERSION}"
MSYS2_REPOSITORY = "https://repo.msys2.org/mingw/mingw64"
DOWNLOAD_WORKERS = 4
DOWNLOAD_TIMEOUT_SECONDS = 120

# Runtime closure for mingw-w64-x86_64-pango, pinned to hashes from the
# signed MSYS2 mingw64 repository database. Python-only glib2 dependencies
# are excluded because WeasyPrint only loads the native DLLs.
PACKAGES = (
    ("mingw-w64-x86_64-brotli-1.2.0-1-any.pkg.tar.zst", "f5f2f7e723a08378241d15f0537386950c1a48e2d82bc47bedd632bd61852aba"),
    ("mingw-w64-x86_64-bzip2-1.0.8-3-any.pkg.tar.zst", "653ec97c18dc139ca94e2b4b9d161a9b4d9e77ceb18dfb064eb95ef2a71171b6"),
    ("mingw-w64-x86_64-cairo-1.18.4-4-any.pkg.tar.zst", "1487120562e42601a8462d9953098f685c513999a2e472a3524fa96434be3290"),
    ("mingw-w64-x86_64-expat-2.8.2-1-any.pkg.tar.zst", "9f25550c738b7695164f4ea237af40512d7c63b4cd97aa417f3e0214930aca4f"),
    ("mingw-w64-x86_64-fontconfig-2.18.2-1-any.pkg.tar.zst", "dfba8c17600314f2f6fb11b8b963539d89b66d1953ed20a62286bea27b520bee"),
    ("mingw-w64-x86_64-freetype-2.14.3-1-any.pkg.tar.zst", "b3e310f457c90348fd14b8c1085e9c036016d168812a657fec21f496f7e3de99"),
    ("mingw-w64-x86_64-fribidi-1.0.16-1-any.pkg.tar.zst", "82d4f9e431082d2ac2fa7b9eddd73aa0c073bf8ae66b7d137195797ec543dffa"),
    ("mingw-w64-x86_64-gcc-libs-16.1.0-5-any.pkg.tar.zst", "aa560f5438c35b71c3e7b24fd5becbca028f70c5b4d1f1697a86ff80fec947da"),
    ("mingw-w64-x86_64-gettext-runtime-1.0-1-any.pkg.tar.zst", "be68d7f260633284b910c588c6d82ee304a81c8817a686d2cd9df83f872c27af"),
    ("mingw-w64-x86_64-glib2-2.88.2-1-any.pkg.tar.zst", "5855fb26ca86405a1826e2a7b35c068860225bce6a53c698f7094105ad25271a"),
    ("mingw-w64-x86_64-graphite2-1.3.15-1-any.pkg.tar.zst", "6ad20d6c16e559f7c4b06fe71248e1201c7edf494d04e5721ed7f9b3f7fd1f74"),
    ("mingw-w64-x86_64-harfbuzz-14.2.1-1-any.pkg.tar.zst", "d378464a57f52e52c6016822bf718c6d93c2783c4f778f2b685da6008a969632"),
    ("mingw-w64-x86_64-libdatrie-0.2.14-1-any.pkg.tar.zst", "fbbf30e9a911c1139ba5c38c5ae008309dd912f6c6b1e05f4310ec698e1b1339"),
    ("mingw-w64-x86_64-libffi-3.7.1-1-any.pkg.tar.zst", "a016df13c67a0438a0b94267f2911c68fd4d7216b4d45fbac7a66af41fe78f44"),
    ("mingw-w64-x86_64-libiconv-1.19-1-any.pkg.tar.zst", "21e334d0911f25de75d3e18e0697648bcecfa9658256d600cad0827d719c2f35"),
    ("mingw-w64-x86_64-libpng-1.6.58-1-any.pkg.tar.zst", "d8ae6066f99b3a04b83b8013b554a26a205d7e68580b80823c173ed045ba76a5"),
    ("mingw-w64-x86_64-libthai-0.1.30-1-any.pkg.tar.zst", "e8cfad91934e24e9a88221b66f2d1c5a310c952ef86631107a632d3ff1738211"),
    ("mingw-w64-x86_64-libwinpthread-14.0.0.r190.g96fb1bff7-1-any.pkg.tar.zst", "52e84dbcef7352e3ce4aa04a24d320d8039b0ddc59b0603ccea00f1a975e8374"),
    ("mingw-w64-x86_64-lzo2-2.10-3-any.pkg.tar.zst", "445115c31e91486801af9493278c0eb86c6194c2644a54e92d5afac10edea630"),
    ("mingw-w64-x86_64-pango-1.58.0-1-any.pkg.tar.zst", "9344fd35e7c1a14d8220cef4d251c631a22509766aa1134ee446f07333db6235"),
    ("mingw-w64-x86_64-pcre2-10.47-1-any.pkg.tar.zst", "7c9e3cd47af02a096c0c1810d1021f63c5fb1d22dbec91fa019d8b37eda00d98"),
    ("mingw-w64-x86_64-pixman-0.46.4-3-any.pkg.tar.zst", "435715dd1ca4c55873cf3c38d644615196bc2d238e3366f8ff81cc0811260eb2"),
    ("mingw-w64-x86_64-tzdata-2026c-1-any.pkg.tar.zst", "502e6f8e65c554e717f6c749dcbb70cc9b85ed94b01c151c26a0c25235e63df2"),
    ("mingw-w64-x86_64-wineditline-2.208-1-any.pkg.tar.zst", "dfe7fab66632eececc73d84053eae2be8dd2146ecefe0fc2133277706084d7ea"),
    ("mingw-w64-x86_64-zlib-1.3.2-2-any.pkg.tar.zst", "9e75842a070ba648e986e12424e1c92c9d7d77200e85f6a34eeb600819f2e694"),
)

REQUIRED_DLLS = (
    "libgobject-2.0-0.dll",
    "libpango-1.0-0.dll",
    "libpangoft2-1.0-0.dll",
    "libharfbuzz-0.dll",
    "libfontconfig-1.dll",
)


def windows_runtime_supported() -> bool:
    return os.name == "nt" and sys.maxsize > 2**32 and platform.machine().lower() in {
        "amd64",
        "x86_64",
    }


def runtime_root(base_dir: Path) -> Path:
    return Path(base_dir).resolve() / "projects" / ".runtime" / RUNTIME_DIRECTORY_NAME


def runtime_bin(base_dir: Path) -> Path:
    return runtime_root(base_dir) / "mingw64" / "bin"


def _runtime_is_complete(base_dir: Path) -> bool:
    root = runtime_root(base_dir)
    bin_dir = runtime_bin(base_dir)
    marker = root / "runtime.json"
    if not marker.is_file() or not all((bin_dir / name).is_file() for name in REQUIRED_DLLS):
        return False
    try:
        metadata = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return metadata.get("version") == RUNTIME_VERSION


def configure_weasyprint_runtime(base_dir: Path) -> bool:
    if not windows_runtime_supported() or not _runtime_is_complete(base_dir):
        return False
    directory = str(runtime_bin(base_dir))
    existing = os.environ.get("WEASYPRINT_DLL_DIRECTORIES", "")
    entries = [entry for entry in existing.split(os.pathsep) if entry]
    if directory not in entries:
        os.environ["WEASYPRINT_DLL_DIRECTORIES"] = os.pathsep.join([directory, *entries])
    return True


def is_missing_weasyprint_native_runtime(issues: list[str]) -> bool:
    if not windows_runtime_supported():
        return False
    return any(
        issue.lower().startswith("weasyprint 無法匯入：")
        and ("cannot load library" in issue.lower() or "could not find module" in issue.lower())
        for issue in issues
    )


def _download_package(destination: Path, filename: str, expected_hash: str) -> Path:
    target = destination / filename
    request = urllib.request.Request(
        f"{MSYS2_REPOSITORY}/{filename}",
        headers={"User-Agent": "PLANT/1.0 WeasyPrint runtime installer"},
    )
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            with target.open("wb") as handle:
                while chunk := response.read(1024 * 1024):
                    handle.write(chunk)
                    digest.update(chunk)
    except (OSError, urllib.error.URLError) as exc:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"無法下載 {filename}：{exc}") from exc
    if digest.hexdigest().lower() != expected_hash.lower():
        target.unlink(missing_ok=True)
        raise RuntimeError(f"{filename} 的 SHA-256 驗證失敗")
    return target


def _extract_package(tar_command: str, package: Path, destination: Path) -> None:
    try:
        result = subprocess.run(
            [tar_command, "-xf", str(package), "-C", str(destination)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"無法解壓縮 {package.name}：{exc}") from exc
    if result.returncode != 0:
        detail = " ".join(result.stderr.split()) or f"exit code {result.returncode}"
        raise RuntimeError(f"無法解壓縮 {package.name}：{detail}")


def ensure_weasyprint_runtime(base_dir: Path) -> Path:
    root = Path(base_dir).resolve()
    if configure_weasyprint_runtime(root):
        return runtime_bin(root)
    if not windows_runtime_supported():
        raise RuntimeError("WeasyPrint 自動執行環境目前僅支援 64 位元 Windows")
    tar_command = shutil.which("tar")
    if not tar_command:
        raise RuntimeError("Windows 缺少 tar 解壓縮工具，無法準備 WeasyPrint 執行環境")
    parent = runtime_root(root).parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(f"無法建立 WeasyPrint 執行環境目錄：{exc}") from exc

    print("正在下載 WeasyPrint Windows 執行環境（約 15 MB）…", flush=True)
    try:
        with tempfile.TemporaryDirectory(prefix="weasyprint-download-", dir=parent) as download_name, tempfile.TemporaryDirectory(prefix="weasyprint-install-", dir=parent) as install_name:
            download_dir = Path(download_name)
            install_dir = Path(install_name)
            downloaded: dict[str, Path] = {}
            with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as executor:
                futures = {
                    executor.submit(_download_package, download_dir, filename, digest): filename
                    for filename, digest in PACKAGES
                }
                for future in as_completed(futures):
                    filename = futures[future]
                    downloaded[filename] = future.result()
            for filename, _digest in PACKAGES:
                _extract_package(tar_command, downloaded[filename], install_dir)
            installed_bin = install_dir / "mingw64" / "bin"
            missing = [name for name in REQUIRED_DLLS if not (installed_bin / name).is_file()]
            if missing:
                raise RuntimeError("WeasyPrint 執行環境內容不完整：" + "、".join(missing))
            (install_dir / "runtime.json").write_text(
                json.dumps(
                    {
                        "version": RUNTIME_VERSION,
                        "source": MSYS2_REPOSITORY,
                        "packages": [filename for filename, _digest in PACKAGES],
                    },
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )
            destination = runtime_root(root)
            if destination.exists():
                shutil.rmtree(destination)
            os.replace(install_dir, destination)
    except RuntimeError:
        raise
    except OSError as exc:
        raise RuntimeError(f"無法準備 WeasyPrint 執行環境：{exc}") from exc
    if not configure_weasyprint_runtime(root):
        raise RuntimeError("WeasyPrint 執行環境安裝完成，但無法啟用 DLL 目錄")
    print("[OK] WeasyPrint Windows 執行環境準備完成", flush=True)
    return runtime_bin(root)
