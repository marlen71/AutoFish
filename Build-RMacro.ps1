param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot 'dist')
)

$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSEdition -ne 'Desktop' -or $PSVersionTable.PSVersion.Major -lt 5) {
    throw 'Build RMacro with Windows PowerShell 5.1 (powershell.exe), not PowerShell 7.'
}
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Web.Extensions
Add-Type -AssemblyName System.Security
$csc = Join-Path ([System.Runtime.InteropServices.RuntimeEnvironment]::GetRuntimeDirectory()) 'csc.exe'
if (-not (Test-Path -LiteralPath $csc)) { throw 'The .NET Framework C# compiler csc.exe was not found.' }
$null = New-Item -ItemType Directory -Path $OutputDirectory -Force
$output = Join-Path (Resolve-Path -LiteralPath $OutputDirectory).Path 'RMacro.exe'
$sources = @(
    'src\Vision.cs', 'src\StateMachine.cs', 'src\Engine.cs', 'src\Safety.cs',
    'src\WindowsGame.cs', 'src\UiComponents.cs', 'src\ChromeControls.cs', 'src\MainForm.cs',
    'rmacro\client\ClientCore.cs', 'rmacro\client\ClientUi.cs', 'rmacro\client\Program.cs'
) | ForEach-Object { Join-Path $PSScriptRoot $_ }
$references = @(
    [System.Diagnostics.Process].Assembly.Location,
    [System.Linq.Enumerable].Assembly.Location,
    [System.Drawing.Color].Assembly.Location,
    [System.Windows.Forms.Form].Assembly.Location,
    [System.Web.Script.Serialization.JavaScriptSerializer].Assembly.Location,
    [System.Security.Cryptography.ProtectedData].Assembly.Location
) | Select-Object -Unique
$arguments = @(
    '/nologo', '/noconfig', '/target:winexe', '/platform:anycpu', '/optimize+', '/utf8output', '/warnaserror+',
    "/win32icon:$(Join-Path $PSScriptRoot 'assets\rmfish.ico')",
    "/win32manifest:$(Join-Path $PSScriptRoot 'rmacro\client\app.manifest')",
    "/resource:$(Join-Path $PSScriptRoot 'assets\rmfish-logo.png'),RMFish.BrandLogo.png",
    "/resource:$(Join-Path $PSScriptRoot 'assets\rmfish-icon-original.png'),RMacro.FishIcon.png",
    "/resource:$(Join-Path $PSScriptRoot 'assets\rmacro-city.png'),RMacro.City.png",
    "/out:$output"
)
foreach ($reference in $references) { $arguments += "/reference:$reference" }
$arguments += $sources
& $csc @arguments
if ($LASTEXITCODE -ne 0) { throw "RMacro compilation failed with exit code $LASTEXITCODE." }
Write-Host "Built $output"
