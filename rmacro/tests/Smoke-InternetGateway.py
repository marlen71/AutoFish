"""End-to-end loopback TLS gateway test with ephemeral fixture credentials.

Requires Caddy and OpenSSL supplied by the test runner. The certificate is
self-signed for this local fixture only; production always uses trusted ACME.
With --dotnet-runner on a disposable GitHub Windows runner, temporarily trust
the test cert in the machine root store, run the unmodified .NET API client,
and remove that exact certificate in finally. Never run this on an owner PC.
"""
import argparse
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def run(command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def request(opener, base, path, body=None, headers=None):
    data = None
    headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers)
    try:
        with opener.open(req, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def check_windows_client(runner, base, cert, openssl, directory, configured):
    if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Windows"
            or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"):
        raise RuntimeError("The machine-wide test certificate may be used only on disposable GitHub Windows runners.")
    print("Checking .NET TLS validation with an untrusted fixture certificate...", flush=True)
    run([runner, base, "untrusted", str(configured)])
    der = directory / "fixture.cer"
    run([openssl, "x509", "-in", str(cert), "-outform", "DER", "-out", str(der)], capture_output=True)
    ps1 = directory / "temporary-trust.ps1"
    ps1.write_text(r'''param([string]$CertFile, [string]$Runner, [string]$Base, [string]$Configured)
$ErrorActionPreference = 'Stop'
# Only the disposable GitHub-hosted VM may trust this uniquely generated cert.
# CurrentUser Root requires a UI prompt on hosted Windows runners.
$candidate = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($CertFile)
$thumb = $candidate.Thumbprint
$path = 'Cert:\LocalMachine\Root\' + $thumb
if (Test-Path -LiteralPath $path) { throw 'Unexpected pre-existing fixture certificate; refusing to remove it.' }
$attempted = $false
$testExit = 1
try {
    $attempted = $true
    $item = Import-Certificate -FilePath $CertFile -CertStoreLocation 'Cert:\LocalMachine\Root' -ErrorAction Stop
    if (-not $item -or $item.Thumbprint -ne $thumb -or -not (Test-Path -LiteralPath $path)) {
        throw 'Could not add the exact temporary CI test certificate.'
    }
    & $Runner $Base 'trusted' $Configured
    $testExit = $LASTEXITCODE
}
finally {
    if ($attempted -and (Test-Path -LiteralPath $path)) { Remove-Item -LiteralPath $path -Force -ErrorAction Stop }
    if (Test-Path -LiteralPath $path) { throw 'Temporary CI test certificate cleanup failed.' }
}
exit $testExit
''', encoding="utf-8")
    print("Checking .NET login with a temporarily trusted fixture certificate...", flush=True)
    run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(ps1),
         str(der), runner, base, str(configured)])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--caddy", required=True)
    parser.add_argument("--openssl", default="openssl")
    parser.add_argument("--dotnet-runner")
    parser.add_argument("--loader")
    args = parser.parse_args()
    gateway = load("gateway_smoke", ROOT / "server" / "internet_gateway.py")
    srv = load("gateway_smoke_server", ROOT / "server" / "server.py")
    with tempfile.TemporaryDirectory(prefix="eternal-https-test-") as temp:
        directory = Path(temp)
        cert, key = directory / "cert.pem", directory / "key.pem"
        run([args.openssl, "req", "-x509", "-newkey", "rsa:2048", "-sha256", "-nodes", "-days", "1",
             "-keyout", str(key), "-out", str(cert), "-subj", "/CN=127.0.0.1",
             "-addext", "subjectAltName=IP:127.0.0.1", "-addext", "basicConstraints=critical,CA:TRUE",
             "-addext", "keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign",
             "-addext", "extendedKeyUsage=serverAuth"], capture_output=True)
        production = directory / "Production-Caddyfile"
        production.write_text(gateway.caddyfile("8.8.8.8"), encoding="utf-8")
        run([args.caddy, "validate", "--config", str(production), "--adapter", "caddyfile"], capture_output=True)
        adapted = run([args.caddy, "adapt", "--config", str(production), "--adapter", "caddyfile"],
                      capture_output=True).stdout
        parsed = json.loads(adapted)
        policies = parsed["apps"]["tls"]["automation"]["policies"]
        issuers = [issuer for policy in policies for issuer in policy.get("issuers", [])]
        assert any(i.get("module") == "acme" and i.get("profile") == "shortlived" for i in issuers), issuers
        assert not any(i.get("module") == "internal" for i in issuers), issuers

        db = srv.Database(directory / "fixture.db")
        db.init_admin("fixture_admin", "fixture-admin-password")
        user = db.create_user("fixture_admin", "fixture_user", "fixture-user-password")
        db.change_user("fixture_admin", user["uid"], "grant", {"product": "rmfish", "seconds": 3600})
        httpd = srv.Server(("127.0.0.1", 0), db, ["127.0.0.1", "localhost"],
                           lan_http_only=True, trusted_local_gateway=True)
        thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
        thread.start()
        port, challenge = free_port(), free_port()
        while challenge == port:
            challenge = free_port()
        config = directory / "Caddyfile"
        config.write_text(gateway.caddyfile("127.0.0.1", port, httpd.server_address[1], challenge,
                                           test_certificate=(cert, key)), encoding="utf-8")
        run([args.caddy, "validate", "--config", str(config), "--adapter", "caddyfile"], capture_output=True)
        environment = os.environ.copy()
        environment["XDG_DATA_HOME"] = str(directory / "caddy-data")
        environment["XDG_CONFIG_HOME"] = str(directory / "caddy-config")
        process = None
        logs = directory / "caddy.log"
        try:
            with logs.open("wb") as output:
                process = subprocess.Popen([args.caddy, "run", "--config", str(config), "--adapter", "caddyfile"],
                                           stdout=output, stderr=subprocess.STDOUT, env=environment)
                context = ssl.create_default_context(cafile=str(cert))
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
                base = "https://127.0.0.1:%d" % port
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("Caddy exited before starting: " + logs.read_text(errors="replace"))
                    try:
                        status, data = request(opener, base, "/api/health")
                        if status == 200 and json.loads(data)["ok"]:
                            break
                    except (urllib.error.URLError, OSError):
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Caddy did not become ready: " + logs.read_text(errors="replace"))

                # A self-signed fixture must fail default certificate validation.
                untrusted = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
                try:
                    request(untrusted, base, "/api/health")
                except urllib.error.URLError as exc:
                    assert isinstance(exc.reason, ssl.SSLError), repr(exc)
                else:
                    raise AssertionError("Untrusted certificate was accepted")
                if args.dotnet_runner:
                    if not args.loader:
                        raise ValueError("--loader is required with --dotnet-runner")
                    configured = directory / "configured" / "EternalCore.exe"
                    srv.configure_loader(args.loader, configured, base)
                    check_windows_client(args.dotnet_runner, base, cert, args.openssl, directory, configured)

                # Never forward plaintext API requests, admin pages, or admin API.
                plain = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                assert request(plain, "http://127.0.0.1:%d" % challenge, "/api/health")[0] == 404
                for path in ("/", "/admin", "/admin/", "/admin/app.js", "/api/admin/users", "/api/unknown",
                             "/%61dmin/", "/api/%61dmin/users", "/api/me/../admin/users", "/api/me%2f..%2fadmin/users"):
                    assert request(opener, base, path)[0] == 404, path
                assert request(opener, base, "/api/admin/login", {"username": "x", "password": "y"})[0] == 404
                local = "http://127.0.0.1:%d" % httpd.server_address[1]
                assert request(plain, local, "/admin/")[0] == 200

                device = "a" * 64
                status, data = request(opener, base, "/api/login", {"username": "fixture_user",
                    "password": "fixture-user-password", "device": device})
                assert status == 200, (status, data)
                token = json.loads(data)["token"]
                headers = {"Authorization": "Bearer " + token, "X-RMacro-Device": device}
                status, data = request(opener, base, "/api/me", headers=headers)
                assert status == 200 and json.loads(data)["user"]["username"] == "fixture_user"
                assert request(opener, base, "/api/authorize", {"product": "rmfish"}, headers)[0] == 200
                assert request(opener, base, "/api/logout", {}, headers)[0] == 200

                # Spoofed forwarded headers cannot turn each guess into a new IP.
                for index in range(8):
                    forged = {"X-EternalCore-Client-IP": "8.8.8.%d" % (index + 1),
                              "X-Forwarded-For": "1.1.1.%d" % (index + 1)}
                    status, _ = request(opener, base, "/api/login", {"username": "fixture_user",
                        "password": "wrong-password", "device": device}, forged)
                    assert status == 401, (index, status)
                status, _ = request(opener, base, "/api/login", {"username": "fixture_user",
                    "password": "wrong-password", "device": device}, {"X-EternalCore-Client-IP": "9.9.9.9"})
                assert status == 429, status
                assert ("user", "127.0.0.1") in httpd.limiter.failures, httpd.limiter.failures
                assert not any(key[1].startswith("8.8.8.") for key in httpd.limiter.failures), httpd.limiter.failures
                print("PASS: validated IP ACME config, local HTTPS login, trusted/untrusted TLS, admin isolation, "
                      "plaintext denial, and spoof-resistant per-client rate limit. No real ACME or router tested.", flush=True)
        except Exception:
            if logs.exists():
                print("Caddy fixture log:\n" + logs.read_text(errors="replace"), file=sys.stderr, flush=True)
            raise
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
