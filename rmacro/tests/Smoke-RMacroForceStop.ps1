$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (Get-Process -Name RMacro -ErrorAction SilentlyContinue) { throw 'Close existing RMacro.exe processes before the force-stop test.' }
$directory = Join-Path ([IO.Path]::GetTempPath()) ('rmacro-force-test-' + [Guid]::NewGuid().ToString('N'))
$previousLocal = $env:LOCALAPPDATA
$process = $null
$cmd = $null
try {
    New-Item -ItemType Directory -Path $directory | Out-Null
    $env:LOCALAPPDATA = $directory
    $process = Start-Process -FilePath (Join-Path $root 'dist\RMacro.exe') -PassThru
    $opened = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        $process.Refresh()
        if ($process.HasExited) { throw "RMacro exited early: $($process.ExitCode)" }
        if ($process.MainWindowTitle -like 'RMacro*продукты') { $opened = $true; break }
    }
    if (-not $opened) { throw 'RMacro window did not open.' }
    $script = Join-Path $root 'rmacro\client\EMERGENCY-RMACRO.bat'
    $cmd = Start-Process -FilePath $env:ComSpec -ArgumentList ('/d /c "' + $script + '"') -WorkingDirectory $directory -PassThru
    if (-not $cmd.WaitForExit(16000)) { throw 'Emergency RMacro BAT did not finish.' }
    if (-not (Test-Path -LiteralPath (Join-Path $directory 'RMacro\Runtime\STOP.txt'))) { throw 'RMacro stop sentinel was not created.' }
    if (-not $process.WaitForExit(5000)) { throw 'Emergency BAT did not close RMacro.exe.' }
    Write-Output '::notice title=RMacro emergency BAT::PASS: STOP.txt was created and the test RMacro.exe was closed; GTA5 was not targeted.'
}
finally {
    $env:LOCALAPPDATA = $previousLocal
    if ($cmd) { $cmd.Refresh(); if (-not $cmd.HasExited) { Stop-Process -Id $cmd.Id -Force } }
    if ($process) { $process.Refresh(); if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force } }
    if (Test-Path -LiteralPath $directory) { Remove-Item -LiteralPath $directory -Recurse -Force -ErrorAction SilentlyContinue }
}
