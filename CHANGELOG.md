# Changelog

All notable changes to Windows App Locker are documented here.

## Unreleased

### Documentation
- Added the public screenshot gallery for dashboard, application, website, folder, and health views.
- Added screenshot references to both Indonesian and English READMEs.
- Added screenshot publishing/privacy checks to the GitHub publishing guide.

## 2.0.0 - 2026-08-31

### Added
- Modernized dashboard with search, context menu, edit-name, enable/disable protection, settings, help, and About.
- Telegram inline-button control menu via `/menu`.
- Local diagnostic command `--doctor`.
- `--show-data-dir`, `--no-telegram`, and `--no-monitor` runtime flags.
- Config corruption backup/recovery.
- Duplicate executable detection and safer exact-path process matching.
- PIN verification reuse for sensitive local settings.
- Block-notification throttling to reduce Telegram spam.
- Installer, uninstaller, release checker, release builder, CI workflow, and complete GitHub documentation.

### Changed
- Manual launch now opens the dashboard; only `--background` starts hidden in the tray.
- Application management validates `.exe` paths and prevents protecting the current Python interpreter.
- Telegram status output includes active protection count and application version.

### Security
- Telegram token remains protected with Windows DPAPI.
- PIN remains stored as a PBKDF2 record, never plaintext.
- No arbitrary shell execution, keylogging, remote screenshots, credential capture, or stealth persistence was added.

## 1.0.0
- Initial Windows App Locker + Telegram Control implementation.
