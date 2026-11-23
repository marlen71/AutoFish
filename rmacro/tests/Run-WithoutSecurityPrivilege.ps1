param(
    [Parameter(Mandatory = $true)][string]$TestScript,
    [Parameter(Mandatory = $true)][string]$Stage,
    [Parameter(Mandatory = $true)][string]$Loader,
    [switch]$RequireNonAdmin
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
    [DllImport("advapi32.dll", SetLastError = true)] private static extern bool GetTokenInformation(IntPtr token, int kind, IntPtr buffer, uint size, out uint needed);

    public static bool Contains(string name)
    {
        Luid target;
        if (!LookupPrivilegeValue(null, name, out target)) throw new Win32Exception(Marshal.GetLastWin32Error());
        IntPtr token, buffer = IntPtr.Zero;
        if (!OpenProcessToken(GetCurrentProcess(), 0x8u, out token)) throw new Win32Exception(Marshal.GetLastWin32Error());
        try
        {
            uint needed;
            GetTokenInformation(token, 3, IntPtr.Zero, 0, out needed); // TokenPrivileges
            if (needed == 0) throw new Win32Exception(Marshal.GetLastWin32Error());
            buffer = Marshal.AllocHGlobal((int)needed);
            if (!GetTokenInformation(token, 3, buffer, needed, out needed)) throw new Win32Exception(Marshal.GetLastWin32Error());
            int count = Marshal.ReadInt32(buffer);
            int size = Marshal.SizeOf(typeof(LuidAndAttributes));
            for (int i = 0; i < count; i++)
            {
                IntPtr item = IntPtr.Add(buffer, 4 + i * size);
                LuidAndAttributes current = (LuidAndAttributes)Marshal.PtrToStructure(item, typeof(LuidAndAttributes));
                if (current.Luid.LowPart == target.LowPart && current.Luid.HighPart == target.HighPart) return true;
            }
            return false;
        }
        finally { if (buffer != IntPtr.Zero) Marshal.FreeHGlobal(buffer); CloseHandle(token); }
    }

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
try {
    if ($RequireNonAdmin) {
        $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
        $administrators = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
        if ($principal.IsInRole($administrators)) { throw 'Administrators SID is still enabled in the child token.' }
    }
    $removed = @('SeSecurityPrivilege', 'SeRestorePrivilege', 'SeBackupPrivilege', 'SeTakeOwnershipPrivilege')
    # The restricted launcher already deleted these privileges on our token.
    # A restricted child might lack the right to reopen its token for adjustment.
    if (-not $RequireNonAdmin) { [TestTokenPrivileges]::Remove($removed) }
    foreach ($privilege in $removed) {
        if ([TestTokenPrivileges]::Contains($privilege)) { throw "Privilege was not removed: $privilege" }
    }
    $ErrorActionPreference = 'Continue'
    $global:LASTEXITCODE = $null
    $output = & python $TestScript --stage $Stage --loader $Loader 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $detail = $output | Out-String
    if ($detail.Length -gt 1800) { $detail = $detail.Substring($detail.Length - 1800) }
    if ($null -eq $code -or $code -ne 0 -or $detail -notmatch 'PASS: BAT owner setup accepted') {
        throw "Restricted Python setup did not pass (exit=$code): $detail"
    }
    $text = "PASS: Administrators SID disabled; security, backup, restore and take-ownership privileges absent.`r`n" + $detail
    if ($env:ETERNAL_RESTRICTED_TEST_LOG) {
        [IO.File]::WriteAllText($env:ETERNAL_RESTRICTED_TEST_LOG, $text, [Text.UTF8Encoding]::new($true))
    } else { Write-Host $text }
    exit $code
}
catch {
    $text = $_ | Format-List * -Force | Out-String
    if ($env:ETERNAL_RESTRICTED_TEST_LOG) {
        [IO.File]::WriteAllText($env:ETERNAL_RESTRICTED_TEST_LOG, $text, [Text.UTF8Encoding]::new($true))
    } else { Write-Host $text }
    exit 1
}
