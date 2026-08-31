# Publish to GitHub

Target repository name: **windows-app-locker**

## 1. Create the repository

On GitHub, create a new **public** repository:

```text
Repository name: windows-app-locker
Description: User-level Windows application locker with PIN protection, system tray, per-user autostart, diagnostics, and owner-only Telegram controls.
```

Do not initialize it with a README, `.gitignore`, or license because this package already contains them.

Recommended topics:

```text
windows
python
app-locker
telegram-bot
security-tools
system-tray
windows-11
windows-10
dpapi
productivity
```

## 2. Initialize Git locally

From the extracted project folder:

```bash
git init
git branch -M main
git add .
git commit -m "Initial release v2.0.0"
```

## 3. Add the GitHub remote

```bash
git remote add origin https://github.com/baska-pro/windows-app-locker.git
git push -u origin main
```

## 4. Verify GitHub Actions

Open the **Actions** tab and wait for the `CI` workflow. It should validate required files, version consistency, Python syntax, dependencies, diagnostics, installer PowerShell syntax, repository hygiene, and credential hygiene.

## 5. Check the repository page

Confirm:
- README renders correctly;
- CI badge becomes green;
- LICENSE is present;
- `VERSION` is `2.0.0`;
- no config, log, token, Chat ID, or runtime file is tracked.

## 6. Create the first tag

After CI is green:

```bash
git tag -a v2.0.0 -m "Windows App Locker v2.0.0"
git push origin v2.0.0
```

## 7. Build a release package

On Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

The output appears under `dist/`.

## 8. Create GitHub Release

Open **Releases → Draft a new release**:

```text
Tag: v2.0.0
Title: Windows App Locker v2.0.0
```

Use `RELEASE_NOTES_v2.0.0.md` as the release description and attach the ZIP from `dist/`.

## 9. Final verification

Download the release ZIP on a clean Windows test account and run:

```powershell
python windows_app_locker.py --version
python windows_app_locker.py --doctor
```

Then perform one real first-run setup with a dedicated Telegram bot token. Never use or publish a production token in screenshots, issues, commits, or release assets.
