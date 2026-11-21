param([switch]$ViaBat)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public sealed class SmokeWindow {
    public IntPtr Handle;
    public string Title;
    public bool Visible;
    public bool Minimized;
}
public static class SmokeWindows {
    private delegate bool Callback(IntPtr h, IntPtr state);
    [DllImport("user32.dll")] private static extern bool EnumWindows(Callback cb, IntPtr state);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowText(IntPtr h, StringBuilder text, int length);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] private static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] private static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);

    public static SmokeWindow[] ForProcess(int processId) {
        List<SmokeWindow> found = new List<SmokeWindow>();
        EnumWindows(delegate(IntPtr h, IntPtr state) {
            uint pid;
            GetWindowThreadProcessId(h, out pid);
            if (pid == processId) {
                StringBuilder title = new StringBuilder(2048);
                GetWindowText(h, title, title.Capacity);
                found.Add(new SmokeWindow { Handle = h, Title = title.ToString(), Visible = IsWindowVisible(h), Minimized = IsIconic(h) });
            }
            return true;
        }, IntPtr.Zero);
        return found.ToArray();
    }
    public static void Close(IntPtr handle) { PostMessage(handle, 0x0010, IntPtr.Zero, IntPtr.Zero); }
}
'@

$launcher = Join-Path $root 'RMFish.ps1'
$process = $null
$main = $null
try {
    if ($ViaBat) {
        # The BAT starts a separate PowerShell process and exits immediately.
        # Find that process by its script path, not by an unrelated console.
        $existing = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
            Where-Object { $_.CommandLine -like "*$launcher*" } | Select-Object -ExpandProperty ProcessId)
        $bat = Join-Path $root 'RMFish.bat'
        $cmd = Start-Process -FilePath $env:ComSpec -ArgumentList ('/d /c "' + $bat + '"') -WorkingDirectory $root -PassThru
        try {
            if (-not $cmd.WaitForExit(10000)) { throw 'RMFish.bat did not return.' }
            if ($cmd.ExitCode -ne 0) { throw "RMFish.bat exited with code $($cmd.ExitCode)." }
        }
        finally {
            $cmd.Refresh()
            if (-not $cmd.HasExited) { Stop-Process -Id $cmd.Id -Force }
        }
        for ($i = 0; $i -lt 40; $i++) {
            $child = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
                Where-Object { $_.CommandLine -like "*$launcher*" -and $existing -notcontains $_.ProcessId } |
                Select-Object -First 1
            if ($child) { $process = [Diagnostics.Process]::GetProcessById($child.ProcessId); break }
            Start-Sleep -Milliseconds 250
        }
        if (-not $process) { throw 'RMFish.bat did not start the PowerShell launcher.' }
    }
    else {
        $arguments = '-NoLogo -NoProfile -ExecutionPolicy Bypass -STA -File "' + $launcher + '"'
        $process = Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -ArgumentList $arguments -WindowStyle Normal -PassThru
    }
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Milliseconds 500
        $process.Refresh()
        if ($process.HasExited) { throw "Source launcher exited early: $($process.ExitCode)" }
        $windows = @([SmokeWindows]::ForProcess($process.Id))
        $main = $windows | Where-Object { $_.Visible -and -not $_.Minimized -and $_.Title -like 'RMFish*RMRP' } | Select-Object -First 1
        if ($main) { break }
        $errorWindow = $windows | Where-Object { $_.Visible -and $_.Title -like 'RMFish*' -and $_.Title -notlike 'RMFish*RMRP' } | Select-Object -First 1
        if ($errorWindow) {
            $details = ''
            try {
                Add-Type -AssemblyName UIAutomationClient
                Add-Type -AssemblyName UIAutomationTypes
                $element = [System.Windows.Automation.AutomationElement]::FromHandle($errorWindow.Handle)
                $children = $element.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
                $details = (($children | ForEach-Object { $_.Current.Name } | Where-Object { $_ }) -join ' | ')
            } catch { $details = 'Could not read dialog text: ' + $_.Exception.Message }
            throw "Unexpected RMFish dialog: $($errorWindow.Title). $details"
        }
    }
    if (-not $main) {
        $titles = ($windows | ForEach-Object { "[visible=$($_.Visible), minimized=$($_.Minimized)] $($_.Title)" }) -join ' | '
        throw "Source main window not detected. Windows: $titles"
    }
    $kind = if ($ViaBat) { "BAT" } else { "PowerShell" }
    Write-Host "PASS: $kind source launcher opened its visible main window on Windows."
}
catch {
    $message = $_.Exception.Message.Replace('%','%25').Replace("`r",'%0D').Replace("`n",'%0A')
    if ($message.Length -gt 5000) { $message = $message.Substring(0, 5000) }
    Write-Output "::error title=PowerShell source launcher::$message"
    throw
}
finally {
    if ($main) { [SmokeWindows]::Close($main.Handle) }
    if ($process) {
        $process.Refresh()
        if (-not $process.HasExited -and -not $process.WaitForExit(5000)) {
            Stop-Process -Id $process.Id -Force
        }
    }
}
