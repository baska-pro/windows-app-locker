# Troubleshooting

## Run diagnostics

```powershell
python windows_app_locker.py --doctor
```

The doctor checks Windows/Python, data-directory write access, DPAPI, registry access, config readability, PIN presence, and Python dependencies.

## App opens but is not blocked

- Confirm the app is listed and **Proteksi = ON**.
- Confirm the dashboard status is not **PAUSED**.
- Some elevated/admin processes may not be controllable from a non-elevated App Locker process.
- If the executable path changed after an application update, remove and re-add that application.

## App is blocked but does not reopen after PIN

The original process command line may not always be reusable. Use the dashboard **Jalankan** action or re-add the application using its current executable.

## Telegram is offline

- Verify Internet access.
- Open **Telegram** settings and confirm the Owner Chat ID.
- Re-enter a new bot token if the previous token was revoked.
- Restart App Locker after changing Telegram settings.
- Inspect `%APPDATA%\WinAppLockerBot\app_locker.log`.

## Dashboard does not appear after login

Autostart intentionally uses `--background`, so it starts in the system tray. Double-click the Start Menu/Desktop shortcut to show the dashboard.

## Manual launch says already running

Only one instance is allowed per Windows user. Use the system-tray icon to show the existing instance, or exit it before starting another copy.

## Config is damaged

The application backs up an unreadable config as `config.corrupt-YYYYMMDD-HHMMSS.json` and loads safe defaults. You may then repair settings from the dashboard or re-run setup after moving the damaged config aside.
