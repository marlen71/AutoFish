param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot 'dist')
)

$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSEdition -ne 'Desktop' -or $PSVersionTable.PSVersion.Major -lt 5) {
    throw 'Build the RMFish product module with Windows PowerShell 5.1.'
}
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$csc = Join-Path ([System.Runtime.InteropServices.RuntimeEnvironment]::GetRuntimeDirectory()) 'csc.exe'
if (-not (Test-Path -LiteralPath $csc)) { throw 'The .NET Framework C# compiler was not found.' }
$null = New-Item -ItemType Directory -Path $OutputDirectory -Force
$output = Join-Path (Resolve-Path -LiteralPath $OutputDirectory).Path 'RMFishProduct.dll'
$sources = @(
    'src\Vision.cs', 'src\Relocation.cs', 'src\StateMachine.cs', 'src\Engine.cs', 'src\Safety.cs',
    'src\WindowsGame.cs', 'src\UiComponents.cs', 'src\ChromeControls.cs', 'src\RelocationUi.cs', 'src\MainForm.cs',
    'rmacro\product\ProductEntry.cs'
) | ForEach-Object { Join-Path $PSScriptRoot $_ }
$references = @(
    [System.Diagnostics.Process].Assembly.Location, [System.Linq.Enumerable].Assembly.Location,
    [System.Drawing.Color].Assembly.Location, [System.Windows.Forms.Form].Assembly.Location
) | Select-Object -Unique
$arguments = @('/nologo', '/noconfig', '/target:library', '/platform:anycpu', '/optimize+', '/utf8output', '/warnaserror+', '/define:ETERNAL_CORE',
    "/resource:$(Join-Path $PSScriptRoot 'assets\rmfish-logo.png'),RMFish.BrandLogo.png", "/out:$output")
foreach ($reference in $references) { $arguments += "/reference:$reference" }
$arguments += $sources
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$compilerOutput = & $csc @arguments 2>&1
$compilerExit = $LASTEXITCODE
$ErrorActionPreference = $previousPreference
foreach ($line in $compilerOutput) { Write-Host $line }
if ($compilerExit -ne 0) {
    $detail = (($compilerOutput | Out-String).Replace('%', '%25').Replace("`r", '%0D').Replace("`n", '%0A'))
    if ($detail.Length -gt 8000) { $detail = $detail.Substring(0, 8000) }
    Write-Output "::error title=RMFish product compiler::$detail"
    throw "RMFish product compilation failed with exit code $compilerExit."
}
Write-Host "Built $output"
