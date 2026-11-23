"""Optional, owner-operated HTTPS gateway for an IPv4 address.

The Python application remains bound to loopback. Caddy terminates public TLS
and forwards only the loader's exact API routes. The production Caddy archive
is downloaded from its official GitHub release and checked against a pinned
SHA-256 before any executable is extracted or run. No service, firewall,
router, account, database, or operating-system trust store is changed here.
"""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import shutil
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
CHALLENGE_PORT = 80
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


def caddyfile(ip, public_port=PUBLIC_PORT, backend_port=BACKEND_PORT, challenge_port=CHALLENGE_PORT,
              test_certificate=None):
    """Build the gateway config. test_certificate is used by local tests only."""
    ip = str(ipaddress.IPv4Address(ip))
    for port in (public_port, backend_port, challenge_port):
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("Некорректный порт шлюза.")
    if test_certificate is None:
        tls = ("    tls {\n"
               "        issuer acme https://acme-v02.api.letsencrypt.org/directory {\n"
               "            profile shortlived\n"
               "            disable_tlsalpn_challenge\n"
               "        }\n"
               "    }\n")
    else:
        # Test harness uses an ephemeral certificate and trust store. This is
        # never accepted from settings.json or used by the production launcher.
        cert, key = test_certificate
        tls = "    tls %s %s\n" % (json.dumps(str(cert)), json.dumps(str(key)))
    return ("{\n"
            "    admin off\n"
            "    auto_https disable_redirects\n"
            "    default_sni " + ip + "\n"
            "    http_port " + str(challenge_port) + "\n"
            "}\n\n"
            "http://:" + str(challenge_port) + " {\n"
            "    respond \"Not found\" 404\n"
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


def setup(configure_loader):
    print("HTTPS через публичный IPv4: серверная база и настройки Windows не меняются.")
    print("Нужны открытые TCP 80 (сертификат) и 8765 (HTTPS), направленные на этот ПК.")
    print("Админ-панель при таком запуске доступна только на серверном ПК.")
    ip = public_ipv4(input("Публичный IPv4 сервера (без порта): "))
    source = input("Путь к распакованному EternalCore.exe нового клиентского архива: ").strip().strip('"')
    if not source or not Path(source).expanduser().is_file():
        raise ValueError("Укажите существующий EternalCore.exe из распакованного клиентского архива.")
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
    destination = ROOT / "configured-client" / ("internet-" + uuid.uuid4().hex[:12]) / "EternalCore.exe"
    configure_loader(source, destination, "https://%s:%d" % (ip, PUBLIC_PORT))
    atomic_text(SETTINGS, json.dumps({"version": 1, "ipv4": ip}, ensure_ascii=True, indent=2) + "\n")
    print("\nГотово. Настроенный EXE: " + str(destination))
    print("Замените им EternalCore.exe в КОПИИ нового клиентского архива; остальные файлы архива сохраните.")
    print("Остановите старый сервер, настройте порты и запустите START-INTERNET.bat.")
    print("Не раздавайте папку data: там база, сертификат и закрытый ключ.")
    return 0


def read_settings():
    try:
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("Сначала запустите CONFIGURE-INTERNET.bat и настройте публичный IPv4.") from exc
    if not isinstance(settings, dict) or set(settings) != {"version", "ipv4"} or settings["version"] != 1:
        raise ValueError("Настройки интернет-шлюза повреждены. Запустите CONFIGURE-INTERNET.bat снова.")
    return public_ipv4(settings["ipv4"])


def serve(database_type, server_type, db_path):
    ip = read_settings()
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
        environment = os.environ.copy()
        environment["XDG_DATA_HOME"] = str(STATE / "caddy-data")
        environment["XDG_CONFIG_HOME"] = str(STATE / "caddy-config")
        print("Локальная админ-панель (только на серверном ПК): http://127.0.0.1:%d/admin/" % BACKEND_PORT, flush=True)
        print("HTTPS для клиентов: https://%s:%d  |  проверка: /api/health" % (ip, PUBLIC_PORT), flush=True)
        print("Держите это окно открытым. Caddy должен получить и регулярно обновлять сертификат.", flush=True)
        print("Проверяйте /api/health с ДРУГОЙ сети; не отправляйте пароли для диагностики.", flush=True)
        process = subprocess.Popen([str(executable), "run", "--config", str(CONFIG), "--adapter", "caddyfile"],
                                   cwd=str(ROOT), env=environment)
        code = process.wait()
        if code:
            print("Шлюз остановился с ошибкой. Проверьте сообщения выше и свободны ли TCP 80 и 8765.", flush=True)
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
