$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$source = Join-Path $root 'dist\EternalCore.exe'
$directory = Join-Path ([IO.Path]::GetTempPath()) ('eternal-network-' + [Guid]::NewGuid().ToString('N'))
$staged = $null
$updater = $null
try {
    New-Item -ItemType Directory -Path $directory | Out-Null
    $target = Join-Path $directory 'EternalCore.exe'
    Copy-Item -LiteralPath $source -Destination $target

    # Invoke the same updater code compiled into the real Windows EXE. Asking
    # from 0.0.0 selects a published stable release without installing it.
    $assembly = [Reflection.Assembly]::LoadFrom($source)
    $updater = $assembly.GetType('RMacro.LoaderUpdater', $true)
    $settings = $assembly.GetType('RMacro.ServerSettings', $true)
    $flags = [Reflection.BindingFlags]::Public -bor [Reflection.BindingFlags]::NonPublic -bor [Reflection.BindingFlags]::Static
    $find = $updater.GetMethod('FindNewer', $flags)
    $prepare = $updater.GetMethod('Prepare', $flags)
    $append = $settings.GetMethod('AppendToExecutable', $flags)
    $read = $settings.GetMethod('ReadFromExecutable', $flags)
    $customAddress = 'http://10.20.30.40:8765'
    $null = $append.Invoke($null, [object[]]@($target, $customAddress))
    $oldHash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
    $release = $find.Invoke($null, [object[]]@([Version]::new(0, 0, 0)))
    if (-not $release) { throw 'No usable stable Eternal Core release with a SHA-256 digest was selected.' }
    $tag = $release.GetType().GetField('Tag').GetValue($release)
    $staged = $prepare.Invoke($null, [object[]]@($release, $target))
    $stage = $staged.GetType().GetField('Directory').GetValue($staged)
    $payload = Join-Path $stage 'payload.exe'
    $helper = Join-Path $stage 'helper.exe'
    if (-not (Test-Path -LiteralPath $payload -PathType Leaf) -or -not (Test-Path -LiteralPath $helper -PathType Leaf)) { throw 'Downloaded update was not staged.' }
    if (($read.Invoke($null, [object[]]@($payload))) -ne $customAddress) { throw 'Downloaded EXE did not retain the configured endpoint.' }
    if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $oldHash) { throw 'Preparing the update modified the installed EXE.' }
    if ((Get-FileHash -LiteralPath $payload -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $helper -Algorithm SHA256).Hash) { throw 'Helper does not match staged EXE.' }
    Write-Output "::notice title=Live GitHub updater::PASS: selected $tag, downloaded and verified its GitHub size/SHA-256 and PE version, staged without installation, and preserved the test endpoint."
}
catch {
    $message = $_.Exception.GetBaseException().ToString().Replace('%', '%25').Replace("`r", '%0D').Replace("`n", '%0A')
    if ($message.Length -gt 5000) { $message = $message.Substring(0, 5000) }
    Write-Output "::error title=Live GitHub updater::$message"
    throw
}
finally {
    if ($staged -and $updater) {
        try {
            $flags = [Reflection.BindingFlags]::Public -bor [Reflection.BindingFlags]::NonPublic -bor [Reflection.BindingFlags]::Static
            $null = $updater.GetMethod('Discard', $flags).Invoke($null, [object[]]@($staged))
        } catch { }
    }
    if (Test-Path -LiteralPath $directory) { Remove-Item -LiteralPath $directory -Recurse -Force -ErrorAction SilentlyContinue }
}
