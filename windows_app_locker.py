#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Windows App Locker + Telegram Control
=====================================
Target: Windows 10/11, Python 3.10+

Fitur utama v2:
- First-run setup wizard dan dependency bootstrap otomatis.
- PIN PBKDF2 (PIN tidak disimpan plaintext).
- Token Telegram dilindungi Windows DPAPI.
- Monitor aplikasi terdaftar dengan psutil dan path matching yang lebih aman.
- Blokir aplikasi yang dibuka ketika masih terkunci.
- Dialog PIN lokal dengan cooldown percobaan salah.
- Dashboard GUI dengan pencarian, edit nama, enable/disable proteksi, pengaturan, dan panduan.
- Double-click / context menu untuk pengelolaan aplikasi.
- System tray dan autostart per-user melalui HKCU Run.
- Manual launch menampilkan dashboard; mode background hanya saat --background.
- Log lokal dengan rotasi serta pemulihan config rusak.
- Telegram notification ketika aplikasi diblokir/dibuka dan PIN salah.
- Telegram inline-button menu + remote control terbatas ke OWNER_CHAT_ID:
    /menu /status /apps /lock /unlock /lockall /unlockall
    /launch /pause /resume /logs /ping /help
- CLI diagnostic: --doctor dan --show-data-dir.

Catatan keamanan:
- Ini adalah app-locker level user, bukan boundary keamanan kernel.
- Administrator Windows tetap dapat menghentikan proses, menghapus autostart,
  mengganti permission, atau menjalankan aplikasi dengan cara lain.
- Tidak ada arbitrary shell/command execution, keylogger, screenshot remote,
  credential capture, atau mekanisme stealth.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional


APP_TITLE = "Windows App Locker"
APP_DIR_NAME = "WinAppLockerBot"
CONFIG_FILENAME = "config.json"
LOG_FILENAME = "app_locker.log"
VERSION = "2.0.0"

# Fast-path metadata command: does not require Windows-only dependencies.
if "--version" in sys.argv:
    print(VERSION)
    raise SystemExit(0)

PROTECTED_PROCESS_NAMES = {
    "explorer.exe", "winlogon.exe", "csrss.exe", "lsass.exe",
    "services.exe", "smss.exe", "svchost.exe", "dwm.exe",
    "fontdrvhost.exe", "sihost.exe", "taskhostw.exe",
}

REQUIRED_PACKAGES = {
    "psutil": "psutil>=7.0",
    "telegram": "python-telegram-bot>=22.0,<23",
    "pystray": "pystray>=0.19",
    "PIL": "Pillow>=10",
    "win32crypt": "pywin32>=306",
}


def is_windows() -> bool:
    return sys.platform == "win32"


def app_data_dir() -> Path:
    base = os.getenv("APPDATA") or str(Path.home())
    p = Path(base) / APP_DIR_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


APP_DIR = app_data_dir()
CONFIG_PATH = APP_DIR / CONFIG_FILENAME
LOG_PATH = APP_DIR / LOG_FILENAME


def install_missing_dependencies() -> None:
    """Install dependencies if their import modules are unavailable."""
    import importlib.util

    missing = []
    for module_name, package_spec in REQUIRED_PACKAGES.items():
        if importlib.util.find_spec(module_name) is None:
            missing.append(package_spec)

    if not missing:
        return

    print("[SETUP] Memasang dependency:", ", ".join(missing))
    cmd = [
        sys.executable, "-m", "pip", "install",
        "--disable-pip-version-check",
        *missing,
    ]
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as exc:
        print("\n[ERROR] Gagal memasang dependency otomatis.")
        print("Jalankan manual:")
        print(f'  "{sys.executable}" -m pip install ' + " ".join(missing))
        raise SystemExit(exc.returncode)


if not is_windows():
    print("Script ini khusus Windows 10/11.")
    raise SystemExit(1)

install_missing_dependencies()

import psutil
import win32crypt
import winreg
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import pystray
from PIL import Image, ImageDraw

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOGGER = logging.getLogger("app_locker")
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False

if not LOGGER.handlers:
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(threadName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = RotatingFileHandler(
        LOG_PATH,
        maxBytes=2 * 1024 * 1024,
        backupCount=4,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    LOGGER.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    LOGGER.addHandler(sh)


# ---------------------------------------------------------------------------
# Utility / security
# ---------------------------------------------------------------------------

def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def dpapi_encrypt(text: str) -> str:
    encrypted = win32crypt.CryptProtectData(
        text.encode("utf-8"),
        "WinAppLockerBot Telegram Token",
        None,
        None,
        None,
        0,
    )
    return b64e(encrypted)


def dpapi_decrypt(blob_b64: str) -> str:
    _desc, decrypted = win32crypt.CryptUnprotectData(
        b64d(blob_b64),
        None,
        None,
        None,
        0,
    )
    return decrypted.decode("utf-8")


def make_pin_record(pin: str, iterations: int = 350_000) -> dict[str, Any]:
    salt = os.urandom(32)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        pin.encode("utf-8"),
        salt,
        iterations,
        dklen=32,
    )
    return {
        "salt": b64e(salt),
        "hash": b64e(digest),
        "iterations": iterations,
    }


def verify_pin(pin: str, record: dict[str, Any]) -> bool:
    try:
        salt = b64d(record["salt"])
        expected = b64d(record["hash"])
        iterations = int(record.get("iterations", 350_000))
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            pin.encode("utf-8"),
            salt,
            iterations,
            dklen=len(expected),
        )
        import hmac
        return hmac.compare_digest(actual, expected)
    except Exception:
        LOGGER.exception("PIN verification error")
        return False


def safe_slug(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    text = (text.strip("-") or "app")[:32]
    return text.rstrip("-") or "app"


def canonical_path(value: str | Path) -> str:
    try:
        return os.path.normcase(os.path.abspath(os.fspath(value)))
    except Exception:
        return os.path.normcase(os.fspath(value))


def human_duration(seconds: float) -> str:
    if seconds <= 0:
        return "terkunci"
    if seconds < 60:
        return f"{int(seconds)} detik"
    minutes = int(seconds // 60)
    return f"{minutes} menit"


def current_username() -> str:
    return os.getenv("USERNAME") or os.getenv("USER") or "unknown"


def pythonw_executable() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        candidate = exe.with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    return str(exe)


def script_path() -> Path:
    return Path(__file__).resolve()


def set_autostart(enabled: bool) -> None:
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    value_name = "WinAppLockerBot"
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        key_path,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        if enabled:
            cmd = f'"{pythonw_executable()}" "{script_path()}" --background'
            winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, value_name)
            except FileNotFoundError:
                pass


def get_autostart() -> bool:
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            key_path,
            0,
            winreg.KEY_QUERY_VALUE,
        ) as key:
            value, _ = winreg.QueryValueEx(key, "WinAppLockerBot")
            return bool(value)
    except FileNotFoundError:
        return False


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "telegram": {
        "token_dpapi": "",
        "owner_chat_id": 0,
        "enabled": True,
    },
    "security": {
        "pin": {},
        "local_unlock_minutes": 5,
        "wrong_pin_notify": True,
        "max_wrong_before_cooldown": 5,
        "cooldown_seconds": 30,
    },
    "monitor": {
        "enabled": True,
        "scan_interval": 0.35,
        "notify_allowed_open": True,
        "notify_blocked_open": True,
    },
    "ui": {
        "start_hidden": False,
        "autostart": True,
    },
    "runtime": {
        "paused_until": 0,
    },
    "apps": {},
}


class ConfigStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.data: dict[str, Any] = {}

    def load(self) -> dict[str, Any]:
        with self.lock:
            if not self.path.exists():
                self.data = json.loads(json.dumps(DEFAULT_CONFIG))
                return self.data

            try:
                with self.path.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if not isinstance(loaded, dict):
                    raise ValueError("Config root must be a JSON object")
            except Exception:
                stamp = time.strftime("%Y%m%d-%H%M%S")
                backup = self.path.with_name(f"{self.path.stem}.corrupt-{stamp}.json")
                try:
                    shutil.copy2(self.path, backup)
                except Exception:
                    LOGGER.exception("Unable to back up corrupt config")
                LOGGER.exception("Config invalid; loading safe defaults")
                loaded = {}

            self.data = json.loads(json.dumps(DEFAULT_CONFIG))
            self._deep_update(self.data, loaded)
            return self.data

    def save(self) -> None:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8", newline="\n") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)

    @staticmethod
    def _deep_update(dst: dict[str, Any], src: dict[str, Any]) -> None:
        for key, value in src.items():
            if isinstance(value, dict) and isinstance(dst.get(key), dict):
                ConfigStore._deep_update(dst[key], value)
            else:
                dst[key] = value


# ---------------------------------------------------------------------------
# First-run setup
# ---------------------------------------------------------------------------

def first_run_setup() -> None:
    root = tk.Tk()
    root.withdraw()

    messagebox.showinfo(
        APP_TITLE,
        "Setup pertama.\n\n"
        "Siapkan:\n"
        "1. Token bot Telegram dari @BotFather\n"
        "2. Chat ID Telegram pemilik\n"
        "3. PIN minimal 4 digit/karakter\n\n"
        "Semua kontrol Telegram hanya menerima perintah dari Chat ID pemilik.",
        parent=root,
    )

    token = ""
    while not token:
        token = simpledialog.askstring(
            "Telegram Bot Token",
            "Masukkan TOKEN bot Telegram:",
            parent=root,
        ) or ""
        token = token.strip()
        if not token:
            if messagebox.askyesno(
                APP_TITLE,
                "Token belum diisi. Batalkan setup?",
                parent=root,
            ):
                root.destroy()
                raise SystemExit(0)

    owner_chat_id = 0
    while owner_chat_id == 0:
        raw = simpledialog.askstring(
            "Telegram Owner Chat ID",
            "Masukkan Chat ID Telegram pemilik\n(contoh: 123456789):",
            parent=root,
        )
        if raw is None:
            root.destroy()
            raise SystemExit(0)
        try:
            owner_chat_id = int(raw.strip())
        except ValueError:
            messagebox.showerror(APP_TITLE, "Chat ID harus berupa angka.", parent=root)

    pin = ""
    while len(pin) < 4:
        pin = simpledialog.askstring(
            "Buat PIN",
            "Buat PIN minimal 4 karakter:",
            show="*",
            parent=root,
        ) or ""
        if not pin:
            if messagebox.askyesno(APP_TITLE, "Batalkan setup?", parent=root):
                root.destroy()
                raise SystemExit(0)
        elif len(pin) < 4:
            messagebox.showerror(APP_TITLE, "PIN minimal 4 karakter.", parent=root)

    confirm = simpledialog.askstring(
        "Konfirmasi PIN",
        "Masukkan ulang PIN:",
        show="*",
        parent=root,
    )
    if confirm != pin:
        messagebox.showerror(APP_TITLE, "Konfirmasi PIN tidak sama.", parent=root)
        root.destroy()
        raise SystemExit(1)

    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    cfg["telegram"]["token_dpapi"] = dpapi_encrypt(token)
    cfg["telegram"]["owner_chat_id"] = owner_chat_id
    cfg["security"]["pin"] = make_pin_record(pin)

    selected: tuple[str, ...] = ()
    if messagebox.askyesno(
        APP_TITLE,
        "Pilih aplikasi .exe yang ingin langsung dikunci sekarang?",
        parent=root,
    ):
        selected = filedialog.askopenfilenames(
            parent=root,
            title="Pilih aplikasi yang akan dikunci",
            filetypes=[("Windows Application", "*.exe"), ("All files", "*.*")],
        )

    skipped_protected = []
    protected_names = set(PROTECTED_PROCESS_NAMES)
    protected_names.add(Path(sys.executable).name.lower())
    for path_str in selected:
        path = Path(path_str)
        if path.name.lower() in protected_names:
            skipped_protected.append(path.name)
            continue
        slug = safe_slug(path.stem)
        base = slug
        i = 2
        while slug in cfg["apps"]:
            slug = f"{base}-{i}"
            i += 1
        cfg["apps"][slug] = {
            "name": path.stem,
            "exe": str(path),
            "process_name": path.name.lower(),
            "enabled": True,
            "unlocked_until": 0,
        }

    if skipped_protected:
        messagebox.showwarning(
            APP_TITLE,
            "Dilewati karena merupakan proses inti Windows:\n" + "\n".join(skipped_protected),
            parent=root,
        )

    cfg_store = ConfigStore(CONFIG_PATH)
    cfg_store.data = cfg
    cfg_store.save()

    enable_start = messagebox.askyesno(
        APP_TITLE,
        "Aktifkan App Locker otomatis saat login Windows?",
        parent=root,
    )
    cfg_store.data["ui"]["autostart"] = enable_start
    cfg_store.save()

    try:
        set_autostart(enable_start)
    except Exception as exc:
        messagebox.showwarning(
            APP_TITLE,
            f"Config tersimpan, tetapi autostart gagal dibuat:\n{exc}",
            parent=root,
        )

    messagebox.showinfo(
        APP_TITLE,
        f"Setup selesai.\n\nConfig:\n{CONFIG_PATH}\n\n"
        "Bot akan memakai long polling; tidak perlu webhook.",
        parent=root,
    )
    root.destroy()


# ---------------------------------------------------------------------------
# Single-instance
# ---------------------------------------------------------------------------

def enforce_single_instance() -> Any:
    import ctypes

    name = "Local\\WinAppLockerBot_7BC5168C"
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, name)
    if ctypes.windll.kernel32.GetLastError() == 183:
        print("App Locker sudah berjalan.")
        raise SystemExit(0)
    return handle


# ---------------------------------------------------------------------------
# Core locker
# ---------------------------------------------------------------------------

@dataclass
class UnlockRequest:
    app_id: str
    app_name: str
    exe: str
    cmdline: list[str]
    source_pid: int


