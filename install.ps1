[CmdletBinding()]
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\WindowsAppLocker",
    [switch]$NoDesktopShortcut,
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($env:OS -ne 'Windows_NT') {
    throw 'Windows App Locker installer only supports Windows.'
}

$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$MainScript = Join-Path $SourceDir 'windows_app_locker.py'
$Requirements = Join-Path $SourceDir 'requirements.txt'

foreach ($required in @($MainScript, $Requirements)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required file not found: $required"
    }
}

function Get-PythonCommand {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @{ Command = 'py'; Prefix = @('-3') }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @{ Command = 'python'; Prefix = @() }
    }
    throw 'Python 3.10+ was not found. Install Python from python.org, then run this installer again.'
}

$Python = Get-PythonCommand
$PythonCommand = [string]$Python.Command
$PythonPrefix = [string[]]$Python.Prefix
$VersionCode = @'
import sys
print('.'.join(map(str, sys.version_info[:3])))
raise SystemExit(0 if sys.version_info >= (3, 10) else 2)
'@

& $PythonCommand @PythonPrefix -c $VersionCode
if ($LASTEXITCODE -ne 0) {
    throw 'Python 3.10 or newer is required.'
}

Write-Host "[1/6] Preparing install directory: $InstallDir"
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null

$FilesToCopy = @(
    'windows_app_locker.py',
    'requirements.txt',
    'VERSION',
    'LICENSE',
    'README.md'
)

Write-Host '[2/6] Copying application files'
foreach ($name in $FilesToCopy) {
    $source = Join-Path $SourceDir $name
    if (Test-Path -LiteralPath $source -PathType Leaf) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $InstallDir $name) -Force
    }
}

$VenvDir = Join-Path $InstallDir '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$VenvPythonW = Join-Path $VenvDir 'Scripts\pythonw.exe'

if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    Write-Host '[3/6] Creating virtual environment'
    & $PythonCommand @PythonPrefix -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to create Python virtual environment.'
    }
} else {
    Write-Host '[3/6] Virtual environment already exists'
}

Write-Host '[4/6] Installing/updating dependencies'
& $VenvPython -m pip install --disable-pip-version-check --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw 'Failed to update pip tooling.' }

& $VenvPython -m pip install --disable-pip-version-check -r (Join-Path $InstallDir 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Failed to install application dependencies.' }

& $VenvPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Installed dependencies are inconsistent.' }

Write-Host '[5/6] Creating shortcuts'
$WshShell = New-Object -ComObject WScript.Shell
$StartMenu = [Environment]::GetFolderPath('StartMenu')
$ProgramsDir = Join-Path $StartMenu 'Programs'
$StartShortcut = Join-Path $ProgramsDir 'Windows App Locker.lnk'

function New-AppShortcut([string]$ShortcutPath) {
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $VenvPythonW
    $Shortcut.Arguments = '"' + (Join-Path $InstallDir 'windows_app_locker.py') + '"'
    $Shortcut.WorkingDirectory = $InstallDir
    $Shortcut.Description = 'Windows App Locker'
    $Shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,48"
    $Shortcut.Save()
}

New-AppShortcut $StartShortcut

if (-not $NoDesktopShortcut) {
    $Desktop = [Environment]::GetFolderPath('Desktop')
    if ($Desktop) {
        New-AppShortcut (Join-Path $Desktop 'Windows App Locker.lnk')
    }
}

Write-Host '[6/6] Validating installation'
& $VenvPython (Join-Path $InstallDir 'windows_app_locker.py') --version
if ($LASTEXITCODE -ne 0) { throw 'Application version check failed.' }

Write-Host ''
Write-Host 'Windows App Locker installation completed.' -ForegroundColor Green
Write-Host "Install directory: $InstallDir"
Write-Host 'Runtime config will be stored under %APPDATA%\WinAppLockerBot.'

if (-not $NoLaunch) {
    Write-Host 'Starting first-run setup...'
    Start-Process -FilePath $VenvPythonW -ArgumentList ('"' + (Join-Path $InstallDir 'windows_app_locker.py') + '"') -WorkingDirectory $InstallDir
}
