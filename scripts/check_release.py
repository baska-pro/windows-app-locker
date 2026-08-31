#!/usr/bin/env python3
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "windows_app_locker.py"
VERSION_FILE = ROOT / "VERSION"

REQUIRED = [
    "windows_app_locker.py",
    "VERSION",
    "requirements.txt",
    "README.md",
    "README.en.md",
    "CHANGELOG.md",
    "LICENSE",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "install.ps1",
    "uninstall.ps1",
    ".gitignore",
    ".github/workflows/ci.yml",
]

TOKEN_RE = re.compile(rb"(?<![A-Za-z0-9_-])[0-9]{8,12}:[A-Za-z0-9_-]{30,}(?![A-Za-z0-9_-])")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def script_version() -> str:
    source = MAIN.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(MAIN))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "VERSION":
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        return node.value.value
    raise RuntimeError("VERSION constant not found in windows_app_locker.py")


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        return [
            p.relative_to(ROOT)
            for p in ROOT.rglob("*")
            if p.is_file()
            and ".git" not in p.parts
            and "__pycache__" not in p.parts
            and p.suffix not in {".pyc", ".pyo"}
        ]
    return [Path(item.decode()) for item in result.stdout.split(b"\0") if item]


def main() -> int:
    failures: list[str] = []

    for name in REQUIRED:
        if not (ROOT / name).is_file():
            failures.append(f"missing required file: {name}")

    if not VERSION_FILE.is_file() or not MAIN.is_file():
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1

    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not SEMVER_RE.fullmatch(version):
        failures.append(f"invalid semantic version: {version!r}")

    try:
        embedded = script_version()
    except Exception as exc:
        failures.append(str(exc))
        embedded = "unknown"

    if embedded != version:
        failures.append(f"version mismatch: VERSION={version}, script={embedded}")

    compile_result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(MAIN)],
        cwd=ROOT,
        check=False,
    )
    if compile_result.returncode != 0:
        failures.append("python syntax check failed")

    forbidden_names = {
        "config.json",
        "config.tmp",
        "app_locker.log",
        "remotedroid.log",
        ".env",
    }

    for relative in tracked_files():
        path = ROOT / relative
        if not path.is_file():
            continue
        if path.name in forbidden_names or "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            failures.append(f"runtime/generated file should not be tracked: {relative}")
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if TOKEN_RE.search(data):
            failures.append(f"possible Telegram bot token in: {relative}")

    readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="replace") if (ROOT / "README.md").exists() else ""
    if version not in readme:
        failures.append(f"README.md does not mention version {version}")

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8", errors="replace") if (ROOT / "CHANGELOG.md").exists() else ""
    if not re.search(rf"^##\s+{re.escape(version)}(?:\s|$)", changelog, flags=re.MULTILINE):
        failures.append(f"CHANGELOG.md does not contain version {version}")

    print(f"Windows App Locker release check | {version}")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1

    print("OK: required files")
    print("OK: version consistency")
    print("OK: Python syntax")
    print("OK: repository/runtime hygiene")
    print("OK: basic credential hygiene")
    print("OK: README and changelog version references")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
