"""Unit tests for the optional HTTPS gateway; no public IP or certificate is used."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import zipfile

SERVER_ROOT = Path(__file__).resolve().parents[1] / "server"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SERVER_ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gateway = load("internet_gateway_test", "internet_gateway.py")
server = load("internet_gateway_server_test", "server.py")


def make_archive(path, names=("caddy.exe",)):
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, b"verified-test-executable")
    return hashlib.sha256(path.read_bytes()).hexdigest()


class InternetGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = self.root / "data" / "internet-gateway"
        self.patchers = [mock.patch.object(gateway, "ROOT", self.root), mock.patch.object(gateway, "STATE", self.state),
                         mock.patch.object(gateway, "SETTINGS", self.state / "settings.json"),
                         mock.patch.object(gateway, "CONFIG", self.state / "Caddyfile")]
        for item in self.patchers:
            item.start()

    def tearDown(self):
        for item in reversed(self.patchers):
            item.stop()
        self.temp.cleanup()

    def test_public_ipv4_and_settings_are_strict(self):
        self.assertEqual(gateway.public_ipv4(" 8.8.8.8 "), "8.8.8.8")
        for value in ("", "127.0.0.1", "192.168.0.105", "10.1.2.3", "0.0.0.0", "224.0.0.1",
                      "8.8.8.8:8765", "https://8.8.8.8", "8.8.8.8\n{malicious}", "::1", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                gateway.public_ipv4(value)
        with self.assertRaises(ValueError):
            gateway.read_settings()
        gateway.atomic_text(gateway.SETTINGS, '{"version":1,"ipv4":"8.8.8.8"}\n')
        self.assertEqual(gateway.read_settings(), "8.8.8.8")
        for text in ('{}', '{"version":2,"ipv4":"8.8.8.8"}',
                     '{"version":1,"ipv4":"127.0.0.1"}',
                     '{"version":1,"ipv4":"8.8.8.8","extra":true}', 'broken'):
            gateway.atomic_text(gateway.SETTINGS, text)
            with self.assertRaises(ValueError):
                gateway.read_settings()

    def test_configuration_is_tls_only_and_exposes_only_loader_paths(self):
        text = gateway.caddyfile("8.8.8.8")
        self.assertIn("default_sni 8.8.8.8", text)
        self.assertIn("https://8.8.8.8:8765", text)
        self.assertIn("profile shortlived", text)
        self.assertIn("disable_tlsalpn_challenge", text)
        self.assertIn("reverse_proxy 127.0.0.1:18765", text)
        self.assertIn("header_up X-EternalCore-Client-IP {remote_host}", text)
        self.assertIn("transport http {\n                keepalive off", text)
        self.assertIn('http://:80 {\n    respond "Not found" 404\n}', text)
        self.assertIn("@client_api path " + " ".join(gateway.CLIENT_PATHS), text)
        self.assertNotIn("/api/admin", text)
        self.assertNotIn("/admin", text)
        self.assertIn('handle {\n        respond "Not found" 404', text)
        for port in (0, 65536, -1):
            with self.assertRaises(ValueError):
                gateway.caddyfile("8.8.8.8", public_port=port)
        with self.assertRaises(ValueError):
            gateway.caddyfile("8.8.8.8\nmalicious")
        test = gateway.caddyfile("127.0.0.1", 9001, 9002, 9003, ("test-cert", "test-key"))
        self.assertIn('tls "test-cert" "test-key"', test)
        self.assertNotIn("profile shortlived", test)

    def test_only_verified_zip_entry_is_extracted_and_no_existing_file_is_lost(self):
        archive, executable = self.root / "source.zip", self.root / "bin" / "caddy.exe"
        digest = make_archive(archive, ("caddy.exe", "../outside.txt"))
        gateway.extract_verified_archive(archive, digest, executable)
        self.assertEqual(executable.read_bytes(), b"verified-test-executable")
        self.assertFalse((self.root / "outside.txt").exists())
        with self.assertRaises(ValueError):
            gateway.extract_verified_archive(archive, "0" * 64, executable)
        self.assertEqual(executable.read_bytes(), b"verified-test-executable")
        digest = make_archive(archive, ("nested/caddy.exe",))
        with self.assertRaises(ValueError):
            gateway.extract_verified_archive(archive, digest, executable)
        self.assertEqual(executable.read_bytes(), b"verified-test-executable")
        archive.write_bytes(b"not a ZIP")
        with self.assertRaises(ValueError):
            gateway.extract_verified_archive(archive, hashlib.sha256(b"not a ZIP").hexdigest(), executable)

    def test_download_hash_and_https_are_checked_before_replacing_archive(self):
        destination = self.state / "release.zip"
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"old")

        class Response(io.BytesIO):
            def __init__(self, body, url):
                super().__init__(body)
                self.headers = {"Content-Length": str(len(body))}
                self.url = url
            def geturl(self):
                return self.url

        payload = b"valid pinned archive"
        digest = hashlib.sha256(payload).hexdigest()
        with mock.patch.object(gateway.urllib.request, "urlopen", return_value=Response(payload, "https://example.invalid/a")):
            with self.assertRaises(ValueError):
                gateway.download_archive(destination, "release.zip", "0" * 64)
        self.assertEqual(destination.read_bytes(), b"old")
        with mock.patch.object(gateway.urllib.request, "urlopen", return_value=Response(payload, "http://example.invalid/a")):
            with self.assertRaises(ValueError):
                gateway.download_archive(destination, "release.zip", digest)
        self.assertEqual(destination.read_bytes(), b"old")
        with mock.patch.object(gateway.urllib.request, "urlopen", return_value=Response(payload, "https://example.invalid/a")):
            gateway.download_archive(destination, "release.zip", digest)
        self.assertEqual(destination.read_bytes(), payload)
        self.assertFalse(list(destination.parent.glob(".caddy-*")))

    def test_setup_generates_new_client_without_overwriting_database_or_original(self):
        self.state.mkdir(parents=True)
        archive = self.state / "verified.zip"
        digest = make_archive(archive)
        original = self.root / "EternalCore.exe"
        contents = b"MZ" + server.LOADER_CONFIG_MAGIC.decode("ascii").encode("utf-16le") + b"test"
        original.write_bytes(contents)
        db = self.root / "data" / "rmacro.db"
        db.write_bytes(b"existing database, untouched")
        answers = iter(("8.8.8.8", str(original)))
        with mock.patch.object(gateway, "archive_for_platform", return_value=(archive.name, digest)), \
                mock.patch("builtins.input", side_effect=lambda prompt: next(answers)), \
                mock.patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(gateway.setup(server.configure_loader), 0)
        self.assertEqual(original.read_bytes(), contents)
        self.assertEqual(db.read_bytes(), b"existing database, untouched")
        outputs = list((self.root / "configured-client").glob("internet-*/EternalCore.exe"))
        self.assertEqual(len(outputs), 1)
        data = outputs[0].read_bytes()
        marker = server.LOADER_CONFIG_MAGIC
        self.assertTrue(data.endswith(marker))
        size = struct.unpack("<I", data[-len(marker)-4:-len(marker)])[0]
        self.assertEqual(data[-len(marker)-4-size:-len(marker)-4], b"https://8.8.8.8:8765")
        self.assertEqual(gateway.read_settings(), "8.8.8.8")
        self.assertEqual((self.state / "bin" / "caddy.exe").read_bytes(), b"verified-test-executable")

    def test_start_uses_loopback_database_and_pinned_gateway_then_closes_cleanly(self):
        import threading
        self.state.mkdir(parents=True)
        gateway.atomic_text(gateway.SETTINGS, '{"version":1,"ipv4":"8.8.8.8"}\n')
        archive = self.state / "verified.zip"
        digest = make_archive(archive)
        instances = []

        class Database:
            def __init__(self, path):
                self.path = path
            def has_admin(self):
                return True

        class LocalServer:
            def __init__(self, address, database, allowed, **options):
                self.address, self.database, self.allowed, self.options = address, database, allowed, options
                self.stopped = threading.Event()
                self.closed = False
                instances.append(self)
            def serve_forever(self, poll_interval):
                self.stopped.wait(10)
            def shutdown(self):
                self.stopped.set()
            def server_close(self):
                self.closed = True

        child = mock.Mock()
        child.wait.return_value = 0
        child.poll.return_value = 0
        with mock.patch.object(gateway, "archive_for_platform", return_value=(archive.name, digest)), \
                mock.patch.object(gateway.subprocess, "Popen", return_value=child) as popen, \
                mock.patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(gateway.serve(Database, LocalServer, "existing-db"), 0)
        local = instances[0]
        self.assertEqual(local.address, ("127.0.0.1", 18765))
        self.assertEqual(local.database.path, "existing-db")
        self.assertTrue(local.options["lan_http_only"] and local.options["trusted_local_gateway"])
        self.assertIn("8.8.8.8", local.allowed)
        self.assertTrue(local.closed and local.stopped.is_set())
        command = popen.call_args.args[0]
        self.assertEqual(command[:2], [str(self.state / "bin" / "caddy.exe"), "run"])
        self.assertIn(str(gateway.CONFIG), command)
        self.assertEqual(popen.call_args.kwargs["env"]["XDG_DATA_HOME"], str(self.state / "caddy-data"))
        self.assertIn("https://8.8.8.8:8765", gateway.CONFIG.read_text(encoding="utf-8"))

    def test_cancel_or_bad_client_does_not_change_previous_settings(self):
        self.state.mkdir(parents=True)
        gateway.atomic_text(gateway.SETTINGS, '{"version":1,"ipv4":"8.8.8.8"}\n')
        original = self.root / "not-loader.exe"
        original.write_bytes(b"not a loader")
        archive = self.state / "verified.zip"
        digest = make_archive(archive)
        answers = iter(("1.1.1.1", str(original)))
        with mock.patch.object(gateway, "archive_for_platform", return_value=(archive.name, digest)), \
                mock.patch("builtins.input", side_effect=lambda prompt: next(answers)), \
                mock.patch("sys.stdout", new_callable=io.StringIO), \
                self.assertRaises(ValueError):
            gateway.setup(server.configure_loader)
        self.assertEqual(gateway.read_settings(), "8.8.8.8")
        archive.unlink()
        answers = iter(("1.1.1.1", str(original), "n"))
        with mock.patch.object(gateway, "archive_for_platform", return_value=(archive.name, digest)), \
                mock.patch("builtins.input", side_effect=lambda prompt: next(answers)), \
                mock.patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(gateway.setup(server.configure_loader), 1)
        self.assertEqual(gateway.read_settings(), "8.8.8.8")


if __name__ == "__main__":
    unittest.main()
