# RMFish launcher for Windows PowerShell 5.1. No packages need to be installed.
param([switch]$HideConsole)
$ErrorActionPreference = 'Stop'
$mutex = $null
$ownsMutex = $false

try {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    # Only one worker may send clicks, even when the launcher is opened twice.
    $mutex = [System.Threading.Mutex]::new($false, 'Local\RMFish')
    try { $ownsMutex = $mutex.WaitOne(0, $false) }
    catch [System.Threading.AbandonedMutexException] { $ownsMutex = $true }
    if (-not $ownsMutex) {
        [System.Windows.Forms.MessageBox]::Show(
            'RMFish уже запущен. Откройте существующее окно программы.',
            'RMFish', 'OK', 'Information') | Out-Null
        exit 0
    }

    $sources = @(
        (Join-Path $PSScriptRoot 'src\Vision.cs'),
        (Join-Path $PSScriptRoot 'src\StateMachine.cs'),
        (Join-Path $PSScriptRoot 'src\Engine.cs'),
        (Join-Path $PSScriptRoot 'src\WindowsGame.cs'),
        (Join-Path $PSScriptRoot 'src\MainForm.cs')
    )
    $references = @(
        [System.Diagnostics.Process].Assembly.Location,
        [System.Linq.Enumerable].Assembly.Location,
        [System.Drawing.Color].Assembly.Location,
        [System.Windows.Forms.Form].Assembly.Location
    ) | Select-Object -Unique
    Add-Type -LiteralPath $sources -ReferencedAssemblies $references
    if ($HideConsole) { [RMFish.WindowsNative]::HideConsoleWindow() }
    [RMFish.WindowsNative]::EnableDpiAwareness()
    [System.Windows.Forms.Application]::EnableVisualStyles()
    [System.Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
    $form = New-Object RMFish.MainForm -ArgumentList $PSScriptRoot
    [System.Windows.Forms.Application]::Run($form)
}
catch {
    $detail = $_ | Out-String
    try {
        [System.Windows.Forms.MessageBox]::Show(
            "Не удалось запустить RMFish.`n`n$detail`nПроверьте Windows PowerShell 5.1 и целостность папки программы.",
            'RMFish — ошибка запуска', 'OK', 'Error') | Out-Null
    }
    catch { Write-Error $detail }
    exit 1
}
finally {
    if ($ownsMutex -and $mutex) { $mutex.ReleaseMutex() }
    if ($mutex) { $mutex.Dispose() }
}
