# Windows App Locker

[![CI](https://github.com/baska-pro/windows-app-locker/actions/workflows/ci.yml/badge.svg)](https://github.com/baska-pro/windows-app-locker/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/baska-pro/windows-app-locker?style=flat-square)](https://github.com/baska-pro/windows-app-locker/releases/latest)
[![License: Baska-Pro Personal Use](https://img.shields.io/badge/License-Baska--Pro%20Personal%20Use%201.0-blue.svg?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D4?style=flat-square)](#persyaratan)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square)](#persyaratan)

**Windows App Locker v2.0.0** adalah aplikasi pengunci aplikasi Windows level user dengan dashboard lokal, PIN, System Tray, autostart per-user, logging, serta kontrol Telegram yang dibatasi hanya untuk pemilik.

> App Locker ini bukan pengganti AppLocker/WDAC/Group Policy Windows. Administrator Windows tetap dapat menghentikan proses atau mengubah konfigurasi sistem.

## Fitur

- First-run setup wizard untuk Token Telegram, Owner Chat ID, PIN, aplikasi awal, dan autostart.
- PIN disimpan sebagai PBKDF2-HMAC-SHA256 dengan salt acak; PIN tidak disimpan plaintext.
- Token Telegram disimpan dengan Windows DPAPI untuk user Windows yang sama.
- Monitor aplikasi terdaftar menggunakan `psutil`.
- Pencocokan executable mengutamakan full path agar tidak salah menutup program lain dengan nama proses yang sama.
- Aplikasi terkunci akan ditutup lalu dialog PIN lokal ditampilkan.
- Temporary unlock 1-1440 menit.
- Dashboard dengan pencarian, edit nama, enable/disable protection, launch, lock, unlock, settings, Help, dan About.
- Double-click dan context menu pada daftar aplikasi.
- System Tray; tombol Close menyembunyikan dashboard, bukan mematikan proteksi.
- Autostart transparan per-user melalui `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.
- Telegram owner-only commands dan inline-button menu.
- Rotating log, throttling notifikasi block, config recovery, dan single-instance mutex.
- Diagnostic CLI `--doctor`.
- Installer/uninstaller PowerShell dan GitHub Actions CI.

## Persyaratan

- Windows 10 atau Windows 11.
- Python 3.10 atau lebih baru.
- Akses internet jika Telegram diaktifkan.
- Tidak perlu Administrator untuk instalasi default per-user.

## Instalasi cepat

```powershell
git clone https://github.com/baska-pro/windows-app-locker.git
cd windows-app-locker
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Installer membuat virtual environment, memasang dependency, menyalin project ke `%LOCALAPPDATA%\Programs\WindowsAppLocker`, membuat shortcut Start Menu/Desktop, lalu membuka aplikasi untuk setup pertama.

Alternatif manual:

```powershell
python -m pip install -r requirements.txt
python windows_app_locker.py
```

## Setup pertama

Saat pertama dijalankan:

1. Masukkan Telegram Bot Token dari BotFather.
2. Masukkan Owner Chat ID.
3. Buat PIN minimal 4 karakter.
4. Pilih aplikasi `.exe` yang ingin langsung dilindungi, jika ada.
5. Pilih apakah autostart aktif saat login Windows.

Config tersimpan di `%APPDATA%\WinAppLockerBot\config.json`. Token Telegram di dalam config tidak disimpan plaintext.

## Telegram

Perintah utama:

```text
/menu
/status
/apps
/lock <app>
/unlock <app> [menit]
/lockall
/unlockall [menit]
/launch <app> [menit]
/pause [menit]
/resume
/logs [jumlah]
/ping
/help
```

Semua kontrol hanya menerima Owner Chat ID yang tersimpan. `/launch` hanya dapat menjalankan executable yang sudah terdaftar; tidak ada arbitrary shell execution.

Lihat [docs/TELEGRAM.md](docs/TELEGRAM.md) untuk panduan lengkap.

## CLI diagnostik

```powershell
python windows_app_locker.py --version
python windows_app_locker.py --doctor
python windows_app_locker.py --show-data-dir
```

Opsi sesi:

```powershell
python windows_app_locker.py --background
python windows_app_locker.py --no-telegram
python windows_app_locker.py --no-monitor
```

`--no-monitor` hanya untuk troubleshooting dan menonaktifkan enforcement selama proses tersebut berjalan.

## Struktur repository

```text
windows-app-locker/
├─ .github/
│  ├─ ISSUE_TEMPLATE/
│  ├─ workflows/ci.yml
│  └─ pull_request_template.md
├─ assets/screenshots/
├─ docs/
├─ scripts/
├─ windows_app_locker.py
├─ install.ps1
├─ uninstall.ps1
├─ requirements.txt
├─ VERSION
├─ CHANGELOG.md
├─ SECURITY.md
├─ CONTRIBUTING.md
├─ LICENSE
└─ README.md
```

## Data runtime

Default:

```text
%APPDATA%\WinAppLockerBot\
├─ config.json
└─ app_locker.log
```

File runtime dan credential tidak boleh dimasukkan ke Git. `.gitignore` sudah disiapkan.

## Batasan

- Ini adalah locker level user, bukan boundary keamanan kernel.
- Administrator dapat mematikan aplikasi atau menghapus autostart.
- Enforcement berbasis monitoring proses; pada beberapa aplikasi jendela dapat muncul sangat singkat sebelum proses ditutup.
- Aplikasi UWP/Microsoft Store tidak selalu memiliki executable tradisional yang cocok untuk model ini.
- Proses sistem Windows dan interpreter Python yang menjalankan App Locker diblokir dari daftar proteksi untuk mencegah self-lock.

## Dokumentasi

- [Instalasi](docs/INSTALLATION.md)
- [Telegram](docs/TELEGRAM.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Security Model](docs/SECURITY_MODEL.md)
- [Publish ke GitHub](docs/PUBLISH_GITHUB.md)

## License

Source dapat dilihat, dipelajari, dijalankan, diuji, dan dimodifikasi untuk penggunaan personal/private/non-commercial. Redistribusi, penjualan, rebranding, publikasi ulang, SaaS, atau penggunaan komersial memerlukan izin tertulis. Lihat [LICENSE](LICENSE).
