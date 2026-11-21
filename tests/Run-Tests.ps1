$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$sources = @(
    (Join-Path $root 'src\Vision.cs'),
    (Join-Path $root 'src\StateMachine.cs'),
    (Join-Path $root 'src\Engine.cs'),
    (Join-Path $root 'src\Safety.cs'),
    (Join-Path $root 'tests\TestRunner.cs')
)
Add-Type -AssemblyName System.IO.Compression
$references = @(
    [System.Diagnostics.Process].Assembly.Location,
    [System.Linq.Enumerable].Assembly.Location,
    [System.IO.Compression.GZipStream].Assembly.Location
) | Select-Object -Unique
Add-Type -LiteralPath $sources -ReferencedAssemblies $references
$exitCode = [TestRunner]::Main([string[]]@((Join-Path $PSScriptRoot 'fixtures')))
exit $exitCode
