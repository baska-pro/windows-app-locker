# Security Model

Windows App Locker is intentionally designed as a **user-level application control utility**.

## What it protects against

It can prevent a normal application registered by executable path from remaining open while its lock is active, and can require a local PIN before granting a temporary unlock.

## What it does not protect against

A Windows Administrator can stop the App Locker process, modify its files, remove its HKCU autostart entry, change file permissions, or use other Windows mechanisms to bypass the user-level monitor.

This project is not a replacement for Microsoft AppLocker, WDAC, enterprise endpoint management, Group Policy, or kernel security.

## Credential handling

- PIN: PBKDF2-HMAC-SHA256 + random salt.
- Telegram token: Windows DPAPI, current-user scope.
- Runtime data: `%APPDATA%\WinAppLockerBot`.

## Remote-control boundaries

Telegram is owner-Chat-ID only and controls registered applications only. The project intentionally excludes arbitrary shell execution, keylogging, credential capture, remote screen capture, microphone recording, and stealth persistence.

## Process matching

Exact executable path is preferred. Process-name fallback is used only when process path information is unavailable. This reduces the chance of terminating an unrelated program with the same executable filename.
