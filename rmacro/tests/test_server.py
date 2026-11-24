"""HTTP and SQLite integration tests; no external packages or real credentials."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import urllib.error
import urllib.request
import uuid

SERVER_PATH = Path(__file__).resolve().parents[1] / "server" / "server.py"
spec = importlib.util.spec_from_file_location("rmacro_server", SERVER_PATH)
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)


class WindowsSourceEncodingTests(unittest.TestCase):
    def test_non_ascii_powershell_and_csharp_have_utf8_bom(self):
        # Windows PowerShell 5.1 and the legacy Framework compiler otherwise
        # decode UTF-8 Russian text using the machine's ANSI code page.
        root = SERVER_PATH.parents[2]
        paths = list(root.glob("*.ps1")) + list((root / "src").glob("*.cs"))
        paths += list((root / "rmacro").rglob("*.ps1")) + list((root / "rmacro").rglob("*.cs"))
        for path in paths:
            content = path.read_bytes()
            if any(byte >= 128 for byte in content):
                with self.subTest(path=str(path)):
                    self.assertTrue(content.startswith(b"\xef\xbb\xbf"), str(path))
                    content.decode("utf-8-sig")


class HandlerLoggingTests(unittest.TestCase):
    def test_idle_socket_timeout_before_request_does_not_raise(self):
        errors = []
        captured = io.StringIO()

        class QuickTimeoutHandler(srv.Handler):
            def setup(self):
                super().setup()
                self.connection.settimeout(0.1)

        client, connection = socket.socketpair()
        try:
            def run_handler():
                try:
                    QuickTimeoutHandler(connection, ("127.0.0.1", 12345), object())
                except Exception as exc:
                    errors.append(exc)
            worker = threading.Thread(target=run_handler, daemon=True)
            with contextlib.redirect_stderr(captured):
                worker.start()
                worker.join(3)
                self.assertFalse(worker.is_alive(), "Idle handler did not exit after the socket timeout")
            self.assertEqual(errors, [])
            self.assertIn("connection closed before a complete request", captured.getvalue())
        finally:
            client.close()
            connection.close()

    def test_logging_redacts_query_and_handles_malformed_target(self):
        handler = object.__new__(srv.Handler)
        handler.client_address = ("127.0.0.1", 12345)
        handler.command = "GET"
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            handler.path = "/api/health?token=example-secret"
            handler.log_message("unused")
            handler.path = "http://[malformed"
            handler.log_message("unused")
        self.assertIn("GET /api/health", captured.getvalue())
        self.assertIn("[invalid request path]", captured.getvalue())
        self.assertNotIn("example-secret", captured.getvalue())


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = srv.Database(Path(self.temp.name) / "private" / "test.db")
        self.assertFalse(self.db.has_admin())
        self.db.init_admin("owner", "administrator password")
        self.httpd = srv.Server(("127.0.0.1", 0), self.db)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:%s" % self.httpd.server_address[1]
        status, result, _ = self.request("/api/admin/login", {"username": "owner", "password": "administrator password"})
        self.assertEqual(status, 200)
        self.admin = result["token"]
        self.device_a, self.device_b = "a" * 64, "b" * 64

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(3)
        self.temp.cleanup()

    def request(self, path, body=None, token=None, device=None, extra_headers=None):
        headers = dict(extra_headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = "Bearer " + token
        if device:
            headers["X-RMacro-Device"] = device
        req = urllib.request.Request(self.base + path, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, json.loads(response.read()), response.headers
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read()), exc.headers

    def create(self, name="fisher", password="password-for-test"):
        status, data, _ = self.request("/api/admin/users", {"username": name, "password": password}, self.admin)
        self.assertEqual(status, 201, data)
        return data["uid"]

    def login(self, name="fisher", password="password-for-test", device=None):
        return self.request("/api/login", {"username": name, "password": password, "device": device or self.device_a})

    def admin_action(self, uid, action, body=None):
        return self.request("/api/admin/users/%s/%s" % (uid, action), body or {}, self.admin)

    def create_key(self, **overrides):
        body = {"product": "rmfish", "seconds": 3600, "activate_before": srv.unix_now() + 86400,
                "max_users": 1, "max_activations": 1, "max_per_user": 1}
        body.update(overrides)
        status, data, _ = self.request("/api/admin/keys", body, self.admin)
        self.assertEqual(status, 201, data)
        return data

    def redeem(self, token, value, request_id=None):
        return self.request("/api/me/activate-key", {"key": value, "request_id": request_id or uuid.uuid4().hex}, token, self.device_a)

    def test_subscription_hwid_reset_revoke_and_persistence(self):
        uid = self.create()
        self.assertEqual(self.create("fisher2"), uid + 1)
        status, login, _ = self.login()
        self.assertEqual(status, 200)
        token = login["token"]
        self.assertEqual(login["user"]["uid"], uid)
        self.assertFalse(login["products"][0]["active"])
        self.assertEqual(self.request("/api/authorize", {"product": "rmfish"}, token, self.device_a)[0], 403)
        status, first, _ = self.admin_action(uid, "grant", {"product": "rmfish", "seconds": 7200})
        self.assertEqual(status, 200)
        status, second, _ = self.admin_action(uid, "grant", {"product": "rmfish", "seconds": 86400})
        self.assertEqual(second["expires_at"] - first["expires_at"], 86400)
        status, allowed, _ = self.request("/api/authorize", {"product": "rmfish"}, token, self.device_a)
        self.assertEqual(status, 200)
        self.assertEqual(allowed["expires_at"], second["expires_at"])
        self.assertEqual(self.login(device=self.device_b)[1]["code"], "DEVICE_MISMATCH")
        self.assertEqual(self.request("/api/me", token=token, device=self.device_b)[0], 401)
        self.assertEqual(self.admin_action(uid, "reset-hwid")[0], 200)
        self.assertEqual(self.request("/api/me", token=token, device=self.device_a)[0], 401)
        status, login_b, _ = self.login(device=self.device_b)
        self.assertEqual(status, 200)
        self.assertEqual(self.login(device=self.device_a)[1]["code"], "DEVICE_MISMATCH")
        self.assertEqual(self.admin_action(uid, "revoke", {"product": "rmfish"})[0], 200)
        self.assertEqual(self.request("/api/authorize", {"product": "rmfish"}, login_b["token"], self.device_b)[0], 403)
        users = self.request("/api/admin/users?q=fisher", token=self.admin)[1]["users"]
        self.assertEqual(len(users), 2)
        self.assertEqual(self.request("/api/admin/users?q=%08d" % uid, token=self.admin)[1]["users"][0]["uid"], uid)
        self.assertTrue(any(u["uid"] == uid and u["hwid_bound"] for u in users))
        reopened = srv.Database(self.db.path)
        self.assertEqual(len(reopened.admin_users()["users"]), 3)  # two users plus linked admin
        self.assertEqual(reopened.user_info(uid)["user"]["username"], "fisher")
        backup = self.db.backup(Path(self.temp.name) / "backup.db")
        self.assertEqual(len(srv.Database(backup).admin_users()["users"]), 3)
        with self.assertRaises(ValueError):
            self.db.backup(backup)

    def test_admin_products_password_and_disable(self):
        uid = self.create()
        status, created, _ = self.request("/api/admin/products", {"code": "another", "name": "Другой продукт"}, self.admin)
        self.assertEqual(status, 201)
        self.assertEqual(created["code"], "another")
        self.assertEqual(self.admin_action(uid, "grant", {"product": "another", "seconds": 1800})[0], 200)
        status, user, _ = self.login()
        token = user["token"]
        self.assertEqual(len(user["products"]), 2)
        self.assertEqual(self.request("/api/admin/users", token=token)[0], 401)
        self.assertEqual(self.request("/api/me", token=self.admin, device=self.device_a)[0], 401)
        self.assertEqual(self.admin_action(uid, "password", {"password": "new-password"})[0], 200)
        self.assertEqual(self.request("/api/me", token=token, device=self.device_a)[0], 401)
        self.assertEqual(self.login()[0], 401)
        status, login, _ = self.login(password="new-password")
        self.assertEqual(status, 200)
        self.assertEqual(self.admin_action(uid, "status", {"enabled": False})[0], 200)
        self.assertEqual(self.request("/api/me", token=login["token"], device=self.device_a)[0], 401)
        self.assertEqual(self.login(password="new-password")[0], 401)
        self.assertEqual(self.admin_action(uid, "status", {"enabled": True})[0], 200)
        self.assertEqual(self.login(password="new-password")[0], 200)
        events = self.request("/api/admin/audit", token=self.admin)[1]["events"]
        self.assertTrue(any(e["action"] == "password" for e in events))
        self.assertNotIn("new-password", json.dumps(events))

    def test_games_products_and_subscriptions(self):
        uid = self.create()
        games = self.request("/api/admin/games", token=self.admin)[1]["games"]
        self.assertEqual(games[0]["code"], "gta5")
        self.assertEqual(self.request("/api/admin/games", {"code": "another-game", "name": "Другая игра"}, self.admin)[0], 201)
        self.assertEqual(self.request("/api/admin/games", {"code": "another-game", "name": "Дубль"}, self.admin)[0], 409)
        self.assertEqual(self.request("/api/admin/games", {"code": "BAD code", "name": "Ошибка"}, self.admin)[0], 400)
        self.assertEqual(self.request("/api/admin/products", {"code": "other", "name": "Другой макрос", "game_code": "missing"}, self.admin)[0], 404)
        status, created, _ = self.request("/api/admin/products", {"code": "other", "name": "Другой макрос", "game_code": "another-game"}, self.admin)
        self.assertEqual(status, 201)
        self.assertEqual(created["game_name"], "Другая игра")
        self.assertEqual(self.admin_action(uid, "grant", {"product": "other", "seconds": 3600})[0], 200)
        status, login, _ = self.login()
        self.assertEqual(status, 200)
        self.assertEqual({game["code"] for game in login["games"]}, {"gta5", "another-game"})
        self.assertEqual({p["code"]: p["game_code"] for p in login["products"]}, {"rmfish": "gta5", "other": "another-game"})
        self.assertTrue(next(p for p in login["products"] if p["code"] == "other")["active"])
        self.assertFalse(next(p for p in login["products"] if p["code"] == "rmfish")["active"])
        self.assertEqual(self.admin_action(uid, "revoke", {"product": "rmfish"})[0], 404)
        self.assertIsNone(next(p for p in self.db.user_info(uid)["products"] if p["code"] == "rmfish")["expires_at"])
        before = self.admin_action(uid, "grant", {"product": "other", "seconds": 7200})[1]["expires_at"]
        status, reset, _ = self.admin_action(uid, "set", {"product": "other", "seconds": 60})
        self.assertEqual(status, 200)
        self.assertGreater(before - reset["expires_at"], 7000)
        self.assertEqual(self.admin_action(uid, "set", {"product": "other", "seconds": -1})[0], 400)
        self.assertEqual(self.request("/api/authorize", {"product": "other"}, login["token"], self.device_a)[0], 200)
        self.assertEqual(self.request("/api/authorize", {"product": "rmfish"}, login["token"], self.device_a)[0], 403)
        self.assertEqual(self.request("/api/admin/products/other", {"name": "Переименован", "game_code": "gta5"}, self.admin)[0], 200)
        moved = next(p for p in self.request("/api/me", token=login["token"], device=self.device_a)[1]["products"] if p["code"] == "other")
        self.assertEqual((moved["name"], moved["game_code"], moved["active"]), ("Переименован", "gta5", True))
        self.assertEqual(self.request("/api/admin/products/other", {"name": "X", "game_code": "missing"}, self.admin)[0], 404)
        self.assertEqual(self.request("/api/admin/games")[0], 401)

    def test_manual_public_product_statuses_and_authorization_are_independent(self):
        uid = self.create()
        self.assertEqual(self.admin_action(uid, "grant", {"product": "rmfish", "seconds": 3600})[0], 200)
        token = self.login()[1]["token"]
        public = self.request("/api/status")[1]
        self.assertEqual(public, {"ok": True, "products": [{"code": "rmfish", "name": "RMFish",
                         "game_name": "GTA5 · RMRP", "status": "OUTDATED"}], "total_products": 1})
        for choice in srv.PRODUCT_STATUSES:
            body = {"name": "RMFish", "game_code": "gta5", "status": choice}
            self.assertEqual(self.request("/api/admin/products/rmfish", body)[0], 401)
            self.assertEqual(self.request("/api/admin/products/rmfish", body, self.admin)[0], 200)
            self.assertEqual(self.request("/api/status")[1]["products"][0]["status"], choice)
            self.assertEqual(self.request("/api/authorize", {"product": "rmfish"}, token, self.device_a)[0], 200)
        self.assertEqual(self.request("/api/admin/products/rmfish", {"name": "X", "game_code": "gta5", "status": "ONLINE"}, self.admin)[0], 400)
        # An old panel can edit a product without resetting its chosen status.
        self.assertEqual(self.request("/api/admin/products/rmfish", {"name": "RMFish", "game_code": "gta5", "status": "ON UPDATE"}, self.admin)[0], 200)
        self.assertEqual(self.request("/api/admin/products/rmfish", {"name": "Renamed", "game_code": "gta5"}, self.admin)[0], 200)
        self.assertEqual(self.request("/api/status")[1]["products"][0]["status"], "ON UPDATE")
        self.assertEqual(srv.Database(self.db.path).public_status()["products"][0]["name"], "Renamed")
        self.assertNotIn("fisher", json.dumps(self.request("/api/status")[1]))

    def test_public_status_reports_catalog_truncation(self):
        with self.db.connect() as db:
            for index in range(107):
                db.execute("INSERT INTO products(code,name,created_at,game_code,status) VALUES(?,?,?,?,?)",
                           ("test-%03d" % index, "Product %03d" % index, srv.unix_now(), "gta5", "OUTDATED"))
        status, public, _ = self.request("/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(len(public["products"]), 100)
        self.assertEqual(public["total_products"], 108)
        self.assertTrue(all(set(p) == {"code", "name", "game_name", "status"} for p in public["products"]))

    def test_concurrent_first_login_binds_only_one_device(self):
        self.create()
        barrier = threading.Barrier(2)
        results = []
        def worker(device):
            barrier.wait()
            results.append(self.login(device=device)[0])
        threads = [threading.Thread(target=worker, args=(d,)) for d in (self.device_a, self.device_b)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual(sorted(results), [200, 403])

    def test_concurrent_grants_do_not_lose_time(self):
        uid = self.create()
        barrier = threading.Barrier(6)
        results = []
        def worker():
            barrier.wait()
            results.append(self.admin_action(uid, "grant", {"product": "rmfish", "seconds": 3600}))
        threads = [threading.Thread(target=worker) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(len(results), 6)
        self.assertTrue(all(result[0] == 200 for result in results))
        expiries = sorted(result[1]["expires_at"] for result in results)
        self.assertEqual([expiries[i + 1] - expiries[i] for i in range(5)], [3600] * 5)
        self.assertEqual(self.db.user_info(uid)["products"][0]["expires_at"], expiries[-1])

    def test_validation_and_no_sensitive_storage(self):
        uid = self.create()
        status, login, _ = self.login()
        token = login["token"]
        self.assertEqual(status, 200)
        self.assertEqual(self.create("different"), uid + 1)
        self.assertEqual(self.request("/api/admin/users", {"username": "FISHER", "password": "12345678"}, self.admin)[0], 409)
        self.assertEqual(self.admin_action(uid, "grant", {"product": "rmfish", "seconds": -1})[0], 400)
        self.assertEqual(self.admin_action(uid, "grant", {"product": "missing", "seconds": 60})[0], 404)
        self.assertEqual(self.admin_action(uid, "status", {"enabled": 1})[0], 400)
        self.assertEqual(self.request("/api/me", token=token, device="invalid")[0], 401)
        self.assertEqual(self.login(password="bad\ud800password")[0], 401)
        self.assertEqual(self.admin_action(uid, "password", {"password":"bad\ud800password"})[0], 400)
        status, _, headers = self.request("/api/health", extra_headers={"Host": "attacker.example"})
        self.assertEqual(status, 400)
        self.assertEqual(headers.get("Connection", "").lower(), "close")
        status, _, headers = self.login(password="invalid-password")
        self.assertEqual(status, 401)
        self.assertEqual(headers.get("Connection", "").lower(), "close")
        self.assertNotIn("Access-Control-Allow-Origin", self.request("/api/health")[2])
        with self.db.connect() as db:
            row = db.execute("SELECT password_hash,salt,rounds FROM users WHERE uid=?", (uid,)).fetchone()
            self.assertNotEqual(bytes(row["password_hash"]), b"password-for-test")
            self.assertGreaterEqual(row["rounds"], 300000)
            session = db.execute("SELECT token_hash FROM sessions WHERE uid=?", (uid,)).fetchone()
            self.assertEqual(session["token_hash"], srv.token_hash(token))
            self.assertNotEqual(session["token_hash"], token)
        self.assertTrue(srv.loopback_bind("127.0.0.1"))
        self.assertFalse(srv.loopback_bind("0.0.0.0"))
        self.assertFalse(srv.loopback_bind("192.168.1.5"))

    def test_gateway_rate_limit_uses_only_explicitly_trusted_loopback_header(self):
        # Normal LAN/server mode ignores all client-supplied proxy headers.
        self.assertFalse(self.httpd.trusted_local_gateway)
        self.request("/api/login", {"username": "missing", "password": "bad", "device": self.device_a},
                     extra_headers={"X-EternalCore-Client-IP": "8.8.8.8"})
        self.assertIn(("user", "127.0.0.1"), self.httpd.limiter.failures)
        self.assertNotIn(("user", "8.8.8.8"), self.httpd.limiter.failures)
        # In gateway mode, only its overwritten, single valid IP is accepted.
        self.httpd.trusted_local_gateway = True
        self.request("/api/login", {"username": "missing", "password": "bad", "device": self.device_a},
                     extra_headers={"X-EternalCore-Client-IP": "8.8.8.8"})
        self.request("/api/login", {"username": "missing", "password": "bad", "device": self.device_a},
                     extra_headers={"X-EternalCore-Client-IP": "1.1.1.1"})
        self.request("/api/login", {"username": "missing", "password": "bad", "device": self.device_a},
                     extra_headers={"X-EternalCore-Client-IP": "8.8.8.8, 1.1.1.1"})
        self.assertIn(("user", "8.8.8.8"), self.httpd.limiter.failures)
        self.assertIn(("user", "1.1.1.1"), self.httpd.limiter.failures)
        self.assertEqual(len(self.httpd.limiter.failures[("user", "127.0.0.1")]), 2)
        with self.assertRaises(ValueError):
            srv.Server(("0.0.0.0", 0), self.db, trusted_local_gateway=True)
        with self.assertRaises(ValueError):
            srv.Server(("192.168.0.105", 0), self.db, trusted_local_gateway=True)

    def test_expired_tokens_and_subscriptions(self):
        uid = self.create()
        self.admin_action(uid, "grant", {"product": "rmfish", "seconds": 60})
        status, user, _ = self.login()
        token = user["token"]
        self.assertEqual(status, 200)
        with self.db.connect() as db:
            db.execute("UPDATE subscriptions SET expires_at=? WHERE uid=?", (srv.unix_now() - 1, uid))
        self.assertEqual(self.request("/api/authorize", {"product": "rmfish"}, token, self.device_a)[0], 403)
        self.assertFalse(self.request("/api/me", token=token, device=self.device_a)[1]["products"][0]["active"])
        with self.db.connect() as db:
            db.execute("UPDATE sessions SET expires_at=? WHERE uid=?", (srv.unix_now() - 1, uid))
        self.assertEqual(self.request("/api/me", token=token, device=self.device_a)[0], 401)

    def test_admin_uses_one_password_and_profile_change_revokes_other_sessions(self):
        status, owner, _ = self.login("owner", "administrator password")
        self.assertEqual(status, 200, owner)
        uid, token = owner["user"]["uid"], owner["token"]
        self.assertTrue(owner["user"]["is_admin"])
        self.assertEqual(owner["user"]["username"], "owner")
        self.assertFalse(any(p["active"] for p in owner["products"]))  # no automatic entitlement
        second = self.login("owner", "administrator password")[1]["token"]
        body = {"old_password": "wrong password", "new_password": "new secure admin password", "confirmation": "new secure admin password"}
        self.assertEqual(self.request("/api/me/password", body, token, self.device_a)[1]["code"], "WRONG_PASSWORD")
        body["old_password"] = "administrator password"
        body["confirmation"] = "different password"
        self.assertEqual(self.request("/api/me/password", body, token, self.device_a)[1]["code"], "PASSWORD_MISMATCH")
        body.update(new_password="short-pass", confirmation="short-pass")
        self.assertEqual(self.request("/api/me/password", body, token, self.device_a)[1]["code"], "BAD_PASSWORD")
        body.update(new_password="new secure admin password", confirmation="new secure admin password")
        self.assertEqual(self.request("/api/me/password", body, token, self.device_a)[0], 200)
        self.assertEqual(self.request("/api/me", token=token, device=self.device_a)[0], 200)
        self.assertEqual(self.request("/api/me", token=second, device=self.device_a)[0], 401)
        self.assertEqual(self.request("/api/admin/users", token=self.admin)[0], 401)
        self.assertEqual(self.request("/api/admin/login", {"username":"owner", "password":"administrator password"})[0], 401)
        new_admin = self.request("/api/admin/login", {"username":"owner", "password":"new secure admin password"})
        self.assertEqual(new_admin[0], 200)
        self.assertEqual(self.login("owner", "administrator password")[0], 401)
        new_login = self.login("owner", "new secure admin password")
        self.assertEqual(new_login[0], 200)
        self.assertEqual(new_login[1]["user"]["uid"], uid)
        self.db.reset_admin("owner", "recovered admin password")
        self.assertEqual(self.request("/api/me", token=token, device=self.device_a)[0], 401)
        self.assertEqual(self.request("/api/admin/users", token=new_admin[1]["token"])[0], 401)
        self.assertEqual(self.login("owner", "recovered admin password")[1]["user"]["uid"], uid)
        self.assertEqual(self.request("/api/admin/login", {"username":"owner", "password":"recovered admin password"})[0], 200)
        self.assertEqual(self.request("/api/admin/users", {"username":"OWNER","password":"some-password"},
                                      new_admin[1]["token"])[0], 401)

    def test_admin_panel_password_reset_is_shared_and_reserved_username(self):
        self.assertEqual(self.request("/api/admin/users", {"username":"OWNER","password":"some-password"}, self.admin)[0], 409)
        owner = self.login("owner", "administrator password")[1]
        uid = owner["user"]["uid"]
        self.assertEqual(self.admin_action(uid, "password", {"password":"short-pass"})[0], 400)
        self.assertEqual(self.admin_action(uid, "rename", {"username":"not-owner"})[1]["code"], "ADMIN_RENAME")
        self.assertEqual(self.admin_action(uid, "password", {"password":"panel changed password"})[0], 200)
        self.assertEqual(self.request("/api/me", token=owner["token"], device=self.device_a)[0], 401)
        self.assertEqual(self.request("/api/admin/users", token=self.admin)[0], 401)
        self.assertEqual(self.login("owner", "panel changed password")[0], 200)
        self.assertEqual(self.request("/api/admin/login", {"username":"owner", "password":"panel changed password"})[0], 200)

    def test_user_profile_password_validation_and_session_revocation(self):
        uid = self.create()
        token1 = self.login()[1]["token"]
        token2 = self.login()[1]["token"]
        body = {"old_password":"incorrect", "new_password":"my new password", "confirmation":"my new password"}
        self.assertEqual(self.request("/api/me/password", body, token1, self.device_a)[1]["code"], "WRONG_PASSWORD")
        body.update(old_password="password-for-test", confirmation="other")
        self.assertEqual(self.request("/api/me/password", body, token1, self.device_a)[1]["code"], "PASSWORD_MISMATCH")
        body["confirmation"] = "my new password"
        self.assertEqual(self.request("/api/me/password", body, token1, self.device_a)[0], 200)
        self.assertEqual(self.request("/api/me", token=token1, device=self.device_a)[0], 200)
        self.assertEqual(self.request("/api/me", token=token2, device=self.device_a)[0], 401)
        self.assertEqual(self.login(password="password-for-test")[0], 401)
        self.assertEqual(self.login(password="my new password")[1]["user"]["uid"], uid)
        events = self.request("/api/admin/audit", token=self.admin)[1]["events"]
        self.assertNotIn("my new password", json.dumps(events))

    def test_key_limits_idempotency_expiry_and_secret_storage(self):
        uid1, uid2 = self.create(), self.create("fisher2")
        token1, token2 = self.login()[1]["token"], self.login("fisher2")[1]["token"]
        key = self.create_key(max_users=1, max_activations=3, max_per_user=2)
        self.assertRegex(key["key"], srv.KEY_RE)
        operation = uuid.uuid4().hex
        status, first, _ = self.redeem(token1, key["key"].lower(), operation)
        self.assertEqual(status, 200, first)
        repeat = self.redeem(token1, key["key"], operation)
        self.assertTrue(repeat[1]["already_processed"])
        self.assertEqual(repeat[1]["expires_at"], first["expires_at"])
        second = self.redeem(token1, key["key"])
        self.assertEqual(second[1]["expires_at"] - first["expires_at"], 3600)
        self.assertEqual(self.redeem(token1, key["key"])[1]["code"], "KEY_PERSONAL_LIMIT")
        self.assertEqual(self.redeem(token2, key["key"])[1]["code"], "KEY_USERS_EXHAUSTED")
        listing = self.request("/api/admin/keys", token=self.admin)[1]["keys"]
        self.assertEqual((listing[0]["users_count"], listing[0]["activation_count"]), (1, 2))
        self.assertNotIn(key["key"], json.dumps(listing))
        self.assertNotIn(key["key"], json.dumps(self.request("/api/admin/audit", token=self.admin)[1]))
        with self.db.connect() as db:
            stored = db.execute("SELECT * FROM activation_keys WHERE id=?", (key["id"],)).fetchone()
            self.assertEqual(stored["key_hash"], srv.hashlib.sha256(key["key"].encode("ascii")).hexdigest())
            self.assertNotIn(key["key"], str(dict(stored)))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM key_activations WHERE uid=?", (uid2,)).fetchone()[0], 0)
        another = self.create_key(max_users=2, max_activations=1, max_per_user=1)
        self.assertEqual(self.redeem(token1, another["key"], operation)[1]["code"], "REQUEST_REUSED")
        self.assertEqual(self.redeem(token1, another["key"])[0], 200)
        self.assertEqual(self.redeem(token2, another["key"])[1]["code"], "KEY_USES_EXHAUSTED")
        disabled = self.create_key()
        self.assertEqual(self.request("/api/admin/keys/%d/status" % disabled["id"], {"enabled":False}, self.admin)[0], 200)
        self.assertEqual(self.redeem(token2, disabled["key"])[1]["code"], "KEY_DISABLED")
        self.assertEqual(self.request("/api/admin/keys/%d/status" % disabled["id"], {"enabled":True}, self.admin)[0], 200)
        with self.db.connect() as db:
            db.execute("UPDATE activation_keys SET activate_before=? WHERE id=?", (srv.unix_now()-1, disabled["id"]))
        self.assertEqual(self.redeem(token2, disabled["key"])[1]["code"], "KEY_EXPIRED")
        self.assertEqual(self.redeem(token2, "not-a-key")[1]["code"], "BAD_KEY")
        self.assertEqual(self.request("/api/admin/keys", token=token1)[0], 401)
        self.assertEqual(self.request("/api/me/activate-key", {"key":key["key"],"request_id":uuid.uuid4().hex})[0], 401)
        invalid = {"product":"rmfish", "seconds":3600, "activate_before":srv.unix_now()+1000,
                   "max_users":True, "max_activations":1, "max_per_user":1}
        self.assertEqual(self.request("/api/admin/keys", invalid, self.admin)[1]["code"], "BAD_LIMITS")
        invalid.update(max_users=1, activate_before=srv.unix_now()-1)
        self.assertEqual(self.request("/api/admin/keys", invalid, self.admin)[1]["code"], "BAD_DEADLINE")
        self.assertGreater(self.db.user_info(uid1)["products"][0]["expires_at"], srv.unix_now())

    def test_concurrent_activation_enforces_both_limits_and_retains_all_time(self):
        people = []
        for i in range(4):
            name = "parallel%d" % i
            uid = self.create(name)
            status, data, _ = self.login(name)
            self.assertEqual(status, 200)
            people.append((uid, data["token"]))
        key = self.create_key(max_users=3, max_activations=5, max_per_user=2)
        barrier = threading.Barrier(8)
        results = []
        def worker(uid, token):
            barrier.wait()
            results.append((uid, self.redeem(token, key["key"])))
        threads = [threading.Thread(target=worker, args=person) for person in people for _ in range(2)]
        for t in threads: t.start()
        for t in threads: t.join(15)
        self.assertEqual(len(results), 8)
        successful = [item for item in results if item[1][0] == 200]
        self.assertEqual(len(successful), 5, results)
        self.assertEqual(len({uid for uid, _ in successful}), 3)
        with self.db.connect() as db:
            rows = db.execute("SELECT uid,COUNT(*) AS n,MAX(expires_at) AS expiry FROM key_activations WHERE key_id=? GROUP BY uid", (key["id"],)).fetchall()
            self.assertEqual(sum(row["n"] for row in rows), 5)
            self.assertTrue(all(row["n"] <= 2 for row in rows))
            for row in rows:
                self.assertEqual(self.db.user_info(row["uid"])["products"][0]["expires_at"], row["expiry"])

    def test_concurrent_retry_is_idempotent(self):
        self.create()
        token = self.login()[1]["token"]
        key = self.create_key(max_users=1, max_activations=8, max_per_user=8)
        operation = uuid.uuid4().hex
        barrier = threading.Barrier(6)
        results = []
        def worker():
            barrier.wait()
            results.append(self.redeem(token, key["key"], operation))
        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads: t.start()
        for t in threads: t.join(15)
        self.assertEqual(len(results), 6)
        self.assertTrue(all(result[0] == 200 for result in results), results)
        self.assertEqual(len({result[1]["expires_at"] for result in results}), 1)
        self.assertEqual(sum(not result[1]["already_processed"] for result in results), 1)
        listing = self.request("/api/admin/keys", token=self.admin)[1]["keys"]
        self.assertEqual((listing[0]["users_count"], listing[0]["activation_count"]), (1, 1))

    def test_sensitive_writes_recheck_revoked_session_inside_transaction(self):
        uid = self.create()
        token = self.login()[1]["token"]
        key = self.create_key()
        self.assertEqual(self.db.authenticate(token, self.device_a)["uid"], uid)
        self.admin_action(uid, "reset-hwid")
        self.assertEqual(self.redeem(token, key["key"])[0], 401)
        body = {"old_password":"password-for-test", "new_password":"new password", "confirmation":"new password"}
        self.assertEqual(self.request("/api/me/password", body, token, self.device_a)[0], 401)
        self.assertIsNone(self.db.user_info(uid)["products"][0]["expires_at"])

    def test_rate_limit_and_admin_reset(self):
        for _ in range(8):
            self.assertEqual(self.login("missing", "some-password")[0], 401)
        self.assertEqual(self.login("missing", "some-password")[0], 429)
        self.db.reset_admin("owner", "new administrator password")
        self.assertEqual(self.request("/api/admin/users", token=self.admin)[0], 401)
        self.assertEqual(self.request("/api/admin/login", {"username": "owner", "password": "new administrator password"})[0], 200)


class MigrationAndConfigurationTests(unittest.TestCase):
    def test_existing_database_is_migrated_without_losing_access(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "old.db"
            token, device = "a" * 43, "b" * 64
            with sqlite3.connect(path) as db:
                db.executescript("""
                    CREATE TABLE products(code TEXT PRIMARY KEY, name TEXT NOT NULL, created_at INTEGER NOT NULL);
                    CREATE TABLE users(uid INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                        salt BLOB NOT NULL, password_hash BLOB NOT NULL, rounds INTEGER NOT NULL,
                        disabled INTEGER NOT NULL DEFAULT 0, hwid_hash TEXT, created_at INTEGER NOT NULL);
                    CREATE TABLE subscriptions(uid INTEGER NOT NULL REFERENCES users(uid), product_code TEXT NOT NULL REFERENCES products(code),
                        expires_at INTEGER NOT NULL, PRIMARY KEY(uid,product_code));
                    CREATE TABLE sessions(token_hash TEXT PRIMARY KEY, uid INTEGER NOT NULL REFERENCES users(uid),
                        device_hash TEXT NOT NULL, expires_at INTEGER NOT NULL, created_at INTEGER NOT NULL);
                """)
                db.execute("INSERT INTO users VALUES(?,?,?,?,?,?,?,?)", (42,"old-user",b"salt",b"hash",310000,0,device,1))
                db.execute("INSERT INTO products VALUES(?,?,?)", ("rmfish","RMFish",1))
                db.execute("INSERT INTO products VALUES(?,?,?)", ("other","Другой",1))
                db.execute("INSERT INTO subscriptions VALUES(?,?,?)", (42,"rmfish",srv.unix_now()+7200))
                db.execute("INSERT INTO sessions VALUES(?,?,?,?,?)", (srv.token_hash(token),42,device,srv.unix_now()+7200,1))
            # sqlite's context manager commits but does not close; Windows
            # cannot remove a temporary database while this handle is open.
            db.close()
            migrated = srv.Database(path)
            self.assertEqual(migrated.authenticate(token, device)["uid"], 42)
            self.assertEqual(migrated.authorize(42,"rmfish")["code"], "rmfish")
            profile = migrated.user_info(42)
            self.assertEqual(profile["user"]["username"], "old-user")
            self.assertEqual({p["game_code"] for p in profile["products"]}, {"gta5"})
            self.assertEqual(len(profile["products"]), 2)
            public = migrated.public_status()
            self.assertEqual(public["total_products"], 2)
            self.assertEqual({p["status"] for p in public["products"]}, {"OUTDATED"})
            self.assertEqual(srv.Database(path).authorize(42,"rmfish")["code"], "rmfish")

    def test_conflicting_legacy_accounts_are_never_merged_or_taken_over(self):
        # Even identical credentials do not prove the two legacy accounts are
        # the same person. All old UIDs, subscriptions and sessions survive.
        for same_password in (False, True):
            with self.subTest(same_password=same_password), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "legacy.db"
                admin_password = "legacy admin password"
                user_password = admin_password if same_password else "legacy user password"
                salt_a, hash_a, rounds_a = srv.new_password(admin_password)
                salt_u, hash_u, rounds_u = srv.new_password(user_password)
                token, admin_token, device = "u" * 43, "a" * 43, "b" * 64
                with sqlite3.connect(path) as db:
                    db.executescript("""
                        CREATE TABLE admins(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                            salt BLOB NOT NULL,password_hash BLOB NOT NULL,rounds INTEGER NOT NULL,created_at INTEGER NOT NULL);
                        CREATE TABLE users(uid INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                            salt BLOB NOT NULL,password_hash BLOB NOT NULL,rounds INTEGER NOT NULL,
                            disabled INTEGER NOT NULL DEFAULT 0,hwid_hash TEXT,created_at INTEGER NOT NULL);
                        CREATE TABLE products(code TEXT PRIMARY KEY,name TEXT NOT NULL,created_at INTEGER NOT NULL);
                        CREATE TABLE subscriptions(uid INTEGER NOT NULL REFERENCES users(uid),product_code TEXT NOT NULL REFERENCES products(code),
                            expires_at INTEGER NOT NULL,PRIMARY KEY(uid,product_code));
                        CREATE TABLE sessions(token_hash TEXT PRIMARY KEY,uid INTEGER NOT NULL REFERENCES users(uid),
                            device_hash TEXT NOT NULL,expires_at INTEGER NOT NULL,created_at INTEGER NOT NULL);
                        CREATE TABLE admin_sessions(token_hash TEXT PRIMARY KEY,admin_id INTEGER NOT NULL REFERENCES admins(id),
                            expires_at INTEGER NOT NULL,created_at INTEGER NOT NULL);
                    """)
                    db.execute("INSERT INTO admins VALUES(?,?,?,?,?,?)", (5,"Shared",salt_a,hash_a,rounds_a,1))
                    db.execute("INSERT INTO users VALUES(?,?,?,?,?,?,?,?)", (42,"shared",salt_u,hash_u,rounds_u,0,device,1))
                    db.execute("INSERT INTO products VALUES(?,?,?)", ("rmfish","RMFish",1))
                    db.execute("INSERT INTO subscriptions VALUES(?,?,?)", (42,"rmfish",srv.unix_now()+7200))
                    db.execute("INSERT INTO sessions VALUES(?,?,?,?,?)", (srv.token_hash(token),42,device,srv.unix_now()+7200,1))
                    db.execute("INSERT INTO admin_sessions VALUES(?,?,?,?)", (srv.token_hash(admin_token),5,srv.unix_now()+7200,1))
                db.close()
                migrated = srv.Database(path)
                self.assertEqual(migrated.authenticate(token, device)["uid"], 42)
                self.assertEqual(migrated.authenticate(admin_token, admin=True)["id"], 5)
                self.assertEqual(migrated.authorize(42,"rmfish")["code"], "rmfish")
                listing = migrated.admin_users("shared")["users"]
                self.assertEqual(len(listing), 2)
                self.assertTrue(next(u for u in listing if u["uid"] == 42)["login_conflict"])
                admin_user = next(u for u in listing if u["is_admin"])
                self.assertNotEqual(admin_user["uid"], 42)
                self.assertFalse(any(p["active"] for p in admin_user["products"]))
                logged_admin = migrated.login("shared", admin_password, "c"*64)
                self.assertEqual(logged_admin["user"]["uid"], admin_user["uid"])
                self.assertEqual(logged_admin["user"]["username"], "Shared")
                if not same_password:
                    self.assertEqual(migrated.login("shared", user_password, device)["user"]["uid"], 42)
                # Resolve the ambiguous name explicitly; never transfer rights.
                migrated.change_user("Shared", 42, "rename", {"username":"legacy-user"})
                self.assertEqual(migrated.login("legacy-user", user_password, device)["user"]["uid"], 42)
                self.assertEqual(migrated.authorize(42,"rmfish")["code"], "rmfish")
                self.assertEqual(srv.Database(path).login("shared", admin_password, "c"*64)["user"]["uid"], admin_user["uid"])
                with self.assertRaises(srv.ApiError): migrated.create_user("Shared", "SHARED", "password-123")

    def test_lan_policy_accepts_private_literal_addresses_not_public_http(self):
        for host in ("localhost", "127.0.0.1", "192.168.0.105", "10.2.3.4", "172.16.2.3", "172.31.255.255"):
            self.assertTrue(srv.lan_http_address(host), host)
        for host in ("0.0.0.0", "8.8.8.8", "172.32.0.1", "169.254.1.2", "example.com", "192.168.1.2.example.com"):
            self.assertFalse(srv.lan_http_address(host), host)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "server.db"
            database = srv.Database(path); database.init_admin("owner", "administrator password")
            # Reject an all-interface/public HTTP bind even if the host machine
            # happens to have that address; a TLS setup is a separate mode.
            result = subprocess.run([sys.executable, str(SERVER_PATH), "--db", str(path), "serve", "--host", "0.0.0.0"],
                                    capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            class FakeServer:
                def __init__(self, address, database, allowed_hosts, lan_http_only):
                    self.address, self.allowed_hosts, self.lan_http_only = address, allowed_hosts, lan_http_only
                def serve_forever(self, poll_interval): pass
                def server_close(self): pass
            with mock.patch.object(srv, "Server", wraps=FakeServer) as factory, mock.patch("builtins.print"):
                self.assertEqual(srv.main(["--db", str(path), "serve"]), 0)
                args, kwargs = factory.call_args
                self.assertEqual(args[0], ("192.168.0.105", 8765))
                self.assertIn("192.168.0.105", args[2])
                self.assertTrue(kwargs["lan_http_only"])

    def test_owner_can_embed_url_without_overwriting_or_remote_http(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            original, first, second = base / "source.exe", base / "first.exe", base / "second.exe"
            original_data = b"MZfake" + srv.LOADER_CONFIG_MAGIC.decode().encode("utf-16le") + b"original"
            original.write_bytes(original_data)
            srv.configure_loader(original, first, "https://macro.example.com:8443/")
            data = first.read_bytes()
            footer = len(srv.LOADER_CONFIG_MAGIC) + 4
            size = struct.unpack("<I", data[-footer:-len(srv.LOADER_CONFIG_MAGIC)])[0]
            self.assertEqual(data[-footer-size:-footer], b"https://macro.example.com:8443")
            self.assertEqual(original.read_bytes(), original_data)
            srv.configure_loader(first, second, "http://127.0.0.1:8765")
            self.assertEqual(second.read_bytes().count(srv.LOADER_CONFIG_MAGIC), 1)
            self.assertTrue(second.read_bytes().startswith(original_data))
            with self.assertRaises(FileExistsError): srv.configure_loader(original, first, "https://example.com")
            with self.assertRaises(ValueError): srv.configure_loader(original, original, "https://example.com")
            for good in ["http://192.168.0.105:8765", "http://10.0.0.8", "http://172.16.8.2", "http://127.0.0.1:8765"]:
                self.assertEqual(srv.validate_loader_url(good), good)
            for bad in ["http://8.8.8.8", "http://public.example.com", "http://172.32.0.1", "http://0.0.0.0",
                        "https://user:pass@example.com", "https://example.com/path", "https://example.com?x=1"]:
                with self.assertRaises(ValueError): srv.validate_loader_url(bad)
            old = base / "old.exe"; old.write_bytes(b"MZlegacy")
            with self.assertRaises(ValueError): srv.configure_loader(old, base / "bad.exe", "https://example.com")
            # An English Windows console/redirect may not represent Russian
            # status text. File creation must still exit successfully.
            environment = dict(os.environ, PYTHONIOENCODING="cp1252")
            third = base / "third.exe"
            result = subprocess.run([sys.executable, str(SERVER_PATH), "configure-client", "--source", str(original),
                "--output", str(third), "--url", "https://example.com"], env=environment, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(third.exists())


if __name__ == "__main__":
    unittest.main()
