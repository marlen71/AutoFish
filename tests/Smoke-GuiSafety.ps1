$ErrorActionPreference = 'Stop'
if ($env:RMFISH_TEST_NATIVE_KEYS -ne '1') {
    throw 'This test injects system-wide keys. Run it only in an isolated Windows test session with RMFISH_TEST_NATIVE_KEYS=1.'
}
$root = Split-Path -Parent $PSScriptRoot
$directory = Join-Path ([IO.Path]::GetTempPath()) ('rmfish-gui-test-' + [Guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Path $directory | Out-Null
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $sources = @(
        (Join-Path $root 'src\Vision.cs'),
        (Join-Path $root 'src\StateMachine.cs'),
        (Join-Path $root 'src\Engine.cs'),
        (Join-Path $root 'src\Safety.cs'),
        (Join-Path $root 'src\WindowsGame.cs'),
        (Join-Path $root 'src\MainForm.cs'),
        (Join-Path $root 'tests\GuiSafetyRunner.cs')
    )
    $references = @(
        [System.Diagnostics.Process].Assembly.Location,
        [System.Linq.Enumerable].Assembly.Location,
        [System.Drawing.Color].Assembly.Location,
        [System.Windows.Forms.Form].Assembly.Location
    ) | Select-Object -Unique
    Add-Type -LiteralPath $sources -ReferencedAssemblies $references
    $exitCode = [GuiSafetyRunner]::Run($directory)
    if ($exitCode -ne 0) { throw "GUI safety test failed with exit code $exitCode." }
}
catch {
    $detail = ($_ | Format-List * -Force | Out-String).Replace('%', '%25').Replace("`r", '%0D').Replace("`n", '%0A')
    if ($detail.Length -gt 5000) { $detail = $detail.Substring(0, 5000) }
    Write-Output "::error title=GUI safety harness::$detail"
    throw
}
finally {
    if (Test-Path -LiteralPath $directory) { Remove-Item -LiteralPath $directory -Recurse -Force }
}
