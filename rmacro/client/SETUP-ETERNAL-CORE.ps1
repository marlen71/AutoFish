param(
    [switch]$CheckOnly,
    [switch]$NoLaunch
)

# Bootstrap prerequisites for the client only. The embedded RMFish needs the
# same .NET Framework as the loader; Python, pip, OCR and the server are NOT
# installed or modified by this script.
$ErrorActionPreference = 'Stop'
try {
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    if ($env:OS -ne 'Windows_NT' -or $PSVersionTable.PSVersion.Major -lt 5 -or $PSVersionTable.PSEdition -ne 'Desktop') {
        throw 'Нужны Windows 10/11 и Windows PowerShell 5.1 (powershell.exe).'
    }
    function Get-FrameworkRelease {
        foreach ($view in @([Microsoft.Win32.RegistryView]::Registry64, [Microsoft.Win32.RegistryView]::Registry32)) {
            $base = $null; $key = $null
            try {
                $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine, $view)
                $key = $base.OpenSubKey('SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full', $false)
                if ($key) {
                    $release = $key.GetValue('Release', 0)
                    if ($release -is [int] -and $release -ge 378389) { return [int]$release }
                }
            }
            catch { }
            finally { if ($key) { $key.Dispose() }; if ($base) { $base.Dispose() } }
        }
        return 0
    }

    $release = Get-FrameworkRelease
    if ($release -ge 378389) {
        Write-Host ".NET Framework 4.5 или новее найден (Release $release). Дополнительные компоненты для встроенного RMFish не нужны."
    }
    elseif ($CheckOnly) {
        Write-Host '.NET Framework 4.5 или новее не найден.'
        exit 2
    }
    else {
        Write-Host '.NET Framework 4.5 или новее не найден. Можно установить .NET Framework 4.8 от Microsoft.'
        Write-Host 'Будут использованы интернет и запрос прав администратора Windows. Сервер и Python не устанавливаются.'
        $answer = Read-Host 'Продолжить? [Y/N]'
        if ($answer -notmatch '^(?i:y|yes|д|да)$') { Write-Host 'Установка отменена.'; exit 2 }
        $installer = Join-Path ([IO.Path]::GetTempPath()) ('eternal-dotnet-' + [Guid]::NewGuid().ToString('N') + '.exe')
        $response = $null; $input = $null; $output = $null
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]3072
            # Microsoft .NET Framework 4.8 offline installer. HTTPS certificate
            # validation is left to Windows; never bypass it.
            $request = [Net.HttpWebRequest]::Create('https://go.microsoft.com/fwlink/?linkid=2088631')
            $request.Timeout = 30000; $request.ReadWriteTimeout = 30000; $request.AllowAutoRedirect = $true
            $response = $request.GetResponse()
            if ($response.ResponseUri.Scheme -ne 'https') { throw 'Microsoft перенаправила загрузку не на HTTPS.' }
            $limit = 160MB
            if ($response.ContentLength -gt $limit) { throw 'Установщик слишком большой.' }
            $input = $response.GetResponseStream()
            $output = [IO.File]::Open($installer, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            $buffer = New-Object byte[] 65536; $total = 0L
            while (($read = $input.Read($buffer, 0, $buffer.Length)) -gt 0) {
                $total += $read
                if ($total -gt $limit) { throw 'Установщик слишком большой.' }
                $output.Write($buffer, 0, $read)
            }
            $output.Dispose(); $output = $null; $input.Dispose(); $input = $null; $response.Dispose(); $response = $null
            $signature = Get-AuthenticodeSignature -LiteralPath $installer
            if ($signature.Status -ne [Management.Automation.SignatureStatus]::Valid -or -not $signature.SignerCertificate -or
                $signature.SignerCertificate.Subject -notmatch '(?i)(?:^|,\s*)CN=Microsoft Corporation(?:,|$)' -or
                $signature.SignerCertificate.Subject -notmatch '(?i)(?:^|,\s*)O=Microsoft Corporation(?:,|$)') {
                throw 'Цифровая подпись Microsoft не прошла проверку. Установщик не будет запущен.'
            }
            Write-Host 'Подпись Microsoft проверена. Подтвердите запрос Windows UAC.'
            $process = Start-Process -FilePath $installer -ArgumentList '/passive', '/norestart' -Verb RunAs -Wait -PassThru
            if ($process.ExitCode -eq 3010) { Write-Host 'Требуется перезагрузка Windows. После неё снова запустите SETUP-ETERNAL-CORE.bat.'; exit 2 }
            if ($process.ExitCode -ne 0 -or (Get-FrameworkRelease) -lt 378389) {
                throw "Установка .NET не завершилась успешно (код $($process.ExitCode))."
            }
            Write-Host '.NET Framework установлен.'
        }
        finally {
            if ($output) { $output.Dispose() }; if ($input) { $input.Dispose() }; if ($response) { $response.Dispose() }
            if (Test-Path -LiteralPath $installer) { Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue }
        }
    }
    if (-not $CheckOnly -and -not $NoLaunch) {
        $exe = Join-Path $PSScriptRoot 'EternalCore.exe'
        if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'Распакуйте весь клиентский архив: рядом с этим файлом нужен EternalCore.exe.' }
        Start-Process -FilePath $exe -WorkingDirectory $PSScriptRoot | Out-Null
    }
    exit 0
}
catch {
    Write-Host ('Ошибка подготовки Eternal Core: ' + $_.Exception.Message)
    Write-Host 'Программа и сервер не изменены. Обратитесь в поддержку или установите .NET Framework с сайта Microsoft вручную.'
    exit 1
}
