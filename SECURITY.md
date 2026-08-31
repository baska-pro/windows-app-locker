# Security Policy

## Supported version

Security fixes target the latest release, currently **2.0.x**.

## Security model

Windows App Locker is a **per-user convenience/control layer**, not a Windows kernel security boundary. A local Windows Administrator can stop the process, modify registry values, change files, or otherwise bypass the locker.

The project intentionally does **not** provide arbitrary remote shell execution, keylogging, remote screen capture, microphone capture, credential harvesting, or stealth persistence. Telegram control is restricted to the configured owner Chat ID.

## Sensitive data

- Telegram bot tokens are encrypted using Windows DPAPI for the current Windows user.
- PINs are stored using PBKDF2-HMAC-SHA256 with a random salt.
- Runtime configuration and logs belong under `%APPDATA%\WinAppLockerBot` and must never be committed.

## Reporting a vulnerability

Do not publish secrets, tokens, or private logs in a public issue. Report the minimum reproduction details needed and redact credentials. For sensitive reports, contact the repository owner through the GitHub profile before disclosing technical details publicly.
