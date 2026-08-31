[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Version = (Get-Content -LiteralPath (Join-Path $Root 'VERSION') -Raw).Trim()
$Dist = Join-Path $Root 'dist'
$Stage = Join-Path $env:TEMP ("windows-app-locker-release-" + [Guid]::NewGuid().ToString('N'))
$PackageDir = Join-Path $Stage ("windows-app-locker-v" + $Version)
$Zip = Join-Path $Dist ("windows-app-locker-v" + $Version + '.zip')

New-Item -ItemType Directory -Path $Dist -Force | Out-Null
New-Item -ItemType Directory -Path $PackageDir -Force | Out-Null

$Include = @(
    'windows_app_locker.py',
    'requirements.txt',
    'install.ps1',
    'uninstall.ps1',
    'VERSION',
    'README.md',
    'README.en.md',
    'CHANGELOG.md',
    'SECURITY.md',
    'CONTRIBUTING.md',
    'LICENSE',
    'RELEASE_NOTES_v2.0.0.md',
    'docs'
)

foreach ($item in $Include) {
    $source = Join-Path $Root $item
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination $PackageDir -Recurse -Force
    }
}

if (Test-Path -LiteralPath $Zip) {
    Remove-Item -LiteralPath $Zip -Force
}

Compress-Archive -Path $PackageDir -DestinationPath $Zip -CompressionLevel Optimal
Remove-Item -LiteralPath $Stage -Recurse -Force

Write-Host "Release package created: $Zip" -ForegroundColor Green