class AppLockerCore:
    def __init__(self, config: ConfigStore):
        self.config = config
        self.stop_event = threading.Event()
        self.gui_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.pending_prompts: set[str] = set()
        self.pending_lock = threading.RLock()

        self.notified_allowed_pids: set[int] = set()
        self.last_block_notice: dict[str, float] = {}

        self.telegram: Optional["TelegramController"] = None
        self.ui: Optional["LockerUI"] = None

        self.wrong_attempts = 0
        self.cooldown_until = 0.0

    def set_ui(self, ui: "LockerUI") -> None:
        self.ui = ui

    def set_telegram(self, controller: "TelegramController") -> None:
        self.telegram = controller

    def notify(self, text: str) -> None:
        LOGGER.info(text.replace("\n", " | "))
        if self.telegram:
            self.telegram.notify(text)

    def verify_local_pin(self, pin: str, action: str = "pengaturan") -> tuple[bool, str]:
        now = time.time()
        if now < self.cooldown_until:
            remain = max(1, int(self.cooldown_until - now))
            return False, f"Terlalu banyak PIN salah. Coba lagi dalam {remain} detik."

        record = self.config.data.get("security", {}).get("pin", {})
        if verify_pin(pin, record):
            self.wrong_attempts = 0
            return True, ""

        self.wrong_attempts += 1
        security = self.config.data.get("security", {})
        max_wrong = max(1, int(security.get("max_wrong_before_cooldown", 5) or 5))
        cooldown = max(5, int(security.get("cooldown_seconds", 30) or 30))

        if self.wrong_attempts >= max_wrong:
            self.cooldown_until = time.time() + cooldown
            self.wrong_attempts = 0

        if security.get("wrong_pin_notify", True):
            self.notify(
                "🚨 PIN salah pada Windows App Locker\n"
                f"PC: {socket.gethostname()}\n"
                f"User: {current_username()}\n"
                f"Aksi: {action}"
            )

        return False, "PIN salah."

    def is_paused(self) -> bool:
        paused_until = float(self.config.data.get("runtime", {}).get("paused_until", 0) or 0)
        return time.time() < paused_until

    def pause(self, minutes: int) -> None:
        minutes = max(1, min(minutes, 1440))
        self.config.data["runtime"]["paused_until"] = time.time() + (minutes * 60)
        self.config.save()
        self.notify(f"⏸ App Locker dijeda {minutes} menit.")

    def resume(self) -> None:
        self.config.data["runtime"]["paused_until"] = 0
        self.config.save()
        self.notify("▶️ App Locker aktif kembali.")

    def app_items(self):
        return list(self.config.data.get("apps", {}).items())

    def resolve_app(self, query: str) -> tuple[Optional[str], Optional[dict[str, Any]]]:
        q = query.strip().lower()
        apps = self.config.data.get("apps", {})

        if q in apps:
            return q, apps[q]

        exact = [
            (app_id, app)
            for app_id, app in apps.items()
            if app.get("name", "").lower() == q
            or app.get("process_name", "").lower() == q
        ]
        if len(exact) == 1:
            return exact[0]

        partial = [
            (app_id, app)
            for app_id, app in apps.items()
            if q in app_id.lower()
            or q in app.get("name", "").lower()
            or q in app.get("process_name", "").lower()
        ]
        if len(partial) == 1:
            return partial[0]

        return None, None

    def app_is_unlocked(self, app: dict[str, Any]) -> bool:
        return time.time() < float(app.get("unlocked_until", 0) or 0)

    def unlock_app(self, app_id: str, minutes: int, source: str = "local") -> bool:
        apps = self.config.data.get("apps", {})
        if app_id not in apps:
            return False

        minutes = max(1, min(minutes, 1440))
        apps[app_id]["unlocked_until"] = time.time() + (minutes * 60)
        self.config.save()
        self.notify(
            f"🔓 {apps[app_id].get('name', app_id)} dibuka "
            f"{minutes} menit via {source}."
        )
        self.refresh_ui()
        return True

    def lock_app(self, app_id: str, terminate_now: bool = True, source: str = "local") -> bool:
        apps = self.config.data.get("apps", {})
        if app_id not in apps:
            return False

        apps[app_id]["unlocked_until"] = 0
        self.config.save()

        closed = 0
        if terminate_now:
            closed = self.terminate_matching_app(app_id)

        self.notify(
            f"🔒 {apps[app_id].get('name', app_id)} dikunci via {source}."
            + (f" Proses ditutup: {closed}." if closed else "")
        )
        self.refresh_ui()
        return True

    def lock_all(self, source: str = "local") -> int:
        count = 0
        for app_id, app in self.app_items():
            app["unlocked_until"] = 0
            count += self.terminate_matching_app(app_id)
        self.config.save()
        self.notify(f"🔒 Semua aplikasi dikunci via {source}. Proses ditutup: {count}.")
        self.refresh_ui()
        return count

    def unlock_all(self, minutes: int, source: str = "local") -> None:
        minutes = max(1, min(minutes, 1440))
        until = time.time() + (minutes * 60)
        for _app_id, app in self.app_items():
            if app.get("enabled", True):
                app["unlocked_until"] = until
        self.config.save()
        self.notify(f"🔓 Semua aplikasi dibuka {minutes} menit via {source}.")
        self.refresh_ui()

    def add_app(self, exe_path: str) -> str:
        path = Path(exe_path).expanduser()
        try:
            path = path.resolve(strict=True)
        except FileNotFoundError as exc:
            raise ValueError("File executable tidak ditemukan.") from exc

        if not path.is_file() or path.suffix.lower() != ".exe":
            raise ValueError("Pilih file aplikasi Windows dengan ekstensi .exe.")

        protected_names = set(PROTECTED_PROCESS_NAMES)
        protected_names.add(Path(sys.executable).name.lower())
        if path.name.lower() in protected_names:
            raise ValueError(
                f"{path.name} tidak boleh dikunci karena digunakan Windows atau App Locker."
            )

        apps = self.config.data.setdefault("apps", {})
        wanted = canonical_path(path)
        for existing in apps.values():
            if canonical_path(existing.get("exe", "")) == wanted:
                raise ValueError("Aplikasi tersebut sudah terdaftar.")

        slug = safe_slug(path.stem)
        base = slug
        i = 2
        while slug in apps:
            suffix = f"-{i}"
            slug = f"{base[:32-len(suffix)]}{suffix}"
            i += 1

        apps[slug] = {
            "name": path.stem,
            "exe": str(path),
            "process_name": path.name.lower(),
            "enabled": True,
            "unlocked_until": 0,
        }
        self.config.save()
        self.notify(f"➕ Aplikasi ditambahkan ke App Locker: {path.stem}")
        self.refresh_ui()
        return slug

    def remove_app(self, app_id: str) -> bool:
        apps = self.config.data.get("apps", {})
        if app_id not in apps:
            return False
        name = apps[app_id].get("name", app_id)
        del apps[app_id]
        self.config.save()
        self.notify(f"➖ Aplikasi dihapus dari daftar App Locker: {name}")
        self.refresh_ui()
        return True

    def launch_registered(self, app_id: str, minutes: int = 5, source: str = "telegram") -> bool:
        apps = self.config.data.get("apps", {})
        app = apps.get(app_id)
        if not app:
            return False

        exe = app.get("exe", "")
        if not exe or not Path(exe).exists():
            self.notify(f"⚠️ Tidak dapat menjalankan {app.get('name', app_id)}: file .exe tidak ditemukan.")
            return False

        self.unlock_app(app_id, minutes, source=source)
        try:
            subprocess.Popen([exe], cwd=str(Path(exe).parent))
            self.notify(f"▶️ {app.get('name', app_id)} dijalankan via {source}.")
            return True
        except Exception:
            LOGGER.exception("Failed launching app %s", app_id)
            return False

    def process_matches(self, info: dict[str, Any], app: dict[str, Any]) -> bool:
        exe = str(info.get("exe") or "")
        wanted_exe = str(app.get("exe") or "")

        # Prefer the exact executable path. This avoids terminating a different
        # program that happens to use the same process filename.
        if exe and wanted_exe:
            return canonical_path(exe) == canonical_path(wanted_exe)

        process_name = str(info.get("name") or "").lower()
        wanted_name = str(app.get("process_name") or "").lower()
        return bool(process_name and wanted_name and process_name == wanted_name)

    def terminate_matching_app(self, app_id: str) -> int:
        apps = self.config.data.get("apps", {})
        app = apps.get(app_id)
        if not app:
            return 0

        targets: list[psutil.Process] = []
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                if self.process_matches(proc.info, app):
                    targets.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        count = 0
        for proc in targets:
            try:
                proc.terminate()
                count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        _gone, alive = psutil.wait_procs(targets, timeout=1.5)
        for proc in alive:
            try:
                proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        return count

    def request_local_unlock(self, req: UnlockRequest) -> None:
        with self.pending_lock:
            if req.app_id in self.pending_prompts:
                return
            self.pending_prompts.add(req.app_id)
        self.gui_queue.put(("unlock_prompt", req))

    def handle_pin_result(self, req: UnlockRequest, pin: Optional[str]) -> None:
        with self.pending_lock:
            self.pending_prompts.discard(req.app_id)

        if pin is None:
            return

        ok, error = self.verify_local_pin(pin, f"membuka {req.app_name}")
        if not ok:
            self.gui_queue.put(("error", error))
            return

        minutes = int(self.config.data["security"].get("local_unlock_minutes", 5))
        self.unlock_app(req.app_id, minutes, source="PIN lokal")
        self._relaunch(req)

    def _relaunch(self, req: UnlockRequest) -> None:
        try:
            cmd = req.cmdline if req.cmdline else [req.exe]
            if not cmd or not cmd[0]:
                cmd = [req.exe]
            subprocess.Popen(cmd, cwd=str(Path(req.exe).parent) if req.exe else None)
        except Exception as exc:
            LOGGER.exception("Relaunch failed")
            self.gui_queue.put(("error", f"Gagal menjalankan kembali aplikasi:\n{exc}"))

    def monitor_loop(self) -> None:
        LOGGER.info("Process monitor started")
        interval = float(self.config.data["monitor"].get("scan_interval", 0.35))
        interval = min(max(interval, 0.15), 5.0)

        while not self.stop_event.is_set():
            try:
                if not self.config.data["monitor"].get("enabled", True) or self.is_paused():
                    self.stop_event.wait(interval)
                    continue

                alive_pids: set[int] = set()

                for proc in psutil.process_iter(["pid", "name", "exe", "cmdline", "username"]):
                    try:
                        info = proc.info
                        pid = int(info["pid"])
                        alive_pids.add(pid)

                        for app_id, app in self.app_items():
                            if not app.get("enabled", True):
                                continue
                            if not self.process_matches(info, app):
                                continue

                            if self.app_is_unlocked(app):
                                if (
                                    pid not in self.notified_allowed_pids
                                    and self.config.data["monitor"].get("notify_allowed_open", True)
                                ):
                                    self.notified_allowed_pids.add(pid)
                                    self.notify(
                                        "✅ Aplikasi dibuka saat izin aktif\n"
                                        f"Aplikasi: {app.get('name', app_id)}\n"
                                        f"PC: {socket.gethostname()}\n"
                                        f"User: {current_username()}"
                                    )
                                continue

                            # Locked: capture command line and terminate quickly.
                            try:
                                cmdline = list(info.get("cmdline") or proc.cmdline() or [])
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                cmdline = []

                            exe = str(info.get("exe") or app.get("exe") or "")
                            if not exe:
                                exe = str(app.get("exe") or "")

                            try:
                                proc.terminate()
                                try:
                                    proc.wait(timeout=1.0)
                                except psutil.TimeoutExpired:
                                    proc.kill()
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass

                            if self.config.data["monitor"].get("notify_blocked_open", True):
                                now_notice = time.time()
                                last_notice = self.last_block_notice.get(app_id, 0.0)
                                if now_notice - last_notice >= 5.0:
                                    self.last_block_notice[app_id] = now_notice
                                    self.notify(
                                        "🔐 Percobaan membuka aplikasi terkunci\n"
                                        f"Aplikasi: {app.get('name', app_id)}\n"
                                        f"PC: {socket.gethostname()}\n"
                                        f"User: {current_username()}"
                                    )

                            req = UnlockRequest(
                                app_id=app_id,
                                app_name=app.get("name", app_id),
                                exe=exe,
                                cmdline=cmdline,
                                source_pid=pid,
                            )
                            self.request_local_unlock(req)
                            break

                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                    except Exception:
                        LOGGER.exception("Error handling process")

                self.notified_allowed_pids.intersection_update(alive_pids)

            except Exception:
                LOGGER.exception("Monitor loop error")

            self.stop_event.wait(interval)

        LOGGER.info("Process monitor stopped")

    def refresh_ui(self) -> None:
        self.gui_queue.put(("refresh", None))

    def stop(self) -> None:
        self.stop_event.set()


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

