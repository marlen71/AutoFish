$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$directory = Join-Path ([IO.Path]::GetTempPath()) ('rmfish-assets-test-' + [Guid]::NewGuid().ToString('N'))
$form = $null
$icon = $null
$iconBitmap = $null
$stream = $null
$sha = $null
try {
    New-Item -ItemType Directory -Path $directory | Out-Null
    $exe = Join-Path $directory 'RMFish.exe'
    Copy-Item (Join-Path $root 'dist\RMFish.exe') $exe
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $assembly = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes($exe))
    $stream = $assembly.GetManifestResourceStream('RMFish.BrandLogo.png')
    if (-not $stream) { throw 'The standalone EXE does not contain the logo resource.' }
    $sha = [Security.Cryptography.SHA256]::Create()
    $actual = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLowerInvariant()
    $expected = (Get-FileHash (Join-Path $root 'assets\rmfish-logo.png') -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) { throw 'The embedded logo differs from the source artwork.' }
    $stream.Dispose(); $stream = $null
    $icon = [Drawing.Icon]::ExtractAssociatedIcon($exe)
    if (-not $icon -or $icon.Width -lt 16 -or $icon.Height -lt 16) { throw 'Could not extract the EXE icon.' }
    $iconBitmap = $icon.ToBitmap()
    $mint = $false; $white = $false
    for ($y = 0; $y -lt $iconBitmap.Height; $y++) {
        for ($x = 0; $x -lt $iconBitmap.Width; $x++) {
            $color = $iconBitmap.GetPixel($x, $y)
            if ($color.A -gt 128 -and $color.G -gt 140 -and $color.G -gt ($color.R * 1.4) -and $color.B -gt 80) { $mint = $true }
            if ($color.A -gt 128 -and $color.R -gt 200 -and $color.G -gt 200 -and $color.B -gt 200) { $white = $true }
        }
    }
    if (-not $mint -or -not $white) { throw 'The EXE icon does not contain the supplied RMFish artwork.' }
    if (Test-Path (Join-Path $directory 'assets')) { throw 'The isolated EXE test unexpectedly has external assets.' }
    $type = $assembly.GetType('RMFish.MainForm', $true)
    $form = [Activator]::CreateInstance($type, [object[]]@([string]$directory))
    $logo = @($form.Controls.Find('brandLogo', $true))
    if ($logo.Count -ne 1 -or -not $logo[0].Image -or $logo[0].Image.Width -lt 100) {
        throw 'The EXE menu failed to load its embedded logo without external files.'
    }
    Write-Output '::notice title=Standalone artwork::PASS: embedded logo matches the source, loads without an assets folder, and the EXE icon can be extracted.'
}
catch {
    $message = $_.Exception.Message.Replace('%', '%25').Replace("`r", '%0D').Replace("`n", '%0A')
    Write-Output "::error title=Standalone artwork::$message"
    throw
}
finally {
    if ($form) { $form.Dispose() }
    if ($iconBitmap) { $iconBitmap.Dispose() }
    if ($icon) { $icon.Dispose() }
    if ($stream) { $stream.Dispose() }
    if ($sha) { $sha.Dispose() }
    if (Test-Path -LiteralPath $directory) { Remove-Item -LiteralPath $directory -Recurse -Force }
}
