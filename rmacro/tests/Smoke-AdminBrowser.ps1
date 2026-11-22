$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$directory = Join-Path ([IO.Path]::GetTempPath()) ('rmacro-browser-test-' + [Guid]::NewGuid().ToString('N'))
$fixture = $null
$oldPort = $env:RMACRO_TEST_PORT
$oldNode = $env:NODE_PATH
$oldChrome = $env:RMACRO_CHROME_PATH
try {
    New-Item -ItemType Directory -Path $directory | Out-Null
    $fixtureSource = Join-Path $PSScriptRoot 'fixture_server.py'
    $db = Join-Path $directory 'fixture.db'; $ready = Join-Path $directory 'port.txt'
    $stdout = Join-Path $directory 'out.txt'; $stderr = Join-Path $directory 'err.txt'
    $argsForPython = @(('"' + $fixtureSource + '"'), '--db', ('"' + $db + '"'), '--ready', ('"' + $ready + '"'))
    $fixture = Start-Process -FilePath (Get-Command python).Source -ArgumentList $argsForPython -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-Path -LiteralPath $ready) { break }
        $fixture.Refresh(); if ($fixture.HasExited) { throw "Fixture stopped early: $(Get-Content $stderr -Raw -ErrorAction SilentlyContinue)" }
        Start-Sleep -Milliseconds 250
    }
    if (-not (Test-Path -LiteralPath $ready)) { throw 'Browser fixture did not start.' }
    $env:RMACRO_TEST_PORT = (Get-Content -LiteralPath $ready -Raw).Trim()
    $env:RMACRO_CHROME_PATH = Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'
    if (-not (Test-Path -LiteralPath $env:RMACRO_CHROME_PATH)) { throw 'Chrome not found on Windows runner.' }
    $nodeHome = Join-Path $directory 'node'
    & npm install --prefix $nodeHome --no-save --no-package-lock --no-audit --no-fund playwright-core@1.42.1
    if ($LASTEXITCODE -ne 0) { throw 'Could not install playwright-core.' }
    $env:NODE_PATH = Join-Path $nodeHome 'node_modules'
    & node (Join-Path $PSScriptRoot 'AdminBrowser.js')
    if ($LASTEXITCODE -ne 0) { throw "Admin browser smoke failed: $LASTEXITCODE" }
    Write-Output '::notice title=RMacro admin UI::PASS: Chrome exercised admin session restore after F5, network retry, revocation/logout, storage denial, and the admin CRUD and mobile UI.'
}
finally {
    $env:RMACRO_TEST_PORT = $oldPort; $env:NODE_PATH = $oldNode; $env:RMACRO_CHROME_PATH = $oldChrome
    if ($fixture) { $fixture.Refresh(); if (-not $fixture.HasExited) { Stop-Process -Id $fixture.Id -Force } }
    if (Test-Path -LiteralPath $directory) { Remove-Item -LiteralPath $directory -Recurse -Force -ErrorAction SilentlyContinue }
}