class TelegramController:
    def __init__(self, core: AppLockerCore, token: str, owner_chat_id: int):
        self.core = core
        self.token = token
        self.owner_chat_id = int(owner_chat_id)

        self.application: Optional[Application] = None
        self.loop = None
        self.thread: Optional[threading.Thread] = None
        self.ready = threading.Event()

    def start(self) -> None:
        self.thread = threading.Thread(
            target=self._thread_main,
            name="TelegramBot",
            daemon=True,
        )
        self.thread.start()

    def _thread_main(self) -> None:
        import asyncio

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.loop = loop
            loop.run_until_complete(self._async_main())
        except Exception:
            LOGGER.exception("Telegram bot crashed")

    async def _async_main(self) -> None:
        self.application = Application.builder().token(self.token).build()

        handlers = {
            "start": self.cmd_start,
            "menu": self.cmd_menu,
            "help": self.cmd_help,
            "ping": self.cmd_ping,
            "status": self.cmd_status,
            "apps": self.cmd_apps,
            "lock": self.cmd_lock,
            "unlock": self.cmd_unlock,
            "lockall": self.cmd_lockall,
            "unlockall": self.cmd_unlockall,
            "launch": self.cmd_launch,
            "pause": self.cmd_pause,
            "resume": self.cmd_resume,
            "logs": self.cmd_logs,
        }
        for command, callback in handlers.items():
            self.application.add_handler(CommandHandler(command, callback))
        self.application.add_handler(CallbackQueryHandler(self.on_callback))

        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )

        self.ready.set()
        LOGGER.info("Telegram bot started")

        try:
            await self.application.bot.send_message(
                chat_id=self.owner_chat_id,
                text=(
                    "🟢 Windows App Locker aktif\n"
                    f"PC: {socket.gethostname()}\n"
                    f"User: {current_username()}\n"
                    f"Versi: {VERSION}\n\n"
                    "Ketik /help untuk kontrol."
                ),
            )
        except Exception:
            LOGGER.exception("Unable to send startup Telegram message")

        while not self.core.stop_event.is_set():
            await self._sleep(0.5)

        await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()

    @staticmethod
    async def _sleep(seconds: float) -> None:
        import asyncio
        await asyncio.sleep(seconds)

    @staticmethod
    def menu_markup() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("📊 Status", callback_data="menu:status"),
                    InlineKeyboardButton("📱 Apps", callback_data="menu:apps"),
                ],
                [
                    InlineKeyboardButton("🔒 Lock All", callback_data="menu:lockall"),
                    InlineKeyboardButton("🔓 Unlock 5m", callback_data="menu:unlockall5"),
                ],
                [
                    InlineKeyboardButton("⏸ Pause 5m", callback_data="menu:pause5"),
                    InlineKeyboardButton("▶️ Resume", callback_data="menu:resume"),
                ],
                [InlineKeyboardButton("ℹ️ Help", callback_data="menu:help")],
            ]
        )

    def status_text(self) -> str:
        paused = self.core.is_paused()
        apps = self.core.app_items()
        unlocked = sum(1 for _, app in apps if self.core.app_is_unlocked(app))
        enabled = sum(1 for _, app in apps if app.get("enabled", True))

        paused_until = float(
            self.core.config.data.get("runtime", {}).get("paused_until", 0) or 0
        )
        pause_text = human_duration(paused_until - time.time()) if paused else "tidak"

        return (
            "🛡 STATUS\n"
            f"PC: {socket.gethostname()}\n"
            f"User: {current_username()}\n"
            f"Monitor: {'aktif' if self.core.config.data['monitor'].get('enabled', True) else 'nonaktif'}\n"
            f"Pause: {pause_text}\n"
            f"Aplikasi terdaftar: {len(apps)}\n"
            f"Proteksi aktif: {enabled}\n"
            f"Sedang unlocked: {unlocked}\n"
            f"Autostart: {'aktif' if get_autostart() else 'nonaktif'}\n"
            f"Versi: {VERSION}"
        )

    def apps_text(self) -> str:
        lines = ["📱 APLIKASI"]
        apps = self.core.app_items()

        if not apps:
            lines.append("Belum ada aplikasi terdaftar.")
        else:
            now = time.time()
            for app_id, app in apps:
                remain = float(app.get("unlocked_until", 0) or 0) - now
                if not app.get("enabled", True):
                    state = "⏸ disabled"
                elif remain > 0:
                    state = f"🔓 {human_duration(remain)}"
                else:
                    state = "🔒 terkunci"
                lines.append(f"• {app_id}: {app.get('name', app_id)} — {state}")

        return "\n".join(lines)[:4000]

    @staticmethod
    def help_text() -> str:
        return (
            "🛡 Windows App Locker\n\n"
            "/menu - tombol kontrol utama\n"
            "/status - status locker\n"
            "/apps - daftar aplikasi\n"
            "/lock <app> - kunci + tutup aplikasi\n"
            "/unlock <app> [menit] - buka sementara\n"
            "/lockall - kunci semua\n"
            "/unlockall [menit] - buka semua sementara\n"
            "/launch <app> [menit] - buka izin + jalankan aplikasi terdaftar\n"
            "/pause [menit] - jeda seluruh enforcement\n"
            "/resume - aktifkan enforcement\n"
            "/logs [jumlah] - log terakhir (maks 50)\n"
            "/ping - cek bot\n\n"
            "Contoh:\n"
            "/unlock chrome 10\n"
            "/lock telegram\n"
            "/launch chrome 5"
        )

    async def cmd_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.authorized(update):
            return
        await update.effective_message.reply_text(
            self.status_text(),
            reply_markup=self.menu_markup(),
        )

    async def on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.authorized(update):
            return
        query = update.callback_query
        if not query:
            return

        await query.answer()
        data = query.data or ""

        if data == "menu:status":
            text = self.status_text()
        elif data == "menu:apps":
            text = self.apps_text()
        elif data == "menu:lockall":
            closed = self.core.lock_all(source="Telegram")
            text = f"🔒 Semua aplikasi dikunci. Proses ditutup: {closed}."
        elif data == "menu:unlockall5":
            self.core.unlock_all(5, source="Telegram")
            text = "🔓 Semua aplikasi dibuka 5 menit."
        elif data == "menu:pause5":
            self.core.pause(5)
            text = "⏸ Enforcement dijeda 5 menit."
        elif data == "menu:resume":
            self.core.resume()
            text = "▶️ Enforcement aktif."
        elif data == "menu:help":
            text = self.help_text()
        else:
            text = "Perintah tombol tidak dikenali."

        try:
            await query.edit_message_text(text=text, reply_markup=self.menu_markup())
        except Exception:
            await query.message.reply_text(text=text, reply_markup=self.menu_markup())

    def notify(self, text: str) -> None:
        if not self.ready.is_set() or not self.application or not self.loop:
            return

        import asyncio

        try:
            coro = self.application.bot.send_message(
                chat_id=self.owner_chat_id,
                text=text[:4000],
            )
            asyncio.run_coroutine_threadsafe(coro, self.loop)
        except Exception:
            LOGGER.exception("Failed to schedule Telegram notification")

    async def authorized(self, update: Update) -> bool:
        chat = update.effective_chat
        user = update.effective_user
        chat_id = chat.id if chat else 0

        if int(chat_id) == self.owner_chat_id:
            return True

        LOGGER.warning(
            "Unauthorized Telegram access chat_id=%s user_id=%s",
            chat_id,
            getattr(user, "id", None),
        )
        if update.effective_message:
            await update.effective_message.reply_text(
                "⛔ Tidak diizinkan.\n"
                f"Chat ID Anda: {chat_id}"
            )
        return False

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.authorized(update):
            return
        await update.effective_message.reply_text(
            "Windows App Locker terhubung. Gunakan tombol di bawah atau ketik /help.",
            reply_markup=self.menu_markup(),
        )

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.authorized(update):
            return
        await update.effective_message.reply_text(
            self.help_text(),
            reply_markup=self.menu_markup(),
        )

    async def cmd_ping(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.authorized(update):
            return
        await update.effective_message.reply_text(
            f"🏓 Online | {socket.gethostname()} | {time.strftime('%Y-%m-%d %H:%M:%S')}",
            reply_markup=self.menu_markup(),
        )

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.authorized(update):
            return
        await update.effective_message.reply_text(
            self.status_text(),
            reply_markup=self.menu_markup(),
        )

    async def cmd_apps(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.authorized(update):
            return
        await update.effective_message.reply_text(
            self.apps_text(),
            reply_markup=self.menu_markup(),
        )

    @staticmethod
    def parse_minutes(raw: str, default: int = 5) -> int:
        try:
            return max(1, min(int(raw), 1440))
        except Exception:
            return default

    async def cmd_lock(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.authorized(update):
            return
        if not context.args:
            await update.effective_message.reply_text("Format: /lock <app>")
            return

        query = " ".join(context.args)
        app_id, app = self.core.resolve_app(query)
        if not app_id:
            await update.effective_message.reply_text("Aplikasi tidak ditemukan / nama ambigu.")
            return

        self.core.lock_app(app_id, terminate_now=True, source="Telegram")
        await update.effective_message.reply_text(f"🔒 {app.get('name', app_id)} dikunci.")

    async def cmd_unlock(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.authorized(update):
            return
        if not context.args:
            await update.effective_message.reply_text("Format: /unlock <app> [menit]")
            return

        minutes = 5
        args = list(context.args)
        if len(args) >= 2 and args[-1].isdigit():
            minutes = self.parse_minutes(args.pop(), 5)

        query = " ".join(args)
        app_id, app = self.core.resolve_app(query)
        if not app_id:
            await update.effective_message.reply_text("Aplikasi tidak ditemukan / nama ambigu.")
            return

        self.core.unlock_app(app_id, minutes, source="Telegram")
        await update.effective_message.reply_text(
            f"🔓 {app.get('name', app_id)} dibuka {minutes} menit."
        )

    async def cmd_lockall(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.authorized(update):
            return
        closed = self.core.lock_all(source="Telegram")
        await update.effective_message.reply_text(
            f"🔒 Semua aplikasi dikunci. Proses ditutup: {closed}."
        )

    async def cmd_unlockall(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.authorized(update):
            return
        minutes = self.parse_minutes(context.args[0], 5) if context.args else 5
        self.core.unlock_all(minutes, source="Telegram")
        await update.effective_message.reply_text(
            f"🔓 Semua aplikasi dibuka {minutes} menit."
        )

    async def cmd_launch(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.authorized(update):
            return
        if not context.args:
            await update.effective_message.reply_text("Format: /launch <app> [menit]")
            return

        minutes = 5
        args = list(context.args)
        if len(args) >= 2 and args[-1].isdigit():
            minutes = self.parse_minutes(args.pop(), 5)

        query = " ".join(args)
        app_id, app = self.core.resolve_app(query)
        if not app_id:
            await update.effective_message.reply_text("Aplikasi tidak ditemukan / nama ambigu.")
            return

        ok = self.core.launch_registered(app_id, minutes, source="Telegram")
        await update.effective_message.reply_text(
            f"{'▶️' if ok else '⚠️'} {app.get('name', app_id)} "
            f"{'dijalankan' if ok else 'gagal dijalankan'}."
        )

    async def cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.authorized(update):
            return
        minutes = self.parse_minutes(context.args[0], 5) if context.args else 5
        self.core.pause(minutes)
        await update.effective_message.reply_text(
            f"⏸ Enforcement dijeda {minutes} menit."
        )

    async def cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.authorized(update):
            return
        self.core.resume()
        await update.effective_message.reply_text("▶️ Enforcement aktif.")

    async def cmd_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.authorized(update):
            return

        count = 20
        if context.args:
            try:
                count = max(1, min(int(context.args[0]), 50))
            except ValueError:
                pass

        try:
            lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = lines[-count:]
            text = "\n".join(tail)
            if len(text) > 3800:
                text = text[-3800:]
            await update.effective_message.reply_text(
                "📜 LOG TERAKHIR\n\n" + (text or "(kosong)")
            )
        except Exception as exc:
            await update.effective_message.reply_text(f"Gagal membaca log: {exc}")


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class LockerUI:
    def __init__(self, core: AppLockerCore):
        self.core = core
        self.root = tk.Tk()
        self.root.title(f"{APP_TITLE} {VERSION}")
        self.root.geometry("1040x620")
        self.root.minsize(820, 480)

        self.tray_icon: Optional[pystray.Icon] = None
        self.search_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="")

        self._configure_style()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.root.after(150, self.process_gui_queue)
        self.root.after(1500, self.periodic_refresh)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            if "vista" in style.theme_names():
                style.theme_use("vista")
        except Exception:
            pass

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x")

        title_box = ttk.Frame(header)
        title_box.pack(side="left", fill="x", expand=True)

        ttk.Label(
            title_box,
            text="Windows App Locker",
            font=("Segoe UI", 17, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            title_box,
            text="App-locker level user dengan kontrol lokal dan Telegram terbatas.",
        ).pack(anchor="w", pady=(2, 0))

        ttk.Label(
            header,
            textvariable=self.status_var,
            justify="right",
        ).pack(side="right", padx=(12, 0))

        search_row = ttk.Frame(outer)
        search_row.pack(fill="x", pady=(12, 8))
        ttk.Label(search_row, text="Cari:").pack(side="left")
        search_entry = ttk.Entry(search_row, textvariable=self.search_var)
        search_entry.pack(side="left", fill="x", expand=True, padx=(8, 8))
        search_entry.bind("<KeyRelease>", lambda _event: self.refresh())
        ttk.Button(search_row, text="Reset", command=self.clear_search).pack(side="left")

        table_frame = ttk.Frame(outer)
        table_frame.pack(fill="both", expand=True)

        cols = ("name", "process", "state", "enabled", "path")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=16)
        self.tree.heading("name", text="Nama")
        self.tree.heading("process", text="Process")
        self.tree.heading("state", text="Status")
        self.tree.heading("enabled", text="Proteksi")
        self.tree.heading("path", text="Executable")
        self.tree.column("name", width=150, minwidth=100)
        self.tree.column("process", width=145, minwidth=100)
        self.tree.column("state", width=145, minwidth=100)
        self.tree.column("enabled", width=90, minwidth=75, anchor="center")
        self.tree.column("path", width=460, minwidth=260)

        scroll_y = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scroll_x = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        self.tree.bind("<Double-1>", lambda _event: self.edit_selected())
        self.tree.bind("<Button-3>", self._show_context_menu)

        self.context_menu = tk.Menu(self.root, tearoff=False)
        self.context_menu.add_command(label="Kunci", command=self.lock_selected)
        self.context_menu.add_command(label="Buka sementara", command=self.unlock_selected)
        self.context_menu.add_command(label="Jalankan", command=self.launch_selected)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Edit nama", command=self.edit_selected)
        self.context_menu.add_command(label="Aktif / Nonaktif", command=self.toggle_selected_enabled)
        self.context_menu.add_command(label="Hapus", command=self.remove_selected)

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(10, 0))

        for text, command in (
            ("Tambah App", self.add_app),
            ("Edit", self.edit_selected),
            ("Hapus", self.remove_selected),
            ("Kunci", self.lock_selected),
            ("Buka Sementara", self.unlock_selected),
            ("Jalankan", self.launch_selected),
            ("Aktif/Nonaktif", self.toggle_selected_enabled),
            ("Kunci Semua", self.lock_all),
        ):
            ttk.Button(buttons, text=text, command=command).pack(side="left", padx=(0, 5))

        admin = ttk.Frame(outer)
        admin.pack(fill="x", pady=(8, 0))

        ttk.Button(admin, text="Pengaturan", command=self.settings_dialog).pack(side="left", padx=(0, 5))
        ttk.Button(admin, text="Telegram", command=self.telegram_settings).pack(side="left", padx=(0, 5))
        ttk.Button(admin, text="Autostart", command=self.toggle_autostart).pack(side="left", padx=(0, 5))
        ttk.Button(admin, text="Ganti PIN", command=self.change_pin).pack(side="left", padx=(0, 5))
        ttk.Button(admin, text="Folder Data", command=self.open_data_dir).pack(side="left", padx=(0, 5))

        ttk.Button(admin, text="Tentang", command=self.show_about).pack(side="right")
        ttk.Button(admin, text="Panduan", command=self.show_help).pack(side="right", padx=(0, 5))

        info = ttk.Label(
            outer,
            text=(
                "Telegram: /menu /status /apps /lock /unlock /lockall /unlockall "
                "/launch /pause /resume /logs"
            ),
        )
        info.pack(anchor="w", pady=(10, 0))

        self.refresh()

    def clear_search(self) -> None:
        self.search_var.set("")
        self.refresh()

    def _show_context_menu(self, event: tk.Event) -> None:
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.tree.focus(item)
            self.context_menu.tk_popup(event.x_root, event.y_root)

    def selected_app_id(self) -> Optional[str]:
        selected = self.tree.selection()
        return selected[0] if selected else None

    def _selected_app(self) -> tuple[Optional[str], dict[str, Any]]:
        app_id = self.selected_app_id()
        if not app_id:
            return None, {}
        return app_id, self.core.config.data.get("apps", {}).get(app_id, {})

    def refresh(self) -> None:
        selected = self.selected_app_id()
        query = self.search_var.get().strip().lower()

        for item in self.tree.get_children():
            self.tree.delete(item)

        now = time.time()
        for app_id, app in self.core.app_items():
            haystack = " ".join(
                [
                    app_id,
                    str(app.get("name", "")),
                    str(app.get("process_name", "")),
                    str(app.get("exe", "")),
                ]
            ).lower()
            if query and query not in haystack:
                continue

            remain = float(app.get("unlocked_until", 0) or 0) - now
            if not app.get("enabled", True):
                state = "Disabled"
            elif remain > 0:
                state = f"Unlocked {human_duration(remain)}"
            else:
                state = "Locked"

            self.tree.insert(
                "",
                "end",
                iid=app_id,
                values=(
                    app.get("name", app_id),
                    app.get("process_name", ""),
                    state,
                    "ON" if app.get("enabled", True) else "OFF",
                    app.get("exe", ""),
                ),
            )

        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected)
            self.tree.focus(selected)

        telegram_state = "OFF"
        if self.core.telegram:
            telegram_state = "ONLINE" if self.core.telegram.ready.is_set() else "CONNECTING"

        self.status_var.set(
            f"{'PAUSED' if self.core.is_paused() else 'ACTIVE'}  |  "
            f"Telegram: {telegram_state}  |  "
            f"Autostart: {'ON' if get_autostart() else 'OFF'}  |  v{VERSION}"
        )

    def periodic_refresh(self) -> None:
        try:
            self.refresh()
        finally:
            self.root.after(1500, self.periodic_refresh)

    def add_app(self) -> None:
        paths = filedialog.askopenfilenames(
            parent=self.root,
            title="Pilih aplikasi yang akan dilindungi",
            filetypes=[("Windows Application", "*.exe"), ("All files", "*.*")],
        )
        errors = []
        for value in paths:
            try:
                self.core.add_app(value)
            except ValueError as exc:
                errors.append(f"{Path(value).name}: {exc}")
        if errors:
            messagebox.showerror(APP_TITLE, "\n".join(errors), parent=self.root)
        self.refresh()

    def _ask_pin(self, title: str = "Verifikasi PIN", action: str = "pengaturan") -> bool:
        pin = simpledialog.askstring(
            title,
            "Masukkan PIN App Locker:",
            show="*",
            parent=self.root,
        )
        if pin is None:
            return False

        ok, error = self.core.verify_local_pin(pin, action)
        if not ok:
            messagebox.showerror(APP_TITLE, error, parent=self.root)
        return ok

    def edit_selected(self) -> None:
        app_id, app = self._selected_app()
        if not app_id:
            return
        if not self._ask_pin("Edit Aplikasi", f"mengedit {app.get('name', app_id)}"):
            return

        new_name = simpledialog.askstring(
            "Edit Aplikasi",
            "Nama tampilan:",
            initialvalue=str(app.get("name", app_id)),
            parent=self.root,
        )
        if new_name is None:
            return
        new_name = new_name.strip()
        if not new_name:
            messagebox.showerror(APP_TITLE, "Nama aplikasi tidak boleh kosong.", parent=self.root)
            return

        app["name"] = new_name[:100]
        self.core.config.save()
        self.core.notify(f"✏️ Nama aplikasi diperbarui: {new_name[:100]}")
        self.refresh()

    def toggle_selected_enabled(self) -> None:
        app_id, app = self._selected_app()
        if not app_id:
            return
        if not self._ask_pin("Ubah Proteksi", f"mengubah proteksi {app.get('name', app_id)}"):
            return

        target = not bool(app.get("enabled", True))
        app["enabled"] = target
        if not target:
            app["unlocked_until"] = 0
        self.core.config.save()
        self.core.notify(
            f"{'✅ Proteksi diaktifkan' if target else '⏸ Proteksi dinonaktifkan'}: "
            f"{app.get('name', app_id)}"
        )
        self.refresh()

    def remove_selected(self) -> None:
        app_id, app = self._selected_app()
        if not app_id:
            return
        if not self._ask_pin("Hapus Aplikasi", f"menghapus {app.get('name', app_id)}"):
            return
        if messagebox.askyesno(
            APP_TITLE,
            f"Hapus {app.get('name', app_id)} dari daftar App Locker?",
            parent=self.root,
        ):
            self.core.remove_app(app_id)
            self.refresh()

    def lock_selected(self) -> None:
        app_id = self.selected_app_id()
        if app_id:
            self.core.lock_app(app_id, True, "GUI")
            self.refresh()

    def unlock_selected(self) -> None:
        app_id, app = self._selected_app()
        if not app_id:
            return
        if not self._ask_pin("Buka Sementara", f"membuka {app.get('name', app_id)}"):
            return

        default_minutes = int(self.core.config.data.get("security", {}).get("local_unlock_minutes", 5) or 5)
        minutes = simpledialog.askinteger(
            "Durasi Unlock",
            "Buka berapa menit? (1-1440)",
            initialvalue=default_minutes,
            minvalue=1,
            maxvalue=1440,
            parent=self.root,
        )
        if minutes is None:
            return

        self.core.unlock_app(app_id, minutes, "GUI")
        self.refresh()

    def launch_selected(self) -> None:
        app_id, app = self._selected_app()
        if not app_id:
            return
        if not self._ask_pin("Jalankan Aplikasi", f"menjalankan {app.get('name', app_id)}"):
            return

        default_minutes = int(self.core.config.data.get("security", {}).get("local_unlock_minutes", 5) or 5)
        minutes = simpledialog.askinteger(
            "Durasi Unlock",
            "Beri izin sebelum menjalankan (menit):",
            initialvalue=default_minutes,
            minvalue=1,
            maxvalue=1440,
            parent=self.root,
        )
        if minutes is None:
            return

        if not self.core.launch_registered(app_id, minutes, source="GUI"):
            messagebox.showerror(APP_TITLE, "Aplikasi gagal dijalankan.", parent=self.root)
        self.refresh()

    def lock_all(self) -> None:
        self.core.lock_all("GUI")
        self.refresh()

    def settings_dialog(self) -> None:
        if not self._ask_pin("Pengaturan", "membuka pengaturan"):
            return

        security = self.core.config.data.setdefault("security", {})
        monitor = self.core.config.data.setdefault("monitor", {})

        minutes = simpledialog.askinteger(
            "Pengaturan",
            "Durasi unlock lokal default (menit):",
            initialvalue=int(security.get("local_unlock_minutes", 5) or 5),
            minvalue=1,
            maxvalue=1440,
            parent=self.root,
        )
        if minutes is None:
            return

        interval = simpledialog.askfloat(
            "Pengaturan",
            "Interval monitor proses dalam detik (0.15 - 5.0):",
            initialvalue=float(monitor.get("scan_interval", 0.35) or 0.35),
            minvalue=0.15,
            maxvalue=5.0,
            parent=self.root,
        )
        if interval is None:
            return

        security["local_unlock_minutes"] = int(minutes)
        monitor["scan_interval"] = float(interval)
        monitor["notify_blocked_open"] = messagebox.askyesno(
            "Pengaturan",
            "Kirim notifikasi Telegram saat aplikasi terkunci dicoba dibuka?",
            parent=self.root,
        )
        monitor["notify_allowed_open"] = messagebox.askyesno(
            "Pengaturan",
            "Kirim notifikasi Telegram saat aplikasi dibuka dalam masa unlock?",
            parent=self.root,
        )

        self.core.config.save()
        messagebox.showinfo(APP_TITLE, "Pengaturan disimpan.", parent=self.root)
        self.refresh()

    def telegram_settings(self) -> None:
        if not self._ask_pin("Pengaturan Telegram", "mengubah pengaturan Telegram"):
            return

        tg = self.core.config.data.setdefault("telegram", {})
        enabled = messagebox.askyesno(
            "Telegram",
            "Aktifkan kontrol dan notifikasi Telegram?",
            parent=self.root,
        )

        owner_raw = simpledialog.askstring(
            "Telegram Owner Chat ID",
            "Chat ID pemilik:",
            initialvalue=str(tg.get("owner_chat_id", "") or ""),
            parent=self.root,
        )
        if owner_raw is None:
            return

        try:
            owner_id = int(owner_raw.strip()) if owner_raw.strip() else 0
        except ValueError:
            messagebox.showerror(APP_TITLE, "Chat ID harus berupa angka.", parent=self.root)
            return

        token = simpledialog.askstring(
            "Telegram Bot Token",
            "Token baru (kosongkan untuk mempertahankan token lama):",
            show="*",
            parent=self.root,
        )
        if token is None:
            return

        if enabled and owner_id == 0:
            messagebox.showerror(APP_TITLE, "Chat ID wajib diisi saat Telegram aktif.", parent=self.root)
            return

        if token.strip():
            tg["token_dpapi"] = dpapi_encrypt(token.strip())
        tg["owner_chat_id"] = owner_id
        tg["enabled"] = enabled
        self.core.config.save()

        messagebox.showinfo(
            APP_TITLE,
            "Pengaturan Telegram disimpan. Restart App Locker agar koneksi Telegram dimuat ulang.",
            parent=self.root,
        )
        self.refresh()

    def change_pin(self) -> None:
        if not self._ask_pin("PIN Lama", "mengganti PIN"):
            return

        new_pin = simpledialog.askstring(
            "PIN Baru",
            "Masukkan PIN baru minimal 4 karakter:",
            show="*",
            parent=self.root,
        )
        if not new_pin or len(new_pin) < 4:
            messagebox.showerror(APP_TITLE, "PIN minimal 4 karakter.", parent=self.root)
            return

        confirm = simpledialog.askstring(
            "Konfirmasi PIN",
            "Masukkan ulang PIN baru:",
            show="*",
            parent=self.root,
        )
        if confirm != new_pin:
            messagebox.showerror(APP_TITLE, "PIN tidak sama.", parent=self.root)
            return

        self.core.config.data["security"]["pin"] = make_pin_record(new_pin)
        self.core.config.save()
        self.core.notify("🔑 PIN App Locker diubah secara lokal.")
        messagebox.showinfo(APP_TITLE, "PIN berhasil diubah.", parent=self.root)

    def toggle_autostart(self) -> None:
        if not self._ask_pin("Autostart", "mengubah autostart"):
            return

        target = not get_autostart()
        try:
            set_autostart(target)
            self.core.config.data["ui"]["autostart"] = target
            self.core.config.save()
            self.refresh()
            messagebox.showinfo(
                APP_TITLE,
                f"Autostart {'diaktifkan' if target else 'dinonaktifkan'}.",
                parent=self.root,
            )
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Gagal mengubah autostart:\n{exc}", parent=self.root)

    def open_data_dir(self) -> None:
        try:
            os.startfile(str(APP_DIR))
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Gagal membuka folder data:\n{exc}", parent=self.root)

    def show_help(self) -> None:
        messagebox.showinfo(
            "Panduan Windows App Locker",
            "1. Klik Tambah App dan pilih file .exe.\n"
            "2. Aplikasi baru langsung berada dalam status Locked.\n"
            "3. Ketika aplikasi terkunci dibuka, proses ditutup lalu dialog PIN muncul.\n"
            "4. PIN yang benar membuka aplikasi sementara sesuai durasi konfigurasi.\n"
            "5. Double-click aplikasi untuk mengubah nama tampilan.\n"
            "6. Tombol Close menyembunyikan jendela ke System Tray.\n"
            "7. Telegram hanya menerima kontrol dari Owner Chat ID yang tersimpan.\n\n"
            "App Locker ini bekerja pada level user Windows; Administrator tetap memiliki kontrol penuh atas PC.",
            parent=self.root,
        )

    def show_about(self) -> None:
        messagebox.showinfo(
            "Tentang",
            f"{APP_TITLE}\nVersi {VERSION}\n\n"
            "Windows 10/11 • Python 3.10+\n"
            "PIN PBKDF2 • Token Telegram DPAPI • System Tray • Autostart HKCU\n\n"
            "Tidak menyediakan arbitrary shell, keylogger, screenshot remote, credential capture, atau stealth persistence.",
            parent=self.root,
        )

    def process_gui_queue(self) -> None:
        while True:
            try:
                action, payload = self.core.gui_queue.get_nowait()
            except queue.Empty:
                break

            if action == "unlock_prompt":
                self._show_unlock_prompt(payload)
            elif action == "error":
                messagebox.showerror(APP_TITLE, str(payload), parent=self.root)
            elif action == "refresh":
                self.refresh()

        self.root.after(150, self.process_gui_queue)

    def _show_unlock_prompt(self, req: UnlockRequest) -> None:
        self.show_window()
        pin = simpledialog.askstring(
            f"Unlock — {req.app_name}",
            f"{req.app_name} sedang terkunci.\n\nMasukkan PIN:",
            show="*",
            parent=self.root,
        )
        self.core.handle_pin_result(req, pin)

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(250, lambda: self.root.attributes("-topmost", False))
        self.refresh()

    def hide_window(self) -> None:
        self.root.withdraw()

    def create_tray(self) -> None:
        img = Image.new("RGB", (64, 64), "white")
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle((12, 28, 52, 58), radius=6, fill="black")
        draw.arc((20, 6, 44, 38), start=180, end=360, fill="black", width=7)

        menu = pystray.Menu(
            pystray.MenuItem("Buka App Locker", lambda *_: self.root.after(0, self.show_window)),
            pystray.MenuItem("Kunci Semua", lambda *_: self.root.after(0, self.lock_all)),
            pystray.MenuItem("Pause 5 Menit", lambda *_: self.root.after(0, lambda: self.core.pause(5))),
            pystray.MenuItem("Resume", lambda *_: self.root.after(0, self.core.resume)),
            pystray.MenuItem("Keluar", lambda *_: self.root.after(0, self.exit_app)),
        )

        self.tray_icon = pystray.Icon(
            "WinAppLockerBot",
            img,
            APP_TITLE,
            menu,
        )
        threading.Thread(
            target=self.tray_icon.run,
            name="SystemTray",
            daemon=True,
        ).start()

    def exit_app(self) -> None:
        if not self._ask_pin("Keluar dari App Locker", "keluar dari aplikasi"):
            return

        self.core.stop()
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.after(100, self.root.destroy)

    def run(self, start_hidden: bool = False) -> None:
        self.create_tray()
        if start_hidden:
            self.root.withdraw()
        else:
            self.root.deiconify()
        self.root.mainloop()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="windows_app_locker.py",
        description="Windows App Locker with optional Telegram control.",
    )
    parser.add_argument(
        "--background",
        action="store_true",
        help="Start minimized to the system tray.",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Run local diagnostics and exit.",
    )
    parser.add_argument(
        "--show-data-dir",
        action="store_true",
        help="Print the application data directory and exit.",
    )
    parser.add_argument(
        "--no-telegram",
        action="store_true",
        help="Disable Telegram only for this process run.",
    )
    parser.add_argument(
        "--no-monitor",
        action="store_true",
        help="Disable process enforcement only for this process run.",
    )
    return parser


def run_doctor() -> int:
    checks: list[tuple[str, bool, str]] = []

    checks.append(("Windows", is_windows(), sys.platform))
    checks.append(("Python >= 3.10", sys.version_info >= (3, 10), sys.version.split()[0]))

    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        probe = APP_DIR / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        checks.append(("Data directory writable", True, str(APP_DIR)))
    except Exception as exc:
        checks.append(("Data directory writable", False, str(exc)))

    try:
        sample = "windows-app-locker-doctor"
        protected = dpapi_encrypt(sample)
        restored = dpapi_decrypt(protected)
        checks.append(("Windows DPAPI", restored == sample, "user-scope encrypt/decrypt"))
    except Exception as exc:
        checks.append(("Windows DPAPI", False, str(exc)))

    try:
        _ = get_autostart()
        checks.append(("HKCU autostart access", True, "registry readable"))
    except Exception as exc:
        checks.append(("HKCU autostart access", False, str(exc)))

    if CONFIG_PATH.exists():
        try:
            cfg = ConfigStore(CONFIG_PATH)
            cfg.load()
            pin_ok = bool(cfg.data.get("security", {}).get("pin", {}))
            checks.append(("Config readable", True, str(CONFIG_PATH)))
            checks.append(("PIN configured", pin_ok, "PBKDF2 record present" if pin_ok else "missing"))

            tg = cfg.data.get("telegram", {})
            token_blob = str(tg.get("token_dpapi", "") or "")
            owner_id = int(tg.get("owner_chat_id", 0) or 0)
            if token_blob:
                try:
                    token_ok = bool(dpapi_decrypt(token_blob))
                except Exception:
                    token_ok = False
                checks.append(("Telegram token decrypt", token_ok, "DPAPI protected"))
            checks.append(("Telegram owner Chat ID", owner_id != 0, str(owner_id or "not set")))
        except Exception as exc:
            checks.append(("Config readable", False, str(exc)))
    else:
        checks.append(("Config", True, "not created yet; first-run wizard will create it"))

    try:
        checks.append(("psutil", bool(psutil.__version__), psutil.__version__))
    except Exception:
        checks.append(("psutil", False, "not available"))

    try:
        import telegram as telegram_pkg
        checks.append(("python-telegram-bot", True, getattr(telegram_pkg, "__version__", "installed")))
    except Exception as exc:
        checks.append(("python-telegram-bot", False, str(exc)))

    print(f"{APP_TITLE} doctor | v{VERSION}")
    print("-" * 64)
    failed = 0
    for name, ok, detail in checks:
        state = "OK" if ok else "FAIL"
        print(f"[{state:<4}] {name:<26} {detail}")
        if not ok:
            failed += 1

    print("-" * 64)
    print(f"Result: {len(checks) - failed} passed, {failed} failed")
    return 1 if failed else 0


def main() -> int:
    args = build_arg_parser().parse_args()

    if not is_windows():
        print("Script ini khusus Windows 10/11.")
        return 1

    if args.show_data_dir:
        print(APP_DIR)
        return 0

    if args.doctor:
        return run_doctor()

    mutex_handle = enforce_single_instance()
    _ = mutex_handle  # Keep handle alive.

    if not CONFIG_PATH.exists():
        first_run_setup()

    store = ConfigStore(CONFIG_PATH)
    store.load()

    # Restore transparent per-user autostart if the user enabled it.
    if store.data.get("ui", {}).get("autostart", True):
        try:
            if not get_autostart():
                set_autostart(True)
        except Exception:
            LOGGER.exception("Unable to restore autostart")

    core = AppLockerCore(store)
    ui = LockerUI(core)
    core.set_ui(ui)

    if not args.no_monitor:
        monitor_thread = threading.Thread(
            target=core.monitor_loop,
            name="ProcessMonitor",
            daemon=True,
        )
        monitor_thread.start()
    else:
        LOGGER.warning("Process monitor disabled for this run")

    tg_cfg = store.data.get("telegram", {})
    if tg_cfg.get("enabled", True) and not args.no_telegram:
        try:
            token = dpapi_decrypt(tg_cfg.get("token_dpapi", ""))
            owner_chat_id = int(tg_cfg.get("owner_chat_id", 0))
            if token and owner_chat_id:
                telegram = TelegramController(core, token, owner_chat_id)
                core.set_telegram(telegram)
                telegram.start()
            else:
                LOGGER.warning("Telegram config incomplete")
        except Exception:
            LOGGER.exception("Telegram setup failed")
    elif args.no_telegram:
        LOGGER.warning("Telegram disabled for this run")

    # A manual launch always shows the dashboard. Only --background starts hidden.
    start_hidden = bool(args.background)

    try:
        ui.run(start_hidden=start_hidden)
    except KeyboardInterrupt:
        pass
    except Exception:
        LOGGER.error("Fatal UI error:\n%s", traceback.format_exc())
    finally:
        core.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
