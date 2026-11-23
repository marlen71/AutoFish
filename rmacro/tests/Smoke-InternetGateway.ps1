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
        $setupOutput = & python (Join-Path $PSScriptRoot 'Smoke-OwnerSetup.py') --stage $stage --loader $source 2>&1
        $setupExit = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        foreach ($line in $setupOutput) { Write-Host $line }
        if ($setupExit -ne 0) { throw "Internet setup failed: $setupExit. Output: $($setupOutput | Out-String)" }
    }
    finally { $env:PYTHONUTF8 = $oldUtf8; $ErrorActionPreference = 'Stop' }
    if ([IO.File]::ReadAllText($db) -ne 'existing database sentinel') { throw 'Internet setup changed the existing database.' }
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $sourceHash) { throw 'Internet setup changed the original loader.' }
    $configured = @(Get-ChildItem (Join-Path $stage 'configured-client') -Filter 'EternalCore.exe' -File -Recurse)
    if ($configured.Count -ne 1 -or -not (Test-Path (Join-Path $state 'settings.json'))) { throw 'Internet setup did not create the configured loader and settings.' }
    $openssl = (Get-Command openssl.exe -ErrorAction SilentlyContinue).Source
    if (-not $openssl) { $openssl = Join-Path $env:ProgramFiles 'Git\usr\bin\openssl.exe' }
    if (-not (Test-Path -LiteralPath $openssl -PathType Leaf)) { throw 'OpenSSL is required for the local TLS test.' }
    # The owner setup creates private keys under a restricted ACL and must not
    # install its root into either Windows root certificate store.
    $caDirectory = Join-Path $state 'caddy-data\caddy\pki\authorities\local'
    $rootPath = Join-Path $caDirectory 'root.crt'
    $keyPath = Join-Path $caDirectory 'root.key'
    if (-not (Test-Path $rootPath) -or -not (Test-Path $keyPath)) { throw 'Owner setup did not create its private CA.' }
    $pem = [IO.File]::ReadAllText($rootPath).Replace('-----BEGIN CERTIFICATE-----', '').Replace('-----END CERTIFICATE-----', '')
    $publicRoot = [Security.Cryptography.X509Certificates.X509Certificate2]::new([Convert]::FromBase64String($pem))
    foreach ($store in @('Cert:\CurrentUser\Root', 'Cert:\LocalMachine\Root')) {
        if (@(Get-ChildItem $store | Where-Object { $_.Thumbprint -eq $publicRoot.Thumbprint }).Count -ne 0) { throw "Private root was installed into $store." }
    }
    $allowed = @([Security.Principal.WindowsIdentity]::GetCurrent().User.Value, 'S-1-5-18', 'S-1-5-32-544')
    foreach ($path in @((Join-Path $state 'caddy-data'), $keyPath)) {
        $acl = Get-Acl -LiteralPath $path
        if (-not $acl.AreAccessRulesProtected) { throw "Private data ACL is inherited: $path" }
        foreach ($rule in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
            if ($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and $allowed -notcontains $rule.IdentityReference.Value) {
                throw "Unexpected access to private data: $($rule.IdentityReference.Value)"
            }
        }
    }
    Add-Type -AssemblyName System.Web.Extensions
    Add-Type -AssemblyName System.Security
    Add-Type -AssemblyName System.Windows.Forms
    $csc = Join-Path ([System.Runtime.InteropServices.RuntimeEnvironment]::GetRuntimeDirectory()) 'csc.exe'
    $runner = Join-Path $directory 'InternetClientRunner.exe'
    $compile = @('/nologo', '/noconfig', '/target:exe', '/platform:anycpu', '/utf8output', '/warnaserror+',
        '/main:InternetClientRunner', "/out:$runner", "/reference:$([System.Diagnostics.Process].Assembly.Location)",
        "/reference:$([System.Linq.Enumerable].Assembly.Location)", "/reference:$([System.Web.Script.Serialization.JavaScriptSerializer].Assembly.Location)",
        "/reference:$([System.Security.Cryptography.ProtectedData].Assembly.Location)",
        "/reference:$([System.Windows.Forms.Form].Assembly.Location)",
        (Join-Path $root 'rmacro\client\ClientCore.cs'), (Join-Path $root 'rmacro\client\UpdatePolicy.cs'),
        (Join-Path $root 'rmacro\client\Updater.cs'), (Join-Path $root 'rmacro\tests\InternetClientRunner.cs'))
    $ErrorActionPreference = 'Continue'
    $compilerOutput = & $csc @compile 2>&1
    $compilerExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    foreach ($line in $compilerOutput) { Write-Host $line }
    if ($compilerExit -ne 0) { throw "Windows HTTPS client test compilation failed: $($compilerOutput | Out-String)" }
    # Exercise independent private-CA fixtures without touching Windows trust.
    # Each tests a valid chain, wrong CA, wrong IP, expired leaf, wrong EKU,
    # updater pin preservation, admin isolation, and repeated connections.
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        Write-Host "HTTPS gateway fixture $attempt of 5"
        $ErrorActionPreference = 'Continue'
        $output = & python (Join-Path $PSScriptRoot 'Smoke-InternetGateway.py') --caddy $caddy --openssl $openssl --dotnet-runner $runner --loader (Join-Path $root 'dist\EternalCore.exe') 2>&1
        $testExit = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        foreach ($line in $output) { Write-Host $line }
        if ($testExit -ne 0) { throw "HTTPS gateway fixture $attempt failed: $testExit. Output: $($output | Out-String)" }
    }
    Write-Output '::notice title=Internet gateway::PASS: 5 private CA fixtures; Windows login, wrong root/IP/expiry/EKU rejection, update preservation, no Windows root installation, local admin isolation and rate limiting. External router not tested.'
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
