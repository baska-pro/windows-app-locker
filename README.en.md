# Windows App Locker

[![CI](https://github.com/baska-pro/windows-app-locker/actions/workflows/ci.yml/badge.svg)](https://github.com/baska-pro/windows-app-locker/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/baska-pro/windows-app-locker?style=flat-square)](https://github.com/baska-pro/windows-app-locker/releases/latest)
[![License: Baska-Pro Personal Use](https://img.shields.io/badge/License-Baska--Pro%20Personal%20Use%201.0-blue.svg?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D4?style=flat-square)](#requirements)

**Windows App Locker v2.0.0** is a per-user Windows application locker with a local dashboard, PIN-based temporary unlock, system tray operation, per-user autostart, logging, and owner-only Telegram control.

> This project is not a replacement for Windows AppLocker, WDAC, Group Policy, or a kernel-level security boundary. A Windows Administrator can still stop or bypass the application.

## Highlights

- PBKDF2-HMAC-SHA256 PIN record with random salt.
- Telegram bot token protected with Windows DPAPI.
- Registered-process monitoring with exact executable-path preference.
- Temporary unlock and controlled launch for registered applications only.
- Searchable GUI, context menu, enable/disable protection, settings, help, and system tray.
- Transparent per-user autostart through HKCU Run.
- Owner-only Telegram commands and inline control menu.
- Rotating logs, configuration recovery, notification throttling, and single-instance protection.
- PowerShell installer/uninstaller and GitHub Actions CI.

## Requirements

- Windows 10/11.
- Python 3.10+.
- Internet access if Telegram is enabled.

## Install

```powershell
git clone https://github.com/baska-pro/windows-app-locker.git
cd windows-app-locker
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Manual installation:

```powershell
python -m pip install -r requirements.txt
python windows_app_locker.py
```

## Telegram commands

```text
/menu /status /apps /lock /unlock /lockall /unlockall
/launch /pause /resume /logs /ping /help
```

Telegram control accepts only the configured owner Chat ID. `/launch` can launch registered applications only; arbitrary shell execution is intentionally excluded.

## Diagnostics

```powershell
python windows_app_locker.py --version
python windows_app_locker.py --doctor
python windows_app_locker.py --show-data-dir
```

## Documentation

See `docs/` for installation, Telegram setup, troubleshooting, security model, and GitHub publishing instructions.

## License

Personal/private/non-commercial viewing, use, study, testing, and modification are permitted. Redistribution, resale, rebranding, public republishing, SaaS, and commercial use require prior written permission. See [LICENSE](LICENSE).
