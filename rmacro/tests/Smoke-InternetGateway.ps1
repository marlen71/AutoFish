$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$directory = Join-Path ([IO.Path]::GetTempPath()) ('eternal-https-ci-' + [Guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Path $directory | Out-Null
    $archiveName = 'caddy_2.11.9_windows_amd64.zip'
    $archive = Join-Path $directory $archiveName
    & gh release download v2.11.9 --repo caddyserver/caddy --pattern $archiveName --dir $directory
    if ($LASTEXITCODE -ne 0) { throw 'Could not download the official Caddy test archive.' }
    $expected = 'ad93112d335ee687100c4c9f11bced16ca590377976b7fe7883882b9e797e472'
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
        throw 'The official Caddy test archive did not match the pinned SHA-256.'
    }
    Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $directory 'caddy')
    $caddy = Join-Path $directory 'caddy\caddy.exe'
    if (-not (Test-Path -LiteralPath $caddy -PathType Leaf)) { throw 'Official Caddy executable not found.' }

    # Exercise the actual owner setup, the BAT Python wrapper, and the built
    # PE with a cached, pinned archive. Existing database/static files must
    # remain untouched; no real public server or ACME request is started.
    $stage = Join-Path $directory 'installed-server'
    $state = Join-Path $stage 'data\internet-gateway'
    New-Item -ItemType Directory -Path $state -Force | Out-Null
    foreach ($name in @('server.py','internet_gateway.py','RUN-PYTHON.bat')) {
        Copy-Item -LiteralPath (Join-Path $root "rmacro\server\$name") -Destination (Join-Path $stage $name)
    }
    Copy-Item -LiteralPath $archive -Destination (Join-Path $state $archiveName)
    $db = Join-Path $stage 'data\rmacro.db'
    [IO.File]::WriteAllText($db, 'existing database sentinel')
    $source = Join-Path $root 'dist\EternalCore.exe'
    $sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
    $oldUtf8 = $env:PYTHONUTF8; $env:PYTHONUTF8 = '1'
    try {
        $ErrorActionPreference = 'Continue'
        $setupOutput = @('8.8.8.8', $source) | & (Join-Path $stage 'RUN-PYTHON.bat') internet-setup 2>&1
        $setupExit = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        foreach ($line in $setupOutput) { Write-Host $line }
        if ($setupExit -ne 0) { throw "Internet setup failed: $setupExit" }
    }
    finally { $env:PYTHONUTF8 = $oldUtf8; $ErrorActionPreference = 'Stop' }
    if ([IO.File]::ReadAllText($db) -ne 'existing database sentinel') { throw 'Internet setup changed the existing database.' }
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $sourceHash) { throw 'Internet setup changed the original loader.' }
    $configured = @(Get-ChildItem (Join-Path $stage 'configured-client') -Filter 'EternalCore.exe' -File -Recurse)
    if ($configured.Count -ne 1 -or -not (Test-Path (Join-Path $state 'settings.json'))) { throw 'Internet setup did not create the configured loader and settings.' }
    $openssl = (Get-Command openssl.exe -ErrorAction SilentlyContinue).Source
    if (-not $openssl) { $openssl = Join-Path $env:ProgramFiles 'Git\usr\bin\openssl.exe' }
    if (-not (Test-Path -LiteralPath $openssl -PathType Leaf)) { throw 'OpenSSL is required for the local TLS test.' }
    Add-Type -AssemblyName System.Web.Extensions
    Add-Type -AssemblyName System.Security
    $csc = Join-Path ([System.Runtime.InteropServices.RuntimeEnvironment]::GetRuntimeDirectory()) 'csc.exe'
    $runner = Join-Path $directory 'InternetClientRunner.exe'
    $compile = @('/nologo', '/noconfig', '/target:exe', '/platform:anycpu', '/utf8output', '/warnaserror+',
        '/main:InternetClientRunner', "/out:$runner", "/reference:$([System.Web.Script.Serialization.JavaScriptSerializer].Assembly.Location)",
        "/reference:$([System.Security.Cryptography.ProtectedData].Assembly.Location)",
        (Join-Path $root 'rmacro\client\ClientCore.cs'), (Join-Path $root 'rmacro\tests\InternetClientRunner.cs'))
    & $csc @compile
    if ($LASTEXITCODE -ne 0) { throw 'Windows HTTPS client test compilation failed.' }
    # The fixture adds a self-signed root only to this CI user's store, tests
    # the unmodified client, and removes that exact root in a finally block.
    $ErrorActionPreference = 'Continue'
    $output = & python (Join-Path $PSScriptRoot 'Smoke-InternetGateway.py') --caddy $caddy --openssl $openssl --dotnet-runner $runner --loader (Join-Path $root 'dist\EternalCore.exe') 2>&1
    $testExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    foreach ($line in $output) { Write-Host $line }
    if ($testExit -ne 0) { throw "HTTPS gateway integration failed: $testExit" }
    Write-Output '::notice title=Internet gateway::PASS: trusted/untrusted IP TLS in the Windows client, local fixture login, admin isolation and spoof-resistant rate limiting; real ACME and external router not tested.'
}
catch {
    $detail = ($_ | Format-List * -Force | Out-String).Replace('%', '%25').Replace("`r", '%0D').Replace("`n", '%0A')
    if ($detail.Length -gt 5000) { $detail = $detail.Substring(0, 5000) }
    Write-Output "::error title=HTTPS gateway integration::$detail"
    throw
}
finally {
    if (Test-Path -LiteralPath $directory) { Remove-Item -LiteralPath $directory -Recurse -Force -ErrorAction SilentlyContinue }
}
