# Installation

## Recommended installation

Open PowerShell in the repository directory:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

The installer:

1. verifies Windows and Python 3.10+;
2. copies the project into `%LOCALAPPDATA%\Programs\WindowsAppLocker`;
3. creates a private virtual environment;
4. installs dependencies from `requirements.txt`;
5. creates Start Menu and Desktop shortcuts;
6. launches the application normally so the first-run wizard can finish configuration.

Administrator rights are not required for the default per-user installation.

## Manual installation

```powershell
python -m pip install -r requirements.txt
python windows_app_locker.py
```

## First run

Prepare:
- Telegram bot token;
- Telegram owner Chat ID;
- a local PIN;
- optional `.exe` files to protect.

The first-run wizard stores runtime data in `%APPDATA%\WinAppLockerBot`.

## Autostart

If enabled, the application registers a transparent per-user startup command under:

```text
HKCU\Software\Microsoft\Windows\CurrentVersion\Run
```

The startup command uses `--background` so the application starts in the system tray. Manually opening the shortcut shows the dashboard.

## Upgrade

Pull or download the new release, then run `install.ps1` again. The installer updates program files but does not delete `%APPDATA%\WinAppLockerBot`.

## Uninstall

Exit Windows App Locker from the tray first, then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1
```

To also delete runtime configuration/logs:

```powershell
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1 -RemoveData
```
