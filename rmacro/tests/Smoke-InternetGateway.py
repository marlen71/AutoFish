"""End-to-end, loopback-only test of the real internal-CA gateway.

Caddy generates a unique temporary CA. No certificate is installed in the
Windows or operating-system trust store. This does not test a real router.
"""
import argparse
import contextlib
import datetime
import hashlib
import http.client
import http.server
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


def request(opener, base, path, body=None, headers=None, method=None):
    data = None
    headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with opener.open(req, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def expect_authority_failure(gateway, caddy):
    try:
        gateway.provision_authority(caddy, "127.0.0.1")
    except ValueError:
        return
    raise AssertionError("Damaged or replaced authority was silently accepted")


@contextlib.contextmanager
def fake_tls_server(openssl, directory, ca_dir, mode):
    """A real TLS listener whose leaf is expired or lacks the server-auth EKU."""
    folder = directory / ("invalid-" + mode)
    folder.mkdir()
    key, csr, cert = folder / "key.pem", folder / "request.pem", folder / "leaf.pem"
    ext = folder / "extensions.txt"
    eku = "serverAuth" if mode == "expired" else "clientAuth"
    ext.write_text("basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
                   "subjectAltName=IP:127.0.0.1\nextendedKeyUsage=" + eku + "\n", encoding="ascii")
    run([openssl, "req", "-new", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=127.0.0.1",
         "-keyout", str(key), "-out", str(csr)], capture_output=True)
    if mode == "expired":
        # OpenSSL builds differ on whether `x509 -days -1` is allowed. The
        # `ca` command supports explicit validity dates on both platforms.
        (folder / "index.txt").write_text("", encoding="ascii")
        (folder / "serial").write_text("01\n", encoding="ascii")
        config = folder / "ca.cnf"
        config.write_text("[ca]\ndefault_ca=local\n[local]\n" +
                          "database=\"" + (folder / "index.txt").as_posix() + "\"\n" +
                          "serial=\"" + (folder / "serial").as_posix() + "\"\n" +
                          "new_certs_dir=\"" + folder.as_posix() + "\"\n" +
                          "default_md=sha256\ndefault_days=1\npolicy=policy\n" +
                          "[policy]\ncommonName=supplied\n[leaf]\n" + ext.read_text(encoding="ascii"), encoding="ascii")
        now = datetime.datetime.now(datetime.timezone.utc)
        start = (now - datetime.timedelta(hours=2)).strftime("%Y%m%d%H%M%SZ")
        end = (now - datetime.timedelta(hours=1)).strftime("%Y%m%d%H%M%SZ")
        command = [openssl, "ca", "-config", str(config), "-batch", "-notext", "-extensions", "leaf",
                   "-cert", str(ca_dir / "intermediate.crt"), "-keyfile", str(ca_dir / "intermediate.key"),
                   "-in", str(csr), "-startdate", start, "-enddate", end, "-out", str(cert)]
    else:
        command = [openssl, "x509", "-req", "-in", str(csr), "-CA", str(ca_dir / "intermediate.crt"),
                   "-CAkey", str(ca_dir / "intermediate.key"), "-set_serial", "1234", "-days", "1",
                   "-sha256", "-extfile", str(ext), "-out", str(cert)]
    try:
        run(command, capture_output=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("Could not generate the invalid TLS fixture: " + exc.stderr.decode(errors="replace")) from exc
    chain = folder / "chain.pem"
    chain.write_bytes(cert.read_bytes() + (ca_dir / "intermediate.crt").read_bytes())
    accepted = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            accepted.set()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        def log_message(self, *args):
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(chain), str(key))
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    thread.start()
    try:
        yield "https://127.0.0.1:%d" % httpd.server_address[1], accepted
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--caddy", required=True)
    parser.add_argument("--openssl", default="openssl")
    parser.add_argument("--dotnet-runner")
    parser.add_argument("--loader")
    args = parser.parse_args()
    if args.dotnet_runner and not args.loader:
        raise ValueError("--loader is required with --dotnet-runner")
    gateway = load("gateway_smoke", ROOT / "server" / "internet_gateway.py")
    srv = load("gateway_smoke_server", ROOT / "server" / "server.py")
    with tempfile.TemporaryDirectory(prefix="eternal-https-test-") as temp:
        directory = Path(temp)
        gateway.ROOT = directory
        gateway.STATE = directory / "state"
        gateway.SETTINGS = gateway.STATE / "settings.json"
        gateway.CONFIG = gateway.STATE / "Caddyfile"
        caddy = str(Path(args.caddy).resolve())

        print("Provisioning the private CA and verifying stable reuse...", flush=True)
        root = gateway.provision_authority(caddy, "127.0.0.1")
        ca_dir = gateway.authority_directory()
        root_pem, root_key = ca_dir / "root.crt", ca_dir / "root.key"
        root_digest = hashlib.sha256(root).hexdigest()
        gateway.atomic_text(gateway.SETTINGS, json.dumps({"version": 2, "ipv4": "8.8.8.8", "ca_sha256": root_digest}))
        assert gateway.provision_authority(caddy, "127.0.0.1") == root
        key_bytes = root_key.read_bytes()
        root_key.unlink()
        expect_authority_failure(gateway, caddy)
        assert not root_key.exists(), "Missing root key was silently recreated"
        root_key.write_bytes(key_bytes)
        root_key.write_bytes(b"invalid private key")
        expect_authority_failure(gateway, caddy)
        root_key.write_bytes(key_bytes)
        record = gateway.authority_record_path()
        record_bytes = record.read_bytes()
        record.unlink()
        expect_authority_failure(gateway, caddy)
        record.write_bytes(record_bytes)
        gateway.atomic_text(gateway.SETTINGS, json.dumps({"version": 2, "ipv4": "8.8.8.8", "ca_sha256": "0" * 64}))
        expect_authority_failure(gateway, caddy)
        gateway.atomic_text(gateway.SETTINGS, json.dumps({"version": 2, "ipv4": "8.8.8.8", "ca_sha256": root_digest}))
        assert gateway.provision_authority(caddy, "127.0.0.1") == root
        if os.name != "nt":
            assert (root_key.stat().st_mode & 0o077) == 0
            assert ((gateway.STATE / "caddy-data").stat().st_mode & 0o077) == 0

        # A separate real CA must never be treated as the configured root.
        original_state, original_settings, original_config = gateway.STATE, gateway.SETTINGS, gateway.CONFIG
        gateway.STATE = directory / "other-state"
        gateway.SETTINGS, gateway.CONFIG = gateway.STATE / "settings.json", gateway.STATE / "Caddyfile"
        other_root = gateway.provision_authority(caddy, "127.0.0.1")
        assert other_root != root
        gateway.STATE, gateway.SETTINGS, gateway.CONFIG = original_state, original_settings, original_config
        old_root = root_pem.read_bytes()
        root_pem.write_text(ssl.DER_cert_to_PEM_cert(other_root), encoding="ascii")
        expect_authority_failure(gateway, caddy)
        root_pem.write_bytes(old_root)
        assert gateway.load_authority(root_digest) == root

        production = directory / "Production-Caddyfile"
        production.write_text(gateway.caddyfile("8.8.8.8"), encoding="utf-8")
        adapted = run([caddy, "adapt", "--config", str(production), "--adapter", "caddyfile"],
                      capture_output=True).stdout
        parsed = json.loads(adapted)
        policies = parsed["apps"]["tls"]["automation"]["policies"]
        issuers = [issuer for policy in policies for issuer in policy.get("issuers", [])]
        assert any(i.get("module") == "internal" for i in issuers), issuers
        assert not any(i.get("module") == "acme" for i in issuers), issuers
        servers = parsed["apps"]["http"]["servers"]
        assert all(":80" not in server.get("listen", []) for server in servers.values()), servers

        db = srv.Database(directory / "fixture.db")
        db.init_admin("fixture_admin", "fixture-admin-password")
        user = db.create_user("fixture_admin", "fixture_user", "fixture-user-password")
        db.change_user("fixture_admin", user["uid"], "grant", {"product": "rmfish", "seconds": 3600})
        forwarded_admin_login = threading.Event()

        class FixtureHandler(srv.Handler):
            def handle_request(self):
                if self.path.split("?", 1)[0] == "/api/admin/login":
                    forwarded_admin_login.set()
                return super().handle_request()

        srv.Handler = FixtureHandler
        httpd = srv.Server(("127.0.0.1", 0), db, ["127.0.0.1", "localhost"],
                           lan_http_only=True, trusted_local_gateway=True)
        thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
        thread.start()
        port = free_port()
        config = directory / "Caddyfile"
        config.write_text(gateway.caddyfile("127.0.0.1", port, httpd.server_address[1]), encoding="utf-8")
        process = None
        logs = directory / "caddy.log"
        try:
            with logs.open("wb") as output:
                process = subprocess.Popen([caddy, "run", "--config", str(config), "--adapter", "caddyfile"],
                                           stdout=output, stderr=subprocess.STDOUT, env=gateway.caddy_environment())
                context = ssl.create_default_context(cafile=str(root_pem))
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

                untrusted = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
                try:
                    request(untrusted, base, "/api/health")
                except urllib.error.URLError as exc:
                    assert isinstance(exc.reason, ssl.SSLError), repr(exc)
                else:
                    raise AssertionError("Unconfigured default trust accepted the private certificate")

                if args.dotnet_runner:
                    configured = directory / "configured" / "EternalCore.exe"
                    wrong = directory / "wrong" / "EternalCore.exe"
                    srv.configure_loader(args.loader, configured, base, root)
                    srv.configure_loader(args.loader, wrong, base, other_root)
                    print("Checking actual Windows API client, private trust and update staging...", flush=True)
                    run([args.dotnet_runner, base, "trusted", str(configured), str(wrong), args.loader])
                    wrong_name = "https://127.0.0.2:%d" % port
                    named = directory / "wrong-name" / "EternalCore.exe"
                    srv.configure_loader(args.loader, named, wrong_name, root)
                    run([args.dotnet_runner, wrong_name, "must-fail", str(named), str(wrong), args.loader])
                    for mode in ("expired", "wrong-eku"):
                        with fake_tls_server(args.openssl, directory, ca_dir, mode) as (invalid_base, accepted):
                            invalid = directory / ("configured-" + mode) / "EternalCore.exe"
                            srv.configure_loader(args.loader, invalid, invalid_base, root)
                            run([args.dotnet_runner, invalid_base, "must-fail", str(invalid), str(wrong), args.loader])
                            assert not accepted.is_set(), "Invalid TLS connection forwarded an HTTP request"

                print("Checking plaintext and administrator isolation...", flush=True)
                plain = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                try:
                    status, _ = request(plain, "http://127.0.0.1:%d" % port, "/api/health")
                    assert status != 200, ("plaintext health", status)
                except (urllib.error.URLError, OSError, http.client.RemoteDisconnected):
                    pass
                for path in ("/", "/admin", "/admin/", "/admin/app.js", "/api/admin/users", "/api/unknown",
                             "/%61dmin/", "/api/%61dmin/users", "/api/me/../admin/users", "/api/me%2f..%2fadmin/users"):
                    status, _ = request(opener, base, path)
                    assert status == 404, (path, status)
                status, _ = request(opener, base, "/api/admin/login", method="POST")
                assert status == 404, ("public admin login without body", status)
                try:
                    status, _ = request(opener, base, "/api/admin/login", {"username": "x", "password": "y"})
                except (http.client.RemoteDisconnected, ConnectionResetError):
                    print("Blocked admin POST was closed while discarding its body.", flush=True)
                else:
                    assert status == 404, ("public admin login with body", status)
                status, data = request(opener, base, "/api/health")
                assert status == 200 and json.loads(data)["ok"], ("gateway remains healthy", status)
                assert not forwarded_admin_login.wait(0.5), "The gateway forwarded public admin login."
                local = "http://127.0.0.1:%d" % httpd.server_address[1]
                status, _ = request(plain, local, "/admin/")
                assert status == 200, ("local admin", status)

                print("Checking Python client authentication...", flush=True)
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

                print("Checking spoof-resistant login limits...", flush=True)
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
                print("PASS: private CA provisioning/reuse, loopback HTTPS, isolated admin and rate limiting. "
                      "No real router or external port was tested.", flush=True)
        except Exception as exc:
            print("HTTPS fixture failure: %s: %s" % (type(exc).__name__, exc), file=sys.stderr, flush=True)
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
