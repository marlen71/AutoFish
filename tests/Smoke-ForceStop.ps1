$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (Get-Process -Name RMFish -ErrorAction SilentlyContinue) {
    throw 'Close existing RMFish.exe processes before running the force-stop test.'
}
$directory = Join-Path ([IO.Path]::GetTempPath()) ('rmfish-force-test-' + [Guid]::NewGuid().ToString('N'))
$process = $null
$cmd = $null
try {
    New-Item -ItemType Directory -Path $directory | Out-Null
    Copy-Item (Join-Path $root 'dist\RMFish.exe') (Join-Path $directory 'RMFish.exe')
    Copy-Item (Join-Path $root 'EMERGENCY-STOP.bat') (Join-Path $directory 'EMERGENCY-STOP.bat')
    $process = Start-Process -FilePath (Join-Path $directory 'RMFish.exe') -PassThru
    $opened = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        $process.Refresh()
        if ($process.HasExited) { throw "RMFish exited early: $($process.ExitCode)" }
        if ($process.MainWindowTitle -like 'RMFish*RMRP') { $opened = $true; break }
    }
    if (-not $opened) { throw 'RMFish window did not open for force-stop test.' }
    $script = Join-Path $directory 'EMERGENCY-STOP.bat'
    $cmd = Start-Process -FilePath $env:ComSpec -ArgumentList ('/d /c "' + $script + '"') -WorkingDirectory $directory -PassThru
    if (-not $cmd.WaitForExit(16000)) { throw 'Emergency BAT did not finish.' }
    if (-not (Test-Path -LiteralPath (Join-Path $directory 'STOP.txt'))) { throw 'Stop sentinel was not created.' }
    if (-not $process.WaitForExit(5000)) { throw 'Emergency BAT did not close RMFish.exe.' }
    Write-Output '::notice title=Emergency BAT::PASS: STOP.txt created and the test RMFish.exe was closed.'
}
catch {
    $message = $_.Exception.Message.Replace('%', '%25').Replace("`r", '%0D').Replace("`n", '%0A')
    Write-Output "::error title=Force-stop smoke test::$message"
    throw
}
finally {
    if ($cmd) {
        $cmd.Refresh()
        if (-not $cmd.HasExited) { Stop-Process -Id $cmd.Id -Force }
    }
    if ($process) {
        $process.Refresh()
        if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
    }
    if (Test-Path -LiteralPath $directory) { Remove-Item -LiteralPath $directory -Recurse -Force }
}
