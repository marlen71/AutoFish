$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (Get-Process -Name EternalCore -ErrorAction SilentlyContinue) { throw 'Close existing EternalCore.exe processes before the force-stop test.' }
$directory = Join-Path ([IO.Path]::GetTempPath()) ('rmacro-force-test-' + [Guid]::NewGuid().ToString('N'))
$previousLocal = $env:LOCALAPPDATA
$process = $null
$cmd = $null
try {
    New-Item -ItemType Directory -Path $directory | Out-Null
    $env:LOCALAPPDATA = $directory
    $process = Start-Process -FilePath (Join-Path $root 'dist\EternalCore.exe') -PassThru
    $opened = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        $process.Refresh()
        if ($process.HasExited) { throw "Eternal Core exited early: $($process.ExitCode)" }
        if ($process.MainWindowTitle -like 'Eternal Core*продукты') { $opened = $true; break }
    }
    if (-not $opened) { throw 'Eternal Core window did not open.' }
    $script = Join-Path $root 'rmacro\client\EMERGENCY-ETERNAL-CORE.bat'
    $cmd = Start-Process -FilePath $env:ComSpec -ArgumentList ('/d /c "' + $script + '"') -WorkingDirectory $directory -PassThru
    if (-not $cmd.WaitForExit(16000)) { throw 'Emergency Eternal Core BAT did not finish.' }
    if (-not (Test-Path -LiteralPath (Join-Path $directory 'RMacro\Runtime\STOP.txt'))) { throw 'RMacro stop sentinel was not created.' }
    if (-not $process.WaitForExit(5000)) { throw 'Emergency BAT did not close EternalCore.exe.' }
    Write-Output '::notice title=RMacro emergency BAT::PASS: STOP.txt was created and the test EternalCore.exe was closed; GTA5 was not targeted.'
}
finally {
    $env:LOCALAPPDATA = $previousLocal
    if ($cmd) { $cmd.Refresh(); if (-not $cmd.HasExited) { Stop-Process -Id $cmd.Id -Force } }
    if ($process) { $process.Refresh(); if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force } }
    if (Test-Path -LiteralPath $directory) { Remove-Item -LiteralPath $directory -Recurse -Force -ErrorAction SilentlyContinue }
}
