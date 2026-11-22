$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$pythonCommand = Get-Command python -ErrorAction Stop
$python = $pythonCommand.Source
$directory = Join-Path ([IO.Path]::GetTempPath()) ('rmacro-test-' + [Guid]::NewGuid().ToString('N'))
$fixture = $null
$guiProcess = $null
$configuredProcess = $null
$oldPort = $env:RMACRO_TEST_PORT
$oldConfigured = $env:RMACRO_CONFIGURED_EXE
$oldLocal = $env:LOCALAPPDATA
try {
    New-Item -ItemType Directory -Path $directory | Out-Null
    $db = Join-Path $directory 'fixture.db'
    $ready = Join-Path $directory 'port.txt'
    $fixtureSource = Join-Path $PSScriptRoot 'fixture_server.py'
    $stdout = Join-Path $directory 'fixture-out.txt'
    $stderr = Join-Path $directory 'fixture-err.txt'
    $argsForPython = @(('"' + $fixtureSource + '"'), '--db', ('"' + $db + '"'), '--ready', ('"' + $ready + '"'))
    $fixture = Start-Process -FilePath $python -ArgumentList $argsForPython -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-Path -LiteralPath $ready) { break }
        $fixture.Refresh()
        if ($fixture.HasExited) { throw "Fixture server stopped early: $(Get-Content $stderr -Raw -ErrorAction SilentlyContinue)" }
        Start-Sleep -Milliseconds 250
    }
    if (-not (Test-Path -LiteralPath $ready)) { throw 'Fixture server did not start.' }
    $env:RMACRO_TEST_PORT = (Get-Content -LiteralPath $ready -Raw).Trim()
    $configured = Join-Path $directory 'configured\RMacro.exe'
    $ErrorActionPreference = 'Continue'
    $configOutput = & $python (Join-Path $root 'rmacro\server\server.py') configure-client --source (Join-Path $root 'dist\RMacro.exe') --output $configured --url "http://127.0.0.1:$env:RMACRO_TEST_PORT" 2>&1
    $configExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    foreach ($line in $configOutput) { Write-Host $line }
    if ($configExit -ne 0 -or -not (Test-Path -LiteralPath $configured)) {
        throw "Failed to configure the released loader EXE (exit $configExit): $($configOutput | Out-String)"
    }
    $env:RMACRO_CONFIGURED_EXE = $configured
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    Add-Type -AssemblyName System.Web.Extensions
    Add-Type -AssemblyName System.Security
    $csc = Join-Path ([System.Runtime.InteropServices.RuntimeEnvironment]::GetRuntimeDirectory()) 'csc.exe'
    $testExe = Join-Path $directory 'RMacroTests.exe'
    $sources = @(
        'src\Vision.cs', 'src\StateMachine.cs', 'src\Engine.cs', 'src\Safety.cs',
        'src\WindowsGame.cs', 'src\UiComponents.cs', 'src\ChromeControls.cs', 'src\MainForm.cs',
        'rmacro\client\ClientCore.cs', 'rmacro\client\ClientUi.cs', 'rmacro\tests\RMacroTestRunner.cs'
    ) | ForEach-Object { Join-Path $root $_ }
    $references = @(
        [System.Diagnostics.Process].Assembly.Location, [System.Linq.Enumerable].Assembly.Location,
        [System.Drawing.Color].Assembly.Location, [System.Windows.Forms.Form].Assembly.Location,
        [System.Web.Script.Serialization.JavaScriptSerializer].Assembly.Location,
        [System.Security.Cryptography.ProtectedData].Assembly.Location
    ) | Select-Object -Unique
    $compile = @('/nologo', '/noconfig', '/target:exe', '/platform:anycpu', '/utf8output', '/warnaserror+',
        '/main:RMacroTestRunner', "/out:$testExe",
        "/win32icon:$(Join-Path $root 'assets\rmfish.ico')",
        "/resource:$(Join-Path $root 'assets\rmfish-logo.png'),RMFish.BrandLogo.png",
        "/resource:$(Join-Path $root 'assets\rmfish-icon-original.png'),RMacro.FishIcon.png",
        "/resource:$(Join-Path $root 'assets\rmacro-city.png'),RMacro.City.png")
    foreach ($reference in $references) { $compile += "/reference:$reference" }
    $compile += $sources
    & $csc @compile
    if ($LASTEXITCODE -ne 0) { throw "GUI test compilation failed: $LASTEXITCODE" }
    $guiOut = Join-Path $directory 'gui-out.txt'
    $guiErr = Join-Path $directory 'gui-err.txt'
    $guiProcess = Start-Process -FilePath $testExe -RedirectStandardOutput $guiOut -RedirectStandardError $guiErr -PassThru
    # Keep a handle so Windows PowerShell can reliably report ExitCode.
    $null = $guiProcess.Handle
    if (-not $guiProcess.WaitForExit(60000)) {
        Stop-Process -Id $guiProcess.Id -Force -ErrorAction SilentlyContinue
        $detail = ((Get-Content $guiOut -Raw -ErrorAction SilentlyContinue) + "`n" + (Get-Content $guiErr -Raw -ErrorAction SilentlyContinue) + "`nServer:" + (Get-Content $stderr -Raw -ErrorAction SilentlyContinue))
        throw "GUI test timed out. $detail"
    }
    $guiProcess.Refresh()
    $guiOutput = (Get-Content $guiOut -Raw -ErrorAction SilentlyContinue)
    $guiError = (Get-Content $guiErr -Raw -ErrorAction SilentlyContinue)
    Write-Host $guiOutput
    if ($guiProcess.ExitCode -ne 0) { throw "RMacro GUI/API test failed: $($guiProcess.ExitCode). $guiOutput $guiError" }

    # Run the actual PE with its appended configuration, not only the reader
    # in the test assembly. The real Windows loader must still open normally.
    $env:LOCALAPPDATA = Join-Path $directory 'configured-profile'
    $configuredProcess = Start-Process -FilePath $configured -PassThru
    $null = $configuredProcess.Handle
    $opened = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        $configuredProcess.Refresh()
        if ($configuredProcess.HasExited) { throw "Configured RMacro exited early: $($configuredProcess.ExitCode)" }
        if ($configuredProcess.MainWindowHandle -ne 0 -and $configuredProcess.MainWindowTitle -like 'RMacro*продукты') { $opened = $true; break }
    }
    if (-not $opened) { throw "Configured RMacro main window was not found: $($configuredProcess.MainWindowTitle)" }
    $null = $configuredProcess.CloseMainWindow()
    if (-not $configuredProcess.WaitForExit(5000)) { throw 'Configured RMacro did not close cleanly.' }
    $configuredProcess.Refresh()
    if ($configuredProcess.ExitCode -ne 0) { throw "Configured RMacro failed: $($configuredProcess.ExitCode)" }
    Write-Host 'PASS: owner-configured RMacro.exe opened and closed on Windows.'

    # Exercise the same Windows BAT that the interactive setup/start wrappers use,
    # and take a consistent backup while the fixture server is running.
    $backup = Join-Path $directory 'backup.db'
    & (Join-Path $root 'rmacro\server\RUN-PYTHON.bat') --db $db backup $backup
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $backup)) { throw 'Server BAT/online backup smoke failed.' }
    & $python -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); assert c.execute('select count(*) from users').fetchone()[0] == 1" $backup
    if ($LASTEXITCODE -ne 0) { throw 'Server BAT produced an invalid backup.' }
    Write-Output '::notice title=RMacro integration::PASS: login, DPAPI restore/logout, UID, expiry warning, product launch, remote HWID reset, blocked-UI stop, offline grace, and server BAT backup. No GTA5 or physical keyboard tested.'
}
catch {
    $detail = ($_ | Format-List * -Force | Out-String).Replace('%', '%25').Replace("`r", '%0D').Replace("`n", '%0A')
    if ($detail.Length -gt 5000) { $detail = $detail.Substring(0, 5000) }
    Write-Output "::error title=RMacro integration::$detail"
    throw
}
finally {
    $env:RMACRO_TEST_PORT = $oldPort
    $env:RMACRO_CONFIGURED_EXE = $oldConfigured
    $env:LOCALAPPDATA = $oldLocal
    if ($guiProcess) { $guiProcess.Refresh(); if (-not $guiProcess.HasExited) { Stop-Process -Id $guiProcess.Id -Force } }
    if ($configuredProcess) { $configuredProcess.Refresh(); if (-not $configuredProcess.HasExited) { Stop-Process -Id $configuredProcess.Id -Force } }
    if ($fixture) { $fixture.Refresh(); if (-not $fixture.HasExited) { Stop-Process -Id $fixture.Id -Force } }
    if (Test-Path -LiteralPath $directory) { Remove-Item -LiteralPath $directory -Recurse -Force -ErrorAction SilentlyContinue }
}
