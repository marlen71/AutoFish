"""HTTP and SQLite integration tests; no external packages or real credentials."""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

SERVER_PATH = Path(__file__).resolve().parents[1] / "server" / "server.py"
spec = importlib.util.spec_from_file_location("rmacro_server", SERVER_PATH)
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)


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
        self.assertEqual(self.request("/api/admin/users?q=00000001", token=self.admin)[1]["users"][0]["uid"], uid)
        self.assertTrue(any(u["uid"] == uid and u["hwid_bound"] for u in users))
        reopened = srv.Database(self.db.path)
        self.assertEqual(len(reopened.admin_users()["users"]), 2)
        self.assertEqual(reopened.user_info(uid)["user"]["username"], "fisher")
        backup = self.db.backup(Path(self.temp.name) / "backup.db")
        self.assertEqual(len(srv.Database(backup).admin_users()["users"]), 2)
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
        self.assertEqual(self.request("/api/health", extra_headers={"Host": "attacker.example"})[0], 400)
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
            self.assertEqual(srv.Database(path).authorize(42,"rmfish")["code"], "rmfish")

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
            for bad in ["http://192.168.1.7", "https://user:pass@example.com", "https://example.com/path", "https://example.com?x=1"]:
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
