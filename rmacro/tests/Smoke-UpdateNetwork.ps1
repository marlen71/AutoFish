param([string]$LegacySource = '')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$directory = Join-Path ([IO.Path]::GetTempPath()) ('eternal-network-' + [Guid]::NewGuid().ToString('N'))
Add-Type -LiteralPath (Join-Path $PSScriptRoot 'UpdateNetworkRunner.cs')
if ($LegacySource) {
    # Run in a separate PowerShell process so the published 1.3 assembly cannot
    # be unified with the already loaded 1.4 assembly of the same simple name.
    exit ([UpdateNetworkRunner]::Run($LegacySource, $directory, '1.3.0'))
}
$source = Join-Path $root 'dist\EternalCore.exe'
$result = [UpdateNetworkRunner]::Run($source, $directory)
if ($result -ne 0) { exit $result }

$legacyDirectory = Join-Path ([IO.Path]::GetTempPath()) ('eternal-legacy-' + [Guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Path $legacyDirectory | Out-Null
    $legacy = Join-Path $legacyDirectory 'EternalCore-1.3.0.exe'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/marlen71/AutoFish/releases/download/eternal-core-v1.3.0/EternalCore.exe' -OutFile $legacy
    if ((Get-FileHash -LiteralPath $legacy -Algorithm SHA256).Hash.ToLowerInvariant() -ne '4a9598c0f967dde6cf22a4c5f993f24769feb0ef37a24db066fff084781db121') {
        throw 'The published 1.3.0 loader does not match its pinned SHA-256.'
    }
    & (Join-Path $PSHOME 'powershell.exe') -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $PSCommandPath -LegacySource $legacy
    if ($LASTEXITCODE -ne 0) { throw "Legacy 1.3.0 live update check failed: $LASTEXITCODE" }
}
finally {
    if (Test-Path -LiteralPath $legacyDirectory) { Remove-Item -LiteralPath $legacyDirectory -Recurse -Force -ErrorAction SilentlyContinue }
}
