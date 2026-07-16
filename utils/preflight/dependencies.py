from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
import re
import subprocess
import sys
import sysconfig
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


_REQUIREMENT_NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]+\])?")
_LOCK_TIMEOUT_SECONDS = 300.0
_STALE_LOCK_SECONDS = 900.0
_DISTRIBUTION_IMPORTS = {
    "python-dotenv": "dotenv",
    "packaging": "packaging",
    "openai": "openai",
    "anthropic": "anthropic",
    "google-genai": "google.genai",
    "pypdf2": "PyPDF2",
    "python-docx": "docx",
    "openpyxl": "openpyxl",
    "python-pptx": "pptx",
    "markdown-it-py": "markdown_it",
    "tavily-python": "tavily",
    "requests": "requests",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "python-multipart": "multipart",
    "gymnasium": "gymnasium",
    "numpy": "numpy",
}


def _requirement_lines(requirements_path: Path) -> list[str]:
    requirements: list[str] = []
    for raw_line in requirements_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        match = _REQUIREMENT_NAME.match(line)
        if not match:
            raise RuntimeError(f"無法解析 Python 套件需求：{raw_line}")
        requirements.append(line)
    return requirements


def _dependency_issues(requirements_path: Path) -> list[str]:
    requirements = _requirement_lines(requirements_path)
    try:
        from packaging.requirements import Requirement
        from packaging.utils import canonicalize_name
    except ImportError:
        return ["packaging 未安裝，無法驗證套件版本"]

    package_modules = importlib.metadata.packages_distributions()
    issues = []
    imports_to_check = []
    installed_versions = {}
    for line in requirements:
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            installed_version = importlib.metadata.version(requirement.name)
        except importlib.metadata.PackageNotFoundError:
            issues.append(f"{requirement.name} 未安裝")
            continue
        if requirement.specifier and installed_version not in requirement.specifier:
            issues.append(
                f"{requirement.name} {installed_version} 不符合 {requirement.specifier}"
            )
            continue
        installed_versions[requirement.name] = installed_version

        normalized_name = canonicalize_name(requirement.name)
        modules = [
            module_name
            for module_name, distributions in package_modules.items()
            if any(canonicalize_name(distribution) == normalized_name for distribution in distributions)
        ]
        if modules and not any(importlib.util.find_spec(module_name) for module_name in modules):
            issues.append(f"{requirement.name} 安裝內容不完整")
            continue
        import_name = _DISTRIBUTION_IMPORTS.get(normalized_name)
        if import_name:
            imports_to_check.append((requirement.name, import_name))

    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "python": sys.executable,
                "imports": imports_to_check,
                "versions": installed_versions,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    cache_path = requirements_path.parent / "projects" / ".runtime" / "python-imports.json"
    cached_fingerprint = ""
    try:
        cached_fingerprint = str(
            json.loads(cache_path.read_text(encoding="utf-8")).get("fingerprint") or ""
        )
    except (FileNotFoundError, OSError, json.JSONDecodeError, AttributeError):
        pass

    if imports_to_check and cached_fingerprint != fingerprint:
        script = """
import contextlib
import importlib
import io
import json
import sys

failures = {}
for distribution, module_name in json.loads(sys.argv[1]):
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            importlib.import_module(module_name)
    except BaseException as exc:
        failures[distribution] = f"{exc.__class__.__name__}: {exc}"
print(json.dumps(failures, ensure_ascii=False))
"""
        try:
            result = subprocess.run(
                [sys.executable, "-c", script, json.dumps(imports_to_check)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            issues.append("Python 套件實際匯入檢查逾時")
        else:
            if result.returncode != 0:
                issues.append("Python 套件實際匯入檢查無法執行")
            else:
                try:
                    failures = json.loads(result.stdout)
                except json.JSONDecodeError:
                    issues.append("Python 套件實際匯入檢查結果無法解析")
                else:
                    issues.extend(
                        f"{distribution} 無法匯入：{error}"
                        for distribution, error in failures.items()
                    )
                    if not failures:
                        temporary = None
                        try:
                            cache_path.parent.mkdir(parents=True, exist_ok=True)
                            temporary = cache_path.with_name(
                                f".{cache_path.name}.{os.getpid()}.tmp"
                            )
                            temporary.write_text(
                                json.dumps({"fingerprint": fingerprint}),
                                encoding="utf-8",
                            )
                            os.replace(temporary, cache_path)
                        except OSError:
                            if temporary is not None:
                                temporary.unlink(missing_ok=True)
    return issues


@contextmanager
def _dependency_install_lock(base_dir: Path) -> Iterator[None]:
    runtime_dir = base_dir / "projects" / ".runtime"
    try:
        runtime_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError("無法建立 Python 套件安裝鎖，請檢查 projects 寫入權限") from exc
    lock_path = runtime_dir / "python-dependencies.lock"
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS

    while True:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(f"{os.getpid()}\n")
            break
        except FileExistsError:
            try:
                stale = time.time() - lock_path.stat().st_mtime > _STALE_LOCK_SECONDS
            except FileNotFoundError:
                continue
            if stale:
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise RuntimeError("等待其他程序安裝 Python 套件逾時")
            time.sleep(0.25)

    try:
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _pip_is_healthy(environment: dict[str, str]) -> bool:
    """Check a pip command that imports the resolver, not just its metadata."""
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-index",
                "--dry-run",
                "pip",
            ],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _ensure_pip(environment: dict[str, str]) -> None:
    if _pip_is_healthy(environment):
        return

    try:
        importlib.metadata.version("pip")
    except importlib.metadata.PackageNotFoundError:
        pass
    else:
        print("偵測到 pip 安裝損壞，正在自動重建…", flush=True)

    result = subprocess.run(
        [sys.executable, "-m", "ensurepip", "--upgrade"],
        env=environment,
        check=False,
    )
    if result.returncode == 0 and _pip_is_healthy(environment):
        return

    # ensurepip does not overwrite a broken pip when its recorded version is
    # newer than the bundled wheel.  In that case, run the bundled copy in an
    # isolated import path and use it to replace the damaged installation.
    try:
        import ensurepip

        bundle_dir = Path(ensurepip.__file__).resolve().parent / "_bundled"
        pip_wheels = sorted(bundle_dir.glob("pip-*.whl"), reverse=True)
        pip_wheel = pip_wheels[0]
    except (ImportError, IndexError, OSError):
        raise RuntimeError("無法自動準備 pip") from None

    recovery_environment = environment.copy()
    existing_pythonpath = recovery_environment.get("PYTHONPATH")
    recovery_environment["PYTHONPATH"] = str(pip_wheel)
    if existing_pythonpath:
        recovery_environment["PYTHONPATH"] += os.pathsep + existing_pythonpath
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--force-reinstall",
            str(pip_wheel),
        ],
        env=recovery_environment,
        check=False,
    )
    if result.returncode != 0 or not _pip_is_healthy(environment):
        raise RuntimeError("pip 已損壞且自動重建失敗")


