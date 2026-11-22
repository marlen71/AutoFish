$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$source = Join-Path $root 'dist\EternalCore.exe'
$directory = Join-Path ([IO.Path]::GetTempPath()) ('eternal-updater-' + [Guid]::NewGuid().ToString('N'))
$oldLocal = $env:LOCALAPPDATA
$children = @()
$helper = $null
function Append-Footer([string]$path) {
    $stream = [IO.File]::Open($path, [IO.FileMode]::Append, [IO.FileAccess]::Write, [IO.FileShare]::None)
    $writer = [IO.BinaryWriter]::new($stream)
    try {
        $payload = [Text.Encoding]::UTF8.GetBytes('http://10.20.30.40:8765')
        $writer.Write($payload); $writer.Write([uint32]$payload.Length); $writer.Write([Text.Encoding]::ASCII.GetBytes('RMACRO_URL_V1'))
    }
    finally { $writer.Dispose() }
}
function Start-Loader([string]$path) {
    $p = Start-Process -FilePath $path -ArgumentList '--skip-update-once' -PassThru
    $null = $p.Handle
    for ($i = 0; $i -lt 80; $i++) {
        Start-Sleep -Milliseconds 250; $p.Refresh()
        if ($p.HasExited) { throw "Loader exited early ($($p.ExitCode))." }
        if ($p.MainWindowHandle -ne 0 -and $p.MainWindowTitle -like 'Eternal Core*продукты') { return $p }
    }
    throw 'Loader window did not open.'
}
function Find-Loader([string]$path) {
    foreach ($p in @(Get-Process -Name EternalCore -ErrorAction SilentlyContinue)) {
        try { if ($p.Path -eq $path) { return $p } } catch { }
    }
    return $null
}
function Stop-Loader([string]$path) {
    foreach ($p in @(Get-Process -Name EternalCore -ErrorAction SilentlyContinue)) {
        try {
            if ($p.Path -eq $path) {
                $null = $p.CloseMainWindow()
                if (-not $p.WaitForExit(5000)) { Stop-Process -Id $p.Id -Force }
            }
        } catch { }
    }
}
function Start-Helper([string]$target, $parent, [bool]$broken) {
    $nonce = [Guid]::NewGuid().ToString('N')
    $stage = Join-Path $directory ('.eternal-core-update-' + $nonce)
    New-Item -ItemType Directory -Path $stage | Out-Null
    $payload = Join-Path $stage 'payload.exe'; $helperPath = Join-Path $stage 'helper.exe'
    if ($broken) { [IO.File]::WriteAllBytes($payload, [Text.Encoding]::ASCII.GetBytes('MZ-not-a-valid-Windows-executable')) }
    else { Copy-Item -LiteralPath $source -Destination $payload }
    Append-Footer $payload
    if (-not $broken) { Append-Footer $payload } # distinguish the verified new file from the old one
    Copy-Item -LiteralPath $source -Destination $helperPath
    $hash = (Get-FileHash -LiteralPath $payload -Algorithm SHA256).Hash.ToLowerInvariant()
    $parent.Refresh(); $ticks = $parent.StartTime.ToUniversalTime().Ticks
    $parameters = @('--apply-update', $parent.Id, $ticks, ('"' + $target + '"'), $hash, $nonce)
    $p = Start-Process -FilePath $helperPath -ArgumentList $parameters -PassThru
    $null = $p.Handle
    return @{ Process = $p; Stage = $stage; Hash = $hash }
}
try {
    New-Item -ItemType Directory -Path $directory | Out-Null
    $env:LOCALAPPDATA = Join-Path $directory 'profile'
    $target = Join-Path $directory 'EternalCore.exe'
    Copy-Item -LiteralPath $source -Destination $target
    Append-Footer $target
    $oldHash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    $sentinel = Join-Path $directory 'server.py'; [IO.File]::WriteAllText($sentinel, 'must not be updated')
    $parent = Start-Loader $target; $children += $parent
    $operation = Start-Helper $target $parent $false; $helper = $operation.Process
    $null = $parent.CloseMainWindow()
    if (-not $parent.WaitForExit(10000)) { throw 'Original loader did not exit.' }
    if (-not $helper.WaitForExit(35000)) { throw 'Successful updater did not exit.' }
    $helper.Refresh()
    if ($helper.ExitCode -ne 0) { throw "Successful update helper failed: $($helper.ExitCode)" }
    if (-not (Test-Path -LiteralPath (Join-Path $operation.Stage 'ready'))) { throw 'New loader did not report a healthy window.' }
    if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $operation.Hash) { throw 'Installed loader hash mismatch.' }
    if ((Get-FileHash -LiteralPath (Join-Path $operation.Stage 'previous.exe') -Algorithm SHA256).Hash.ToLowerInvariant() -ne $oldHash) { throw 'Original configured loader backup is missing.' }
    if ([IO.File]::ReadAllText($sentinel) -ne 'must not be updated') { throw 'Updater changed the unrelated server file.' }
    Stop-Loader $target

    # An invalid but footer-preserving replacement must be rolled back when it
    # cannot start; the original loader is then reopened with one check skipped.
    $beforeFailure = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    $parent = Start-Loader $target; $children += $parent
    $operation = Start-Helper $target $parent $true; $helper = $operation.Process
    $null = $parent.CloseMainWindow()
    if (-not $parent.WaitForExit(10000)) { throw 'Original loader did not exit before rollback test.' }
    $restored = $false
    for ($i = 0; $i -lt 100; $i++) {
        Start-Sleep -Milliseconds 250
        if ((Test-Path -LiteralPath $target) -and (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -eq $beforeFailure) {
            $p = Find-Loader $target
            if ($p) { $restored = $true; break }
        }
    }
    if (-not $restored) {
        $helper.Refresh()
        $actual = if (Test-Path -LiteralPath $target) { (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() } else { 'missing' }
        $files = @(Get-ChildItem -LiteralPath $operation.Stage -File -ErrorAction SilentlyContinue | ForEach-Object { $_.Name + ':' + $_.Length }) -join ','
        $processes = @(Get-Process -Name EternalCore -ErrorAction SilentlyContinue | ForEach-Object { try { $_.Id.ToString() + ':' + $_.Path } catch { $_.Id.ToString() } }) -join ','
        $dialog = ''
        if ($helper.MainWindowHandle -ne 0) {
            try {
                Add-Type -AssemblyName UIAutomationClient; Add-Type -AssemblyName UIAutomationTypes
                $element = [System.Windows.Automation.AutomationElement]::FromHandle($helper.MainWindowHandle)
                $parts = $element.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
                $dialog = (($parts | ForEach-Object { $_.Current.Name } | Where-Object { $_ }) -join ' | ')
            } catch { $dialog = $_.Exception.Message }
        }
        throw "Failed update did not restore and reopen. Expected=$beforeFailure actual=$actual; helperExited=$($helper.HasExited) window=$($helper.MainWindowTitle); files=$files; loaders=$processes; dialog=$dialog"
    }
    # Dismiss the helper's warning without hiding its exit status.
    for ($i = 0; $i -lt 40; $i++) {
        $helper.Refresh(); if ($helper.HasExited) { break }
        if ($helper.MainWindowHandle -ne 0) { $null = $helper.CloseMainWindow(); break }
        Start-Sleep -Milliseconds 250
    }
    if (-not $helper.WaitForExit(10000)) { throw 'Rollback warning could not be dismissed.' }
    $helper.Refresh(); if ($helper.ExitCode -ne 1) { throw "Rollback helper returned $($helper.ExitCode), expected 1." }
    if ([IO.File]::ReadAllText($sentinel) -ne 'must not be updated') { throw 'Rollback touched the unrelated server file.' }
    Write-Output '::notice title=Updater integration::PASS: configured footer preserved, atomic loader replacement, healthy-window handshake, backup, broken-update rollback and unrelated server file unchanged. No GitHub network download exercised.'
}
catch {
    $detail = ($_ | Format-List * -Force | Out-String).Replace('%', '%25').Replace("`r", '%0D').Replace("`n", '%0A')
    if ($detail.Length -gt 5000) { $detail = $detail.Substring(0, 5000) }
    Write-Output "::error title=Updater integration::$detail"
    throw
}
finally {
    if ($target) { Stop-Loader $target }
    if ($helper) { $helper.Refresh(); if (-not $helper.HasExited) { Stop-Process -Id $helper.Id -Force -ErrorAction SilentlyContinue } }
    foreach ($p in $children) { $p.Refresh(); if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } }
    $env:LOCALAPPDATA = $oldLocal
    if (Test-Path -LiteralPath $directory) { Remove-Item -LiteralPath $directory -Recurse -Force -ErrorAction SilentlyContinue }
}
