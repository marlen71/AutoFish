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
}
public static class SmokeWindows {
    private delegate bool Callback(IntPtr h, IntPtr state);
    [DllImport("user32.dll")] private static extern bool EnumWindows(Callback cb, IntPtr state);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowText(IntPtr h, StringBuilder text, int length);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] private static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);

    public static SmokeWindow[] ForProcess(int processId) {
        List<SmokeWindow> found = new List<SmokeWindow>();
        EnumWindows(delegate(IntPtr h, IntPtr state) {
            uint pid;
            GetWindowThreadProcessId(h, out pid);
            if (pid == processId) {
                StringBuilder title = new StringBuilder(2048);
                GetWindowText(h, title, title.Capacity);
                found.Add(new SmokeWindow { Handle = h, Title = title.ToString(), Visible = IsWindowVisible(h) });
            }
            return true;
        }, IntPtr.Zero);
        return found.ToArray();
    }
    public static void Close(IntPtr handle) { PostMessage(handle, 0x0010, IntPtr.Zero, IntPtr.Zero); }
}
'@

$launcher = Join-Path $root 'RMFish.ps1'
$arguments = '-NoLogo -NoProfile -ExecutionPolicy Bypass -STA -File "' + $launcher + '"'
$process = Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -ArgumentList $arguments -WindowStyle Normal -PassThru
$main = $null
try {
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Milliseconds 500
        $process.Refresh()
        if ($process.HasExited) { throw "Source launcher exited early: $($process.ExitCode)" }
        $windows = @([SmokeWindows]::ForProcess($process.Id))
        $main = $windows | Where-Object { $_.Visible -and $_.Title -like 'RMFish*RMRP' } | Select-Object -First 1
        if ($main) { break }
        $errorWindow = $windows | Where-Object { $_.Visible -and $_.Title -like 'RMFish*' } | Select-Object -First 1
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
        $titles = ($windows | ForEach-Object { "[$($_.Visible)] $($_.Title)" }) -join ' | '
        throw "Source main window not detected. Windows: $titles"
    }
    Write-Host 'PASS: PowerShell source launcher opened its visible main window on Windows.'
}
catch {
    $message = $_.Exception.Message.Replace('%','%25').Replace("`r",'%0D').Replace("`n",'%0A')
    if ($message.Length -gt 5000) { $message = $message.Substring(0, 5000) }
    Write-Output "::error title=PowerShell source launcher::$message"
    throw
}
finally {
    if ($main) { [SmokeWindows]::Close($main.Handle) }
    $process.Refresh()
    if (-not $process.HasExited -and -not $process.WaitForExit(5000)) {
        Stop-Process -Id $process.Id -Force
    }
}
