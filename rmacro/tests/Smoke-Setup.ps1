$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$exe = Join-Path $root 'dist\EternalCore.exe'
$before = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash
& (Join-Path $root 'rmacro\client\SETUP-ETERNAL-CORE.bat') -CheckOnly -NoLaunch
if ($LASTEXITCODE -ne 0) { throw "Prerequisite check through BAT failed: $LASTEXITCODE" }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'rmacro\client\SETUP-ETERNAL-CORE.ps1') -CheckOnly -NoLaunch
if ($LASTEXITCODE -ne 0) { throw "Direct prerequisite check failed: $LASTEXITCODE" }
if ((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash -ne $before) { throw 'Prerequisite check changed the loader.' }
Write-Output '::notice title=Prerequisites::PASS: .NET detection and BAT forwarding; no packages installed on the CI machine. The interactive Microsoft download and UAC prompt were not exercised.'
