$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$sources = @(
    (Join-Path $root 'rmacro\client\UpdatePolicy.cs'),
    (Join-Path $root 'rmacro\tests\UpdatePolicyRunner.cs')
)
$references = @([System.Diagnostics.Process].Assembly.Location, [System.Linq.Enumerable].Assembly.Location) | Select-Object -Unique
Add-Type -LiteralPath $sources -ReferencedAssemblies $references
exit ([UpdatePolicyRunner]::Main())