def _check_python_install_directory() -> None:
    install_dir = Path(sysconfig.get_paths()["purelib"])
    try:
        install_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix="plant-package-probe-",
            dir=install_dir,
            delete=True,
        ) as handle:
            handle.write(b"ok")
            handle.flush()
    except OSError as exc:
        raise RuntimeError(
            f"Python 套件安裝目錄無法寫入：{install_dir}"
        ) from exc


def ensure_python_dependencies(base_dir: Path) -> None:
    root = Path(base_dir).resolve()
    requirements_path = root / "requirements.txt"
    if not requirements_path.is_file():
        raise RuntimeError(f"找不到 Python 套件清單：{requirements_path}")

    issues = _dependency_issues(requirements_path)
    if not issues:
        return

    with _dependency_install_lock(root):
        issues = _dependency_issues(requirements_path)
        if not issues:
            return

        print(
            "\n偵測到 Python 套件缺失或版本不符，正在自動修復："
            + "；".join(issues),
            flush=True,
        )
        environment = os.environ.copy()
        environment["PYTHONUTF8"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        _check_python_install_directory()
        _ensure_pip(environment)

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--no-cache-dir",
                    "--requirement",
                    str(requirements_path),
                ],
                cwd=root,
                env=environment,
                check=False,
                timeout=900,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Python 套件自動安裝超過 15 分鐘") from exc
        if result.returncode != 0:
            raise RuntimeError("Python 套件自動安裝失敗，請檢查網路與 pip 輸出")

        importlib.invalidate_caches()
        unresolved = _dependency_issues(requirements_path)
        if unresolved:
            raise RuntimeError(
                "下列 Python 套件安裝後仍無法使用：" + "、".join(unresolved)
            )
        print("[OK] Python 套件自動安裝完成\n", flush=True)
