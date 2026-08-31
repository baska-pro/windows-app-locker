[CmdletBinding()]
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\WindowsAppLocker",
    [switch]$RemoveData
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($env:OS -ne 'Windows_NT') {
    throw 'Windows App Locker uninstaller only supports Windows.'
}

Write-Host 'Exit Windows App Locker from the system tray before continuing.'

$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
try {
    Remove-ItemProperty -Path $RunKey -Name 'WinAppLockerBot' -ErrorAction SilentlyContinue
} catch {
    Write-Warning "Unable to remove autostart entry: $($_.Exception.Message)"
}

$StartMenu = [Environment]::GetFolderPath('StartMenu')
$Desktop = [Environment]::GetFolderPath('Desktop')
$Shortcuts = @(
    (Join-Path (Join-Path $StartMenu 'Programs') 'Windows App Locker.lnk')
)
if ($Desktop) {
    $Shortcuts += (Join-Path $Desktop 'Windows App Locker.lnk')
}

foreach ($shortcut in $Shortcuts) {
    Remove-Item -LiteralPath $shortcut -Force -ErrorAction SilentlyContinue
}

if (Test-Path -LiteralPath $InstallDir) {
    try {
        Remove-Item -LiteralPath $InstallDir -Recurse -Force
    } catch {
        throw "Unable to remove $InstallDir. Make sure Windows App Locker is not running. $($_.Exception.Message)"
    }
}

if ($RemoveData) {
    $DataDir = Join-Path $env:APPDATA 'WinAppLockerBot'
    if (Test-Path -LiteralPath $DataDir) {
        Remove-Item -LiteralPath $DataDir -Recurse -Force
    }
    Write-Host 'Application and user data removed.' -ForegroundColor Green
} else {
    Write-Host 'Application removed. User config/logs were preserved.' -ForegroundColor Green
    Write-Host 'Use -RemoveData if you also want to delete %APPDATA%\WinAppLockerBot.'
}
