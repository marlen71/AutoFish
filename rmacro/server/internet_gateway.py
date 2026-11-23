"""Optional, owner-operated HTTPS gateway for an IPv4 address.

The Python application remains bound to loopback. Caddy terminates public TLS
and forwards only the loader's exact API routes. The production Caddy archive
is downloaded from its official GitHub release and checked against a pinned
SHA-256 before any executable is extracted or run. No service, firewall,
router, account, database, or operating-system trust store is changed here.
"""
import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
import uuid
import zipfile

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "data" / "internet-gateway"
SETTINGS = STATE / "settings.json"
CONFIG = STATE / "Caddyfile"
PUBLIC_PORT = 8765
BACKEND_PORT = 18765
CADDY_VERSION = "2.11.9"
CADDY_RELEASE = "https://github.com/caddyserver/caddy/releases/download/v" + CADDY_VERSION + "/"
# GitHub release asset digests, obtained from caddyserver/caddy v2.11.9.
ARCHIVES = {
    "amd64": ("caddy_2.11.9_windows_amd64.zip", "ad93112d335ee687100c4c9f11bced16ca590377976b7fe7883882b9e797e472"),
    "arm64": ("caddy_2.11.9_windows_arm64.zip", "bdf5fa34e7f3646ee04f59634d66cbcbfa39516f08108d8661ff3ceb3913a0c7"),
}
MAX_ARCHIVE = 32 * 1024 * 1024
MAX_EXECUTABLE = 128 * 1024 * 1024
CLIENT_PATHS = ("/api/health", "/api/login", "/api/logout", "/api/authorize", "/api/me",
                "/api/me/password", "/api/me/activate-key")


def public_ipv4(value):
    try:
        if not isinstance(value, str):
            raise ValueError("IPv4 должен быть строкой.")
        address = ipaddress.IPv4Address(value.strip())
        if not address.is_global or address.is_multicast or address.is_unspecified:
            raise ValueError("Это не публичный IPv4.")
        return str(address)
    except ipaddress.AddressValueError as exc:
        raise ValueError("Введите публичный IPv4, например 8.8.8.8, без порта и протокола.") from exc


