$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$source = Join-Path $root 'dist\EternalCore.exe'
$directory = Join-Path ([IO.Path]::GetTempPath()) ('eternal-network-' + [Guid]::NewGuid().ToString('N'))
Add-Type -LiteralPath (Join-Path $PSScriptRoot 'UpdateNetworkRunner.cs')
exit ([UpdateNetworkRunner]::Run($source, $directory))
