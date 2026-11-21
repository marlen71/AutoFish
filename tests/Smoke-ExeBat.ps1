$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (Get-Process -Name RMFish -ErrorAction SilentlyContinue) {
    throw 'Close existing RMFish.exe processes before running the BAT launcher test.'
}
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ExeBatWindow {
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr window);
}
'@
$directory = Join-Path ([IO.Path]::GetTempPath()) ('rmfish-exebat-test-' + [Guid]::NewGuid().ToString('N'))
$process = $null
$cmd = $null
try {
    New-Item -ItemType Directory -Path $directory | Out-Null
    $exe = Join-Path $directory 'RMFish.exe'
    $bat = Join-Path $directory 'RMFish.bat'
    Copy-Item (Join-Path $root 'dist\RMFish.exe') $exe
    Copy-Item (Join-Path $root 'RMFish.bat') $bat
    $cmd = Start-Process -FilePath $env:ComSpec -ArgumentList ('/d /c "' + $bat + '"') -WorkingDirectory $directory -PassThru
    if (-not $cmd.WaitForExit(10000) -or $cmd.ExitCode -ne 0) { throw 'The EXE launcher BAT did not return successfully.' }
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Milliseconds 250
        if (-not $process) {
            $child = Get-CimInstance Win32_Process -Filter "Name='RMFish.exe'" |
                Where-Object { $_.ExecutablePath -eq $exe } | Select-Object -First 1
            if ($child) { $process = [Diagnostics.Process]::GetProcessById($child.ProcessId) }
        }
        if ($process) {
            $process.Refresh()
            if ($process.HasExited) { throw 'The BAT-launched EXE exited early.' }
            if ($process.MainWindowHandle -ne 0 -and $process.MainWindowTitle -like 'RMFish*RMRP' -and
                [ExeBatWindow]::IsWindowVisible($process.MainWindowHandle) -and
                -not [ExeBatWindow]::IsIconic($process.MainWindowHandle)) { break }
        }
    }
    if (-not $process -or $process.MainWindowHandle -eq 0 -or
        $process.MainWindowTitle -notlike 'RMFish*RMRP' -or
        -not [ExeBatWindow]::IsWindowVisible($process.MainWindowHandle) -or
        [ExeBatWindow]::IsIconic($process.MainWindowHandle)) {
        throw 'The BAT did not open a visible, non-minimized EXE menu.'
    }
    Write-Output '::notice title=EXE launcher BAT::PASS: BAT opened the visible RMFish.exe menu.'
}
catch {
    $message = $_.Exception.Message.Replace('%', '%25').Replace("`r", '%0D').Replace("`n", '%0A')
    Write-Output "::error title=EXE launcher BAT::$message"
    throw
}
finally {
    if ($cmd) {
        $cmd.Refresh()
        if (-not $cmd.HasExited) { Stop-Process -Id $cmd.Id -Force }
    }
    if ($process) {
        $process.Refresh()
        if (-not $process.HasExited) {
            $null = $process.CloseMainWindow()
            if (-not $process.WaitForExit(5000)) { Stop-Process -Id $process.Id -Force }
        }
    }
    if (Test-Path -LiteralPath $directory) { Remove-Item -LiteralPath $directory -Recurse -Force }
}