def archive_for_platform():
    if os.name != "nt":
        raise ValueError("Автоматический шлюз предназначен для Windows 10/11.")
    machine = (os.environ.get("PROCESSOR_ARCHITEW6432") or platform.machine()).lower()
    if machine in ("amd64", "x86_64", "x64"):
        return ARCHIVES["amd64"]
    if machine in ("arm64", "aarch64"):
        return ARCHIVES["arm64"]
    raise ValueError("Нужна Windows x64 или ARM64 для Caddy.")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def atomic_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=str(path.parent),
                                         prefix=".eternal-", delete=False) as output:
            name = output.name
            output.write(text)
        os.replace(name, str(path))
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def download_archive(path, filename, expected_hash):
    """Download one pinned release archive without executing downloaded code."""
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(CADDY_RELEASE + filename,
                                     headers={"User-Agent": "EternalCore-Internet-Setup/1"})
    temporary = None
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if urllib.parse.urlsplit(response.geturl()).scheme.lower() != "https":
                raise ValueError("Загрузка Caddy была перенаправлена не на HTTPS.")
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_ARCHIVE:
                raise ValueError("Архив Caddy слишком большой.")
            digest = hashlib.sha256()
            total = 0
            with tempfile.NamedTemporaryFile("wb", dir=str(path.parent), prefix=".caddy-", delete=False) as output:
                temporary = output.name
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_ARCHIVE:
                        raise ValueError("Архив Caddy слишком большой.")
                    digest.update(chunk)
                    output.write(chunk)
        if digest.hexdigest() != expected_hash:
            raise ValueError("SHA-256 загруженного Caddy не совпадает. Архив не будет запущен.")
        os.replace(temporary, str(path))
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def extract_verified_archive(archive, expected_hash, destination):
    """Extract exactly caddy.exe after checking the complete official archive."""
    if not archive.is_file() or archive.stat().st_size > MAX_ARCHIVE or sha256_file(archive) != expected_hash:
        raise ValueError("Архив Caddy отсутствует или его SHA-256 не совпадает. Запустите CONFIGURE-INTERNET.bat снова.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        try:
            with zipfile.ZipFile(str(archive)) as bundle:
                matches = [item for item in bundle.infolist() if item.filename == "caddy.exe"]
                if len(matches) != 1 or matches[0].is_dir() or not 0 < matches[0].file_size <= MAX_EXECUTABLE:
                    raise ValueError("В архиве Caddy нет ожидаемого caddy.exe.")
                with bundle.open(matches[0]) as source, tempfile.NamedTemporaryFile(
                        "wb", dir=str(destination.parent), prefix=".caddy-exe-", delete=False) as output:
                    temporary = output.name
                    shutil.copyfileobj(source, output, length=1024 * 1024)
        except zipfile.BadZipFile as exc:
            raise ValueError("Архив Caddy повреждён.") from exc
        os.replace(temporary, str(destination))
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def caddyfile(ip, public_port=PUBLIC_PORT, backend_port=BACKEND_PORT, test_certificate=None):
    """Build the TLS-only allowlist; test_certificate is a local fixture only."""
    ip = str(ipaddress.IPv4Address(ip))
    for port in (public_port, backend_port):
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("Некорректный порт шлюза.")
    if test_certificate is None:
        tls = "    tls internal\n"
    else:
        cert, key = test_certificate
        tls = "    tls %s %s\n" % (json.dumps(str(cert)), json.dumps(str(key)))
    return ("{\n"
            "    admin off\n"
            "    auto_https disable_redirects\n"
            "    skip_install_trust\n"
            "    default_sni " + ip + "\n"
            "}\n\n"
            "https://" + ip + ":" + str(public_port) + " {\n" + tls +
            "    @client_api path " + " ".join(CLIENT_PATHS) + "\n"
            "    handle @client_api {\n"
            "        reverse_proxy 127.0.0.1:" + str(backend_port) + " {\n"
            "            header_up X-EternalCore-Client-IP {remote_host}\n"
            "            transport http {\n"
            "                keepalive off\n"
            "            }\n"
            "        }\n"
            "    }\n"
            "    handle {\n"
            "        respond \"Not found\" 404\n"
            "    }\n"
            "}\n")


def caddy_environment():
    environment = os.environ.copy()
    environment["XDG_DATA_HOME"] = str((STATE / "caddy-data").resolve())
    environment["XDG_CONFIG_HOME"] = str((STATE / "caddy-config").resolve())
    return environment


def authority_directory():
    return STATE / "caddy-data" / "caddy" / "pki" / "authorities" / "local"


def restrict_authority():
    """Protect all Caddy keys before creation; Windows chmod does not set ACLs."""
    directory = STATE / "caddy-data"
    directory.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        directory.chmod(0o700)
        for item in directory.rglob("*"):
            if item.is_symlink():
                raise ValueError("Недопустимая ссылка в папке закрытых ключей.")
            if item.is_dir():
                item.chmod(0o700)
            elif item.is_file():
                item.chmod(0o600)
        return
    # Only the setup account, SYSTEM and local administrators may read/write
    # Caddy's CA and leaf keys. Existing files get explicit ACLs too.
    # Never interpolate an owner-controlled path into a PowerShell command.
    script = r'''$ErrorActionPreference = 'Stop'
$folder = $env:ETERNAL_CA_DIR
$user = [Security.Principal.WindowsIdentity]::GetCurrent().User
$sids = @($user, [Security.Principal.SecurityIdentifier]::new('S-1-5-18'), [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
$right = [Security.AccessControl.FileSystemRights]::FullControl
$allow = [Security.AccessControl.AccessControlType]::Allow
$prop = [Security.AccessControl.PropagationFlags]::None
$inherit = [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit
$items = @((Get-Item -LiteralPath $folder -Force)) + @(Get-ChildItem -LiteralPath $folder -Force -Recurse)
foreach ($item in $items) {
    # OneDrive placeholders can be reparse points too; reject filesystem links,
    # not cloud placeholder attributes used by an owner's Desktop directory.
    if (@('SymbolicLink', 'Junction', 'HardLink') -contains $item.LinkType) { throw 'Links are not allowed in the Caddy data directory.' }
    if ($item.PSIsContainer) {
        $acl = [Security.AccessControl.DirectorySecurity]::new()
        $acl.SetAccessRuleProtection($true, $false)
        foreach ($sid in $sids) { $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid, $right, $inherit, $prop, $allow)) }
    } else {
        $acl = [Security.AccessControl.FileSecurity]::new()
        $acl.SetAccessRuleProtection($true, $false)
        foreach ($sid in $sids) { $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid, $right, $allow)) }
    }
    Set-Acl -LiteralPath $item.FullName -AclObject $acl
}
'''
    environment = os.environ.copy()
    environment["ETERNAL_CA_DIR"] = str(directory.resolve())
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                       env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        detail = getattr(exc, "stderr", b"") or b""
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace")
        raise ValueError("Не удалось ограничить доступ к закрытым ключам. Проверьте права на папку сервера. " + detail[:1000]) from exc


def authority_record_path():
    return STATE / "authority.json"


def load_authority(expected=None):
    """Fail closed if persisted CA state or either cert/key pair was changed."""
    directory = authority_directory()
    record = authority_record_path()
    error = ("Внутренний сертификат или ключ повреждён, отсутствует либо изменён. "
             "Восстановите папку data/internet-gateway из защищённой резервной копии; "
             "не создавайте новый центр без повторной раздачи клиента.")
    try:
        info = json.loads(record.read_text(encoding="utf-8"))
        if (not isinstance(info, dict) or set(info) != {"version", "sha256"} or info["version"] != 1 or
                not isinstance(info["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", info["sha256"])):
            raise ValueError(error)
        for name in ("root.crt", "root.key", "intermediate.crt", "intermediate.key"):
            path = directory / name
            if not path.is_file() or not 0 < path.stat().st_size <= 16384:
                raise ValueError(error)
        root_text = (directory / "root.crt").read_text(encoding="ascii")
        if root_text.count("-----BEGIN CERTIFICATE-----") != 1:
            raise ValueError(error)
        der = ssl.PEM_cert_to_DER_cert(root_text)
        if not 1 <= len(der) <= 4096:
            raise ValueError(error)
        digest = hashlib.sha256(der).hexdigest()
        if digest != info["sha256"] or (expected is not None and digest != expected):
            raise ValueError(error)
        # OpenSSL checks that each stored certificate matches its private key.
        for name in ("root", "intermediate"):
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(str(directory / (name + ".crt")), str(directory / (name + ".key")))
        return der
    except (OSError, UnicodeError, json.JSONDecodeError, ssl.SSLError, ValueError) as exc:
        raise ValueError(error) from exc


def provision_authority(executable, ip):
    """Create the CA once without ACME/network listeners, or reuse it exactly."""
    directory = authority_directory()
    record = authority_record_path()
    existing = [directory / name for name in ("root.crt", "root.key", "intermediate.crt", "intermediate.key")]
    # V2 settings independently pin the CA, so replacing both certificate and
    # authority.json cannot silently turn an existing installation into a new CA.
    try:
        old = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except FileNotFoundError:
        old = None
    except (OSError, ValueError) as exc:
        raise ValueError("Настройки шлюза повреждены; восстановите резервную копию data/internet-gateway.") from exc
    expected = None
    if old is not None:
        if not isinstance(old, dict) or old.get("version") not in (1, 2):
            raise ValueError("Настройки шлюза повреждены; восстановите резервную копию data/internet-gateway.")
        if old["version"] == 1 and set(old) != {"version", "ipv4"}:
            raise ValueError("Настройки шлюза повреждены.")
        if old["version"] == 2:
            if (set(old) != {"version", "ipv4", "ca_sha256"} or
                    not isinstance(old["ca_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", old["ca_sha256"])):
                raise ValueError("Настройки шлюза повреждены.")
            expected = old["ca_sha256"]
    if record.exists():
        restrict_authority()
        return load_authority(expected)
    if any(path.exists() for path in existing):
        raise ValueError("Найдены неполные данные внутреннего сертификата без записи доверия. "
                         "Восстановите папку data/internet-gateway из резервной копии.")
    if expected is not None:
        raise ValueError("Внутренний сертификат потерян. Восстановите data/internet-gateway из резервной копии.")
    # If both metadata files were lost but a previously configured V2 client
    # remains, do not silently create a different CA that breaks those clients.
    for candidate in (ROOT / "configured-client").glob("internet-*/EternalCore.exe"):
        try:
            with candidate.open("rb") as client:
                client.seek(-len(b"RMACRO_TLS_V2"), os.SEEK_END)
                if client.read() == b"RMACRO_TLS_V2":
                    raise ValueError("Найдена ранее настроенная защищённая копия без её сертификата. Восстановите data/internet-gateway.")
        except OSError as exc:
            raise ValueError("Не удалось проверить ранее настроенную копию лоадера.") from exc
    restrict_authority()
    bootstrap = STATE / (".bootstrap-" + uuid.uuid4().hex + ".Caddyfile")
    try:
        atomic_text(bootstrap, caddyfile(ip))
        # validate provisions the PKI but does not start listeners or contact ACME.
        result = subprocess.run([str(executable), "validate", "--config", str(bootstrap), "--adapter", "caddyfile"],
                                cwd=str(ROOT), env=caddy_environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=60)
        if result.returncode:
            raise ValueError("Не удалось создать внутренний сертификат через проверенный Caddy.")
        restrict_authority()
        root = directory / "root.crt"
        if not root.is_file() or root.stat().st_size > 16384:
            raise ValueError("Caddy не создал внутренний сертификат.")
        der = ssl.PEM_cert_to_DER_cert(root.read_text(encoding="ascii"))
        if not 1 <= len(der) <= 4096:
            raise ValueError("Внутренний сертификат слишком велик.")
        digest = hashlib.sha256(der).hexdigest()
        atomic_text(record, json.dumps({"version": 1, "sha256": digest}, indent=2) + "\n")
        return load_authority(digest)
    finally:
        try:
            bootstrap.unlink()
        except FileNotFoundError:
            pass


def setup(configure_loader):
    print("HTTPS через публичный IPv4: встроенный сертификат создаётся автоматически, без Let's Encrypt и порта 80.")
    print("Нужен доступный извне TCP 8765. Остановите сервер перед настройкой.")
    print("Админ-панель при таком запуске доступна только на серверном ПК.")
    ip = public_ipv4(input("Публичный IPv4 сервера (без порта): "))
    source = input("Путь к распакованному EternalCore.exe нового клиентского архива: ").strip().strip('"')
    if not source or not Path(source).expanduser().is_file():
        raise ValueError("Укажите существующий EternalCore.exe из распакованного клиентского архива.")
    source_path = Path(source).expanduser()
    if source_path.stat().st_size > MAX_EXECUTABLE:
        raise ValueError("Исходный EXE слишком велик.")
    image = source_path.read_bytes()
    if not image.startswith(b"MZ") or "RMACRO_TLS_V2".encode("utf-16le") not in image:
        raise ValueError("Выберите новый EternalCore.exe с поддержкой защищённого интернет-подключения.")
    filename, expected_hash = archive_for_platform()
    archive = STATE / filename
    if not archive.is_file() or sha256_file(archive) != expected_hash:
        print("Для HTTPS нужен Caddy %s (около 18 МБ) из официального GitHub caddyserver/caddy." % CADDY_VERSION)
        print("Архив проверяется по SHA-256; установка службы и изменение брандмауэра не выполняются.")
        answer = input("Скачать Caddy? [Y/N]: ").strip().lower()
        if answer not in ("y", "yes", "д", "да"):
            print("Отменено. Сервер и настройки не изменены.")
            return 1
        print("Загрузка и проверка Caddy...")
        try:
            download_archive(archive, filename, expected_hash)
        except (OSError, ValueError):
            print("Можно скачать архив вручную с " + CADDY_RELEASE + filename)
            print("Не распаковывая, положите его в " + str(archive) + " и снова запустите настройку.")
            print("Требуемый SHA-256: " + expected_hash)
            raise
    # Validate the archive before writing a new client or replacing settings.
    executable = STATE / "bin" / "caddy.exe"
    extract_verified_archive(archive, expected_hash, executable)
    print("Создание или проверка внутреннего сертификата...")
    root = provision_authority(executable, ip)
    digest = hashlib.sha256(root).hexdigest()
    destination = ROOT / "configured-client" / ("internet-" + uuid.uuid4().hex[:12]) / "EternalCore.exe"
    configure_loader(source, destination, "https://%s:%d" % (ip, PUBLIC_PORT), root)
    atomic_text(SETTINGS, json.dumps({"version": 2, "ipv4": ip, "ca_sha256": digest}, ensure_ascii=True, indent=2) + "\n")
    print("\nГотово. Настроенный EXE: " + str(destination))
    print("Раздайте эту копию в клиентском комплекте. Старые клиенты не знают новый сертификат.")
    print("Настройте порт 8765 и запустите START-INTERNET.bat.")
    print("Обязательно сохраните резервную копию data/internet-gateway вместе с копией базы.")
    print("Не раздавайте папку data: там база и закрытые ключи. Если они попадут в OneDrive, защитите облачную копию.")
    return 0


def read_settings():
    try:
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("Сначала запустите CONFIGURE-INTERNET.bat и настройте публичный IPv4.") from exc
    if (not isinstance(settings, dict) or set(settings) != {"version", "ipv4", "ca_sha256"} or
            settings["version"] != 2 or not isinstance(settings["ca_sha256"], str) or
            not re.fullmatch(r"[0-9a-f]{64}", settings["ca_sha256"])):
        raise ValueError("Сначала запустите новую CONFIGURE-INTERNET.bat и сохраните резервную копию.")
    return public_ipv4(settings["ipv4"]), settings["ca_sha256"]


def serve(database_type, server_type, db_path):
    ip, expected = read_settings()
    restrict_authority()
    load_authority(expected)
    filename, expected_hash = archive_for_platform()
    executable = STATE / "bin" / "caddy.exe"
    extract_verified_archive(STATE / filename, expected_hash, executable)
    database = database_type(db_path)
    if not database.has_admin():
        raise ValueError("Сначала запустите SETUP-ADMIN.bat и создайте администратора.")
    atomic_text(CONFIG, caddyfile(ip))
    # All requests from the gateway originate on loopback. Caddy overwrites the
    # special client-IP header so failed-login limits still distinguish peers.
    httpd = server_type(("127.0.0.1", BACKEND_PORT), database,
                        ["localhost", "127.0.0.1", "::1", ip],
                        lan_http_only=True, trusted_local_gateway=True)
    worker = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.3}, daemon=True)
    process = None
    try:
        worker.start()
        print("Локальная админ-панель (только на серверном ПК): http://127.0.0.1:%d/admin/" % BACKEND_PORT, flush=True)
        print("HTTPS для клиентов: https://%s:%d  |  только настроенные клиенты доверяют сертификату" % (ip, PUBLIC_PORT), flush=True)
        print("Держите это окно открытым. Порт 80 и Let's Encrypt не используются.", flush=True)
        print("Проверьте вход с настроенным EXE из ДРУГОЙ сети; браузер не доверяет внутреннему сертификату.", flush=True)
        process = subprocess.Popen([str(executable), "run", "--config", str(CONFIG), "--adapter", "caddyfile"],
                                   cwd=str(ROOT), env=caddy_environment())
        code = process.wait()
        if code:
            print("Шлюз остановился с ошибкой. Проверьте сообщения выше и свободен ли TCP 8765.", flush=True)
        return code
    except KeyboardInterrupt:
        print("\nОстановка интернет-сервера...", flush=True)
        return 0
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if worker.is_alive():
            httpd.shutdown()
            worker.join(timeout=5)
        httpd.server_close()
