# SPDX-License-Identifier: AGPL-3.0-or-later
# Builds an MSIX package of RuEn Translator for the Microsoft Store (or for local testing).
#
# Local test build:
#   powershell -ExecutionPolicy Bypass -File build_msix.ps1
#   Then, with Windows Developer Mode on (Settings > System > For developers), install the layout:
#   Add-AppxPackage -Register build\msix\layout\AppxManifest.xml
#   (Remove it again with: Get-AppxPackage RuEnTranslator.LocalTest | Remove-AppxPackage)
#
# Store build - copy the three values from Partner Center > your app > Product identity:
#   powershell -ExecutionPolicy Bypass -File build_msix.ps1 `
#       -IdentityName "Aexonlab.RuEnTranslator" -Publisher "CN=XXXXXXXX-XXXX-..." -PublisherDisplayName "Aexonlab"
# Upload the resulting dist\RuEnTranslator-<version>-x64.msix in Partner Center; the Store signs it.
#
# -SkipBuild reuses the existing dist\RuEnTranslator folder build instead of running build.ps1.
param(
    [string]$IdentityName = "RuEnTranslator.LocalTest",
    [string]$Publisher = "CN=RuEnTranslatorLocalTest",
    [string]$PublisherDisplayName = "Aexonlab",
    [switch]$SkipBuild
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = ".\.venv\Scripts\python.exe"

# Version from rutrans/__init__.py (1.6.0 -> 1.6.0.0; the Store needs the last part to be 0)
$ver = (& $py -c "import rutrans; print(rutrans.__version__)").Trim()
$parts = @($ver.Split(".")) + @("0", "0", "0")
$msixVersion = ($parts[0..2] -join ".") + ".0"

# Windows SDK tools (MakeAppx, MakePri)
$sdk = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Directory |
    Where-Object { Test-Path (Join-Path $_.FullName "x64\makeappx.exe") } | Sort-Object Name -Descending | Select-Object -First 1
if (-not $sdk) { throw "Windows 10/11 SDK not found (needed for makeappx.exe / makepri.exe)." }
$tools = Join-Path $sdk.FullName "x64"

# 1. The app folder (build.ps1 output). Only the app itself goes into the package.
if (-not $SkipBuild) {
    powershell -ExecutionPolicy Bypass -File build.ps1
    if ($LASTEXITCODE) { throw "build.ps1 failed" }
}
$app = Join-Path $PSScriptRoot "dist\RuEnTranslator"
if (-not (Test-Path "$app\RuEnTranslator.exe")) { throw "No app build in $app - run build.ps1 first." }

$root = Join-Path $PSScriptRoot "build\msix"
$layout = Join-Path $root "layout"
if (Test-Path $root) { Remove-Item $root -Recurse -Force }
New-Item -ItemType Directory -Force $layout | Out-Null
Copy-Item "$app\RuEnTranslator.exe" $layout
Copy-Item "$app\_internal" $layout -Recurse

# 2. Tile and logo images
& $py packaging\make_store_assets.py "$layout\Assets"
if ($LASTEXITCODE) { throw "make_store_assets failed" }

# 3. Manifest
$manifest = (Get-Content packaging\AppxManifest.template.xml -Raw).
    Replace("{IDENTITY_NAME}", $IdentityName).Replace("{PUBLISHER}", [Security.SecurityElement]::Escape($Publisher)).
    Replace("{PUBLISHER_DISPLAY_NAME}", [Security.SecurityElement]::Escape($PublisherDisplayName)).
    Replace("{VERSION}", $msixVersion)
$localTest = $IdentityName -eq "RuEnTranslator.LocalTest"
[IO.File]::WriteAllText("$layout\AppxManifest.xml", $manifest, (New-Object Text.UTF8Encoding $false))

# 4. Resource index (lets Windows pick the right image scale / size)
& "$tools\makepri.exe" createconfig /cf "$root\priconfig.xml" /dq en-US /pv 10.0.0 /o | Out-Null
[xml]$pc = Get-Content "$root\priconfig.xml"
$pk = $pc.SelectSingleNode("//packaging")     # one resources.pri (no per-scale split files)
if ($pk) { [void]$pk.ParentNode.RemoveChild($pk) }
$pc.Save("$root\priconfig.xml")
& "$tools\makepri.exe" new /pr $layout /cf "$root\priconfig.xml" /mn "$layout\AppxManifest.xml" /of "$layout\resources.pri" /o | Out-Null
if ($LASTEXITCODE) { throw "makepri failed" }

# 5. Pack
New-Item -ItemType Directory -Force dist | Out-Null
$suffix = if ($localTest) { "-localtest" } else { "" }
$out = Join-Path $PSScriptRoot "dist\RuEnTranslator-$msixVersion-x64$suffix.msix"
& "$tools\makeappx.exe" pack /d $layout /p $out /o | Out-Null
if ($LASTEXITCODE) { throw "makeappx failed" }
"Built: $out ({0:N0} MB)  identity: $IdentityName, publisher: $Publisher" -f ((Get-Item $out).Length / 1MB)
