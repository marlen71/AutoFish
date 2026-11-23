param(
    [Parameter(Mandatory = $true)][string]$TestScript,
    [Parameter(Mandatory = $true)][string]$Stage,
    [Parameter(Mandatory = $true)][string]$Loader
)
$ErrorActionPreference = 'Stop'
# Run this script in a CHILD process. Removing privileges is irreversible for
# that process, and every Python/Caddy/PowerShell child inherits its token.
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class TestTokenPrivileges
{
    [StructLayout(LayoutKind.Sequential)]
    private struct Luid { public uint LowPart; public int HighPart; }
    [StructLayout(LayoutKind.Sequential)]
    private struct LuidAndAttributes { public Luid Luid; public uint Attributes; }
    [StructLayout(LayoutKind.Sequential)]
    private struct TokenPrivileges { public uint Count; public LuidAndAttributes Privilege; }
    [DllImport("kernel32.dll")] private static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32.dll")] private static extern bool CloseHandle(IntPtr handle);
    [DllImport("advapi32.dll", SetLastError = true)] private static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr token);
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern bool LookupPrivilegeValue(string system, string name, out Luid luid);
    [DllImport("advapi32.dll", SetLastError = true)] private static extern bool AdjustTokenPrivileges(IntPtr token, bool disableAll, ref TokenPrivileges state, uint size, IntPtr previous, IntPtr returned);

    public static void Remove(string[] names)
    {
        IntPtr token;
        if (!OpenProcessToken(GetCurrentProcess(), 0x20u | 0x8u, out token)) throw new Win32Exception(Marshal.GetLastWin32Error());
        try
        {
            foreach (string name in names)
            {
                Luid luid;
                if (!LookupPrivilegeValue(null, name, out luid)) throw new Win32Exception(Marshal.GetLastWin32Error());
                TokenPrivileges state = new TokenPrivileges { Count = 1, Privilege = new LuidAndAttributes { Luid = luid, Attributes = 4u } };
                if (!AdjustTokenPrivileges(token, false, ref state, 0, IntPtr.Zero, IntPtr.Zero)) throw new Win32Exception(Marshal.GetLastWin32Error());
                int code = Marshal.GetLastWin32Error();
                if (code != 0 && code != 1300) throw new Win32Exception(code); // 1300 = privilege already absent
            }
        }
        finally { CloseHandle(token); }
    }
}
'@
$removed = @('SeSecurityPrivilege', 'SeRestorePrivilege', 'SeBackupPrivilege', 'SeTakeOwnershipPrivilege')
[TestTokenPrivileges]::Remove($removed)
$privileges = & (Join-Path $env:SystemRoot 'System32\whoami.exe') /priv /fo csv /nh
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect child-process token privileges.' }
foreach ($privilege in $removed) {
    if (($privileges -join "`n") -match [regex]::Escape($privilege)) { throw "Privilege was not removed: $privilege" }
}
Write-Host 'PASS: child and descendants lack security, backup, restore and take-ownership privileges.'
$ErrorActionPreference = 'Continue'
& python $TestScript --stage $Stage --loader $Loader
$code = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
exit $code
