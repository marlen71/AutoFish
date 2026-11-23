param(
    [Parameter(Mandatory = $true)][string]$TestScript,
    [Parameter(Mandatory = $true)][string]$Stage,
    [Parameter(Mandatory = $true)][string]$Loader
)
$ErrorActionPreference = 'Stop'
# Start the actual setup with a restricted token derived from this user. The
# local Administrators SID is deny-only and all privileges except traverse are
# disabled. This tests the user ACE rather than relying on the runner's admin
# group. No account, password, system policy, or parent token is modified.
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;

public static class RestrictedSetupProcess
{
    [StructLayout(LayoutKind.Sequential)]
    private struct SidAndAttributes { public IntPtr Sid; public uint Attributes; }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct StartupInfo
    {
        public int Size;
        public string Reserved, Desktop, Title;
        public int X, Y, XSize, YSize, XChars, YChars, FillAttribute, Flags;
        public short ShowWindow, Reserved2Size;
        public IntPtr Reserved2, StdInput, StdOutput, StdError;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct ProcessInformation { public IntPtr Process, Thread; public int ProcessId, ThreadId; }
    [DllImport("kernel32.dll")] private static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32.dll")] private static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool GetExitCodeProcess(IntPtr handle, out uint code);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool TerminateProcess(IntPtr handle, uint code);
    [DllImport("advapi32.dll", SetLastError = true)] private static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr token);
    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool CreateRestrictedToken(IntPtr existing, uint flags, uint disableCount, ref SidAndAttributes disabled,
        uint deleteCount, IntPtr deleted, uint restrictCount, IntPtr restricted, out IntPtr token);
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CreateProcessAsUser(IntPtr token, string application, StringBuilder command, IntPtr processAttributes,
        IntPtr threadAttributes, bool inheritHandles, uint flags, IntPtr environment, string directory,
        ref StartupInfo startup, out ProcessInformation process);

    public static int Run(string application, string command)
    {
        IntPtr original = IntPtr.Zero, limited = IntPtr.Zero, sidMemory = IntPtr.Zero;
        ProcessInformation process = new ProcessInformation();
        try
        {
            // Assign-primary, duplicate, impersonate, query, adjust-default and
            // adjust-privileges access on a copy of our own process token.
            if (!OpenProcessToken(GetCurrentProcess(), 0xAFu, out original)) throw new Win32Exception(Marshal.GetLastWin32Error());
            SecurityIdentifier admin = new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null);
            byte[] bytes = new byte[admin.BinaryLength];
            admin.GetBinaryForm(bytes, 0);
            sidMemory = Marshal.AllocHGlobal(bytes.Length);
            Marshal.Copy(bytes, 0, sidMemory, bytes.Length);
            SidAndAttributes denied = new SidAndAttributes { Sid = sidMemory, Attributes = 0 };
            if (!CreateRestrictedToken(original, 1u, 1u, ref denied, 0, IntPtr.Zero, 0, IntPtr.Zero, out limited))
                throw new Win32Exception(Marshal.GetLastWin32Error());
            // Keep the parent's console association: CREATE_NO_WINDOW can
            // prevent USER32/console initialization for restricted tokens.
            StartupInfo startup = new StartupInfo { Size = Marshal.SizeOf(typeof(StartupInfo)), Flags = 1, ShowWindow = 0 };
            if (!CreateProcessAsUser(limited, application, new StringBuilder(command), IntPtr.Zero, IntPtr.Zero,
                                     true, 0u, IntPtr.Zero, null, ref startup, out process))
                throw new Win32Exception(Marshal.GetLastWin32Error());
            uint wait = WaitForSingleObject(process.Process, 180000u);
            if (wait == 258u) { TerminateProcess(process.Process, 1u); throw new TimeoutException("Restricted setup timed out."); }
            if (wait != 0u) throw new Win32Exception(Marshal.GetLastWin32Error());
            uint code;
            if (!GetExitCodeProcess(process.Process, out code)) throw new Win32Exception(Marshal.GetLastWin32Error());
            return unchecked((int)code);
        }
        finally
        {
            if (process.Thread != IntPtr.Zero) CloseHandle(process.Thread);
            if (process.Process != IntPtr.Zero) CloseHandle(process.Process);
            if (limited != IntPtr.Zero) CloseHandle(limited);
            if (original != IntPtr.Zero) CloseHandle(original);
            if (sidMemory != IntPtr.Zero) Marshal.FreeHGlobal(sidMemory);
        }
    }
}
'@
$log = Join-Path $Stage ('.restricted-setup-' + [guid]::NewGuid().ToString('N') + '.log')
$oldLog = $env:ETERNAL_RESTRICTED_TEST_LOG
$env:ETERNAL_RESTRICTED_TEST_LOG = $log
try {
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $child = Join-Path $PSScriptRoot 'Run-WithoutSecurityPrivilege.ps1'
    # Windows filenames cannot contain quote characters; all four paths are
    # quoted to preserve spaces, apostrophes and non-ASCII characters.
    $command = '"{0}" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{1}" -TestScript "{2}" -Stage "{3}" -Loader "{4}" -RequireNonAdmin' -f $powershell, $child, $TestScript, $Stage, $Loader
    $code = [RestrictedSetupProcess]::Run($powershell, $command)
    if (Test-Path -LiteralPath $log) { Get-Content -LiteralPath $log -Encoding UTF8 | ForEach-Object { Write-Host $_ } }
    if ($code -ne 0) { throw "Restricted-token setup failed with exit code $code." }
    if (-not (Test-Path -LiteralPath $log)) { throw 'Restricted-token setup did not report its token checks.' }
}
finally {
    $env:ETERNAL_RESTRICTED_TEST_LOG = $oldLog
    Remove-Item -LiteralPath $log -Force -ErrorAction SilentlyContinue
}
