param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot 'dist')
)

$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSEdition -ne 'Desktop' -or $PSVersionTable.PSVersion.Major -lt 5) {
    throw 'Build RMFish with Windows PowerShell 5.1 (powershell.exe), not PowerShell 7.'
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$csc = Join-Path ([System.Runtime.InteropServices.RuntimeEnvironment]::GetRuntimeDirectory()) 'csc.exe'
if (-not (Test-Path -LiteralPath $csc)) {
    throw 'The .NET Framework C# compiler csc.exe was not found.'
}

$null = New-Item -ItemType Directory -Path $OutputDirectory -Force
$output = Join-Path (Resolve-Path -LiteralPath $OutputDirectory).Path 'RMFish.exe'
$sources = @(
    (Join-Path $PSScriptRoot 'src\Vision.cs'),
    (Join-Path $PSScriptRoot 'src\Relocation.cs'),
    (Join-Path $PSScriptRoot 'src\StateMachine.cs'),
    (Join-Path $PSScriptRoot 'src\Engine.cs'),
    (Join-Path $PSScriptRoot 'src\Safety.cs'),
    (Join-Path $PSScriptRoot 'src\WindowsGame.cs'),
    (Join-Path $PSScriptRoot 'src\UiComponents.cs'),
    (Join-Path $PSScriptRoot 'src\ChromeControls.cs'),
    (Join-Path $PSScriptRoot 'src\RelocationUi.cs'),
    (Join-Path $PSScriptRoot 'src\MainForm.cs'),
    (Join-Path $PSScriptRoot 'src\Program.cs')
)
$references = @(
    [System.Diagnostics.Process].Assembly.Location,
    [System.Linq.Enumerable].Assembly.Location,
    [System.Drawing.Color].Assembly.Location,
    [System.Windows.Forms.Form].Assembly.Location
) | Select-Object -Unique
$arguments = @(
    '/nologo', '/noconfig', '/target:winexe', '/platform:anycpu', '/optimize+', '/utf8output',
    "/win32icon:$(Join-Path $PSScriptRoot 'assets\rmfish.ico')",
    "/win32manifest:$(Join-Path $PSScriptRoot 'assets\app.manifest')",
    "/resource:$(Join-Path $PSScriptRoot 'assets\rmfish-logo.png'),RMFish.BrandLogo.png",
    "/out:$output"
)
foreach ($reference in $references) { $arguments += "/reference:$reference" }
$arguments += $sources
& $csc @arguments
if ($LASTEXITCODE -ne 0) { throw "RMFish compilation failed with exit code $LASTEXITCODE." }
Write-Host "Built $output"
