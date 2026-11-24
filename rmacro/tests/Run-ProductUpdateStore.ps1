$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$directory = Join-Path ([IO.Path]::GetTempPath()) ('product-store-test-' + [Guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Path $directory | Out-Null
    $csc = Join-Path ([System.Runtime.InteropServices.RuntimeEnvironment]::GetRuntimeDirectory()) 'csc.exe'
    $fixture = Join-Path $directory 'RMFishProduct.dll'
    & $csc /nologo /noconfig /target:library "/out:$fixture" (Join-Path $PSScriptRoot 'ProductModuleFixture.cs')
    if ($LASTEXITCODE -ne 0) { throw 'Could not compile the harmless product module fixture.' }
    $sources = @(
        (Join-Path $root 'rmacro\client\UpdatePolicy.cs'),
        (Join-Path $root 'rmacro\client\ProductUpdateStore.cs'),
        (Join-Path $PSScriptRoot 'ProductUpdateStoreRunner.cs')
    )
    $references = @([System.Diagnostics.Process].Assembly.Location, [System.Linq.Enumerable].Assembly.Location) | Select-Object -Unique
    Add-Type -LiteralPath $sources -ReferencedAssemblies $references
    $result = [ProductUpdateStoreRunner]::Main([string[]]@($fixture))
    if ($result -ne 0) { throw "Product update store tests failed: $result" }
}
finally { if (Test-Path $directory) { Remove-Item -LiteralPath $directory -Recurse -Force -ErrorAction SilentlyContinue } }
