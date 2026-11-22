#!/usr/bin/env python3
"""Eternal Core server: standard-library HTTP API, SQLite, and admin UI.

The chosen LAN HTTP mode is unencrypted. Never expose it to the internet;
for public access configure trusted HTTPS as described in README-SERVER.md.
"""
import argparse
import collections
import datetime as dt
import getpass
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import ssl
import struct
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "data" / "rmacro.db"
STATIC = ROOT / "static"
PBKDF2_ROUNDS = 310_000
USER_SESSION_SECONDS = 30 * 24 * 60 * 60
ADMIN_SESSION_SECONDS = 12 * 60 * 60
MAX_REQUEST_BYTES = 16384
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,47}$")
DEVICE_RE = re.compile(r"^[0-9a-f]{64}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{40,64}$")
KEY_RE = re.compile(r"^EC-(?:[0-9A-F]{4}-){7}[0-9A-F]{4}$")
REQUEST_ID_RE = re.compile(r"^[0-9a-f]{32}$")
MAX_DURATION = 10 * 366 * 86400
MAX_KEY_USES = 1_000_000


class ApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def check_username(value):
    if not isinstance(value, str) or not NAME_RE.fullmatch(value):
        raise ApiError(400, "BAD_USERNAME", "Логин: 3–32 латинских буквы, цифры, точка, дефис или подчёркивание.")
    return value


def check_password(value, admin=False):
    minimum = 12 if admin else 8
    if not isinstance(value, str) or not minimum <= len(value) <= 256:
        raise ApiError(400, "BAD_PASSWORD", "Пароль должен содержать от %d до 256 символов." % minimum)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ApiError(400, "BAD_PASSWORD", "Пароль содержит недопустимые символы.")
    return value


def password_hash(password, salt, rounds=PBKDF2_ROUNDS):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)


def new_password(password):
    salt = secrets.token_bytes(16)
    return salt, password_hash(password, salt), PBKDF2_ROUNDS


def token_hash(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def unix_now():
    return int(time.time())


class ManagedConnection(sqlite3.Connection):
    """sqlite's normal context manager commits but does not close the file."""
    def __exit__(self, exc_type, exc_value, tb):
        try:
            return super().__exit__(exc_type, exc_value, tb)
        finally:
            self.close()


class Database:
    """A connection per operation; writes use immediate transactions."""
    def __init__(self, path=DEFAULT_DB):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(str(self.path.parent), 0o700)
        except OSError:
            pass
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS admins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    salt BLOB NOT NULL, password_hash BLOB NOT NULL, rounds INTEGER NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    uid INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    salt BLOB NOT NULL, password_hash BLOB NOT NULL, rounds INTEGER NOT NULL,
                    disabled INTEGER NOT NULL DEFAULT 0 CHECK (disabled IN (0,1)),
                    hwid_hash TEXT, created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS games (
                    code TEXT PRIMARY KEY, name TEXT NOT NULL, created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS products (
                    code TEXT PRIMARY KEY, name TEXT NOT NULL, created_at INTEGER NOT NULL,
                    game_code TEXT NOT NULL DEFAULT 'gta5' REFERENCES games(code)
                );
                CREATE TABLE IF NOT EXISTS subscriptions (
                    uid INTEGER NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
                    product_code TEXT NOT NULL REFERENCES products(code),
                    expires_at INTEGER NOT NULL,
                    PRIMARY KEY (uid, product_code)
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    uid INTEGER NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
                    device_hash TEXT NOT NULL, expires_at INTEGER NOT NULL, created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_uid ON sessions(uid);
                CREATE TABLE IF NOT EXISTS admin_sessions (
                    token_hash TEXT PRIMARY KEY,
                    admin_id INTEGER NOT NULL REFERENCES admins(id) ON DELETE CASCADE,
                    expires_at INTEGER NOT NULL, created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS admin_user_links (
                    admin_id INTEGER PRIMARY KEY REFERENCES admins(id) ON DELETE CASCADE,
                    uid INTEGER NOT NULL UNIQUE REFERENCES users(uid) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS activation_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_hash TEXT NOT NULL UNIQUE, key_hint TEXT NOT NULL,
                    product_code TEXT NOT NULL REFERENCES products(code),
                    duration_seconds INTEGER NOT NULL, activate_before INTEGER NOT NULL,
                    max_users INTEGER NOT NULL, max_activations INTEGER NOT NULL,
                    max_per_user INTEGER NOT NULL, disabled INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL, created_by TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS key_activations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_id INTEGER NOT NULL REFERENCES activation_keys(id),
                    uid INTEGER NOT NULL REFERENCES users(uid),
                    request_id TEXT NOT NULL,
                    activated_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
                    UNIQUE(uid, request_id)
                );
                CREATE INDEX IF NOT EXISTS key_activations_key_user ON key_activations(key_id,uid);
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    at INTEGER NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
                    uid INTEGER, details TEXT NOT NULL DEFAULT ''
                );
            """)
            # Upgrade an existing beta.1 database in place without changing
            # user IDs, sessions, subscriptions, or product codes. Serialize
            # concurrent initializations before inspecting and altering schema.
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO games(code,name,created_at) VALUES(?,?,?)", ("gta5", "GTA5 · RMRP", unix_now()))
            columns = {row["name"] for row in db.execute("PRAGMA table_info(products)")}
            if "game_code" not in columns:
                # SQLite permits an added REFERENCES column only with a NULL
                # default. Immediately backfill it inside this transaction.
                db.execute("ALTER TABLE products ADD COLUMN game_code TEXT REFERENCES games(code)")
            db.execute("UPDATE products SET game_code='gta5' WHERE game_code IS NULL")
            db.execute("INSERT OR IGNORE INTO products(code,name,created_at,game_code) VALUES(?,?,?,?)",
                       ("rmfish", "RMFish", unix_now(), "gta5"))
            # Never adopt an unrelated legacy user merely because its login
            # matches an administrator. Conflicts get a separate loader UID.
            for admin_row in db.execute("SELECT * FROM admins").fetchall():
                self._ensure_admin_user(db, admin_row)
            db.commit()
        try:
            os.chmod(str(self.path), 0o600)
        except OSError:
            pass

    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=10, factory=ManagedConnection)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @staticmethod
    def _ensure_admin_user(db, admin):
        """Create the administrator's loader identity while holding a write lock.

        Old databases may already contain an unrelated user with the same
        login, even with the same password. Never take over that account. An
        internal name (not a valid public login) lets both UIDs and all their
        existing subscriptions and sessions remain separate. In an ambiguous
        same-password collision the administrator takes precedence at login;
        the owner must rename the old user in the panel to restore that login.
        """
        link = db.execute("SELECT uid FROM admin_user_links WHERE admin_id=?", (admin["id"],)).fetchone()
        if link:
            return link["uid"]
        existing = db.execute("SELECT uid FROM users WHERE username=?", (admin["username"],)).fetchone()
        name = admin["username"] if not existing else "~admin-" + str(admin["id"])
        while db.execute("SELECT uid FROM users WHERE username=?", (name,)).fetchone():
            name = "~admin-" + str(admin["id"]) + "-" + secrets.token_hex(4)
        cur = db.execute("INSERT INTO users(username,salt,password_hash,rounds,created_at) VALUES(?,?,?,?,?)",
                         (name, admin["salt"], admin["password_hash"], admin["rounds"], unix_now()))
        uid = cur.lastrowid
        db.execute("INSERT INTO admin_user_links(admin_id,uid) VALUES(?,?)", (admin["id"], uid))
        return uid

    def has_admin(self):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM admins LIMIT 1").fetchone() is not None

    def init_admin(self, username, password):
        username, password = check_username(username), check_password(password, True)
        salt, hashed, rounds = new_password(password)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM admins LIMIT 1").fetchone():
                raise ApiError(409, "ADMIN_EXISTS", "Администратор уже создан. Используйте локальную команду reset-admin.")
            cur = db.execute("INSERT INTO admins(username,salt,password_hash,rounds,created_at) VALUES(?,?,?,?,?)",
                             (username, salt, hashed, rounds, unix_now()))
            self._ensure_admin_user(db, db.execute("SELECT * FROM admins WHERE id=?", (cur.lastrowid,)).fetchone())

    def reset_admin(self, username, password):
        username, password = check_username(username), check_password(password, True)
        salt, hashed, rounds = new_password(password)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
            if not row:
                raise ApiError(404, "NOT_FOUND", "Администратор не найден.")
            uid = self._ensure_admin_user(db, row)
            db.execute("UPDATE admins SET salt=?,password_hash=?,rounds=? WHERE id=?", (salt, hashed, rounds, row["id"]))
            db.execute("UPDATE users SET salt=?,password_hash=?,rounds=? WHERE uid=?", (salt, hashed, rounds, uid))
            db.execute("DELETE FROM admin_sessions WHERE admin_id=?", (row["id"],))
            db.execute("DELETE FROM sessions WHERE uid=?", (uid,))
            self.audit(db, row["username"], "admin_reset_password", uid)

    @staticmethod
    def audit(db, actor, action, uid=None, details=""):
        db.execute("INSERT INTO audit(at,actor,action,uid,details) VALUES(?,?,?,?,?)",
                   (unix_now(), actor, action, uid, details[:200]))

    @staticmethod
    def games_for(db):
        return [dict(row) for row in db.execute("SELECT code,name FROM games ORDER BY name COLLATE NOCASE,code")]

    @staticmethod
    def products_for(db, uid, now):
        rows = db.execute("""SELECT p.code,p.name,p.game_code,g.name AS game_name,s.expires_at FROM products p
            JOIN games g ON g.code=p.game_code
            LEFT JOIN subscriptions s ON s.product_code=p.code AND s.uid=? ORDER BY p.code""", (uid,)).fetchall()
        return [{"code": r["code"], "name": r["name"], "game_code": r["game_code"], "game_name": r["game_name"],
                 "expires_at": r["expires_at"], "active": r["expires_at"] is not None and r["expires_at"] > now,
                 "seconds_remaining": max(0, r["expires_at"] - now) if r["expires_at"] is not None else 0}
                for r in rows]

    def user_info(self, uid):
        now = unix_now()
        with self.connect() as db:
            row = db.execute("""SELECT u.uid,COALESCE(a.username,u.username) AS username,
                a.id IS NOT NULL AS is_admin FROM users u
                LEFT JOIN admin_user_links l ON l.uid=u.uid LEFT JOIN admins a ON a.id=l.admin_id
                WHERE u.uid=? AND u.disabled=0""", (uid,)).fetchone()
            if not row:
                raise ApiError(401, "SESSION_INVALID", "Сессия больше не действительна. Войдите заново.")
            return {"server_time": now, "user": {"uid": row["uid"], "username": row["username"],
                    "is_admin": bool(row["is_admin"])}, "games": self.games_for(db),
                    "products": self.products_for(db, uid, now)}

    def login(self, username, password, device, admin=False):
        # Same generic failure for an unknown account and an incorrect password.
        if (not isinstance(username, str) or not NAME_RE.fullmatch(username) or
                not isinstance(password, str) or len(password) > 256):
            raise ApiError(401, "BAD_CREDENTIALS", "Неверный логин или пароль.")
        try:
            password.encode("utf-8")
        except UnicodeEncodeError:
            raise ApiError(401, "BAD_CREDENTIALS", "Неверный логин или пароль.")
        if not admin and (not isinstance(device, str) or not DEVICE_RE.fullmatch(device)):
            raise ApiError(400, "BAD_DEVICE", "Не удалось определить идентификатор устройства.")
        with self.connect() as db:
            administrator = db.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
            # Admin credentials always have priority for the loader. If there
            # is a legacy collision with a different password, its owner can
            # still log in to the original UID using that other password.
            salt, expected, rounds = ((administrator["salt"], administrator["password_hash"], administrator["rounds"])
                                      if administrator else (b"EternalCore-dummy", b"\x00" * 32, PBKDF2_ROUNDS))
            admin_ok = hmac.compare_digest(password_hash(password, salt, rounds), expected) and administrator is not None
            row = None
            if admin or admin_ok:
                if not admin_ok:
                    raise ApiError(401, "BAD_CREDENTIALS", "Неверный логин или пароль.")
                row = administrator
                kind = "admin"
            else:
                row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
                salt, expected, rounds = ((row["salt"], row["password_hash"], row["rounds"]) if row
                                          else (b"EternalCore-dummy", b"\x00" * 32, PBKDF2_ROUNDS))
                user_ok = hmac.compare_digest(password_hash(password, salt, rounds), expected)
                if not row or not user_ok or row["disabled"]:
                    raise ApiError(401, "BAD_CREDENTIALS", "Неверный логин или пароль.")
                kind = "user"
            # Recheck the exact password record under a write lock. Resets,
            # renames and bans racing with hashing must take precedence.
            db.execute("BEGIN IMMEDIATE")
            if kind == "admin":
                fresh_admin = db.execute("SELECT * FROM admins WHERE id=? AND username=?", (row["id"], username)).fetchone()
                if (not fresh_admin or fresh_admin["salt"] != row["salt"] or
                        fresh_admin["password_hash"] != row["password_hash"] or fresh_admin["rounds"] != row["rounds"]):
                    raise ApiError(401, "BAD_CREDENTIALS", "Неверный логин или пароль.")
                uid = self._ensure_admin_user(db, fresh_admin)
            else:
                fresh = db.execute("SELECT * FROM users WHERE uid=? AND username=?", (row["uid"], username)).fetchone()
                if (not fresh or fresh["salt"] != row["salt"] or fresh["password_hash"] != row["password_hash"] or
                        fresh["rounds"] != row["rounds"] or fresh["disabled"] or
                        db.execute("SELECT 1 FROM admin_user_links WHERE uid=?", (row["uid"],)).fetchone()):
                    raise ApiError(401, "BAD_CREDENTIALS", "Неверный логин или пароль.")
                uid = fresh["uid"]
            now = unix_now()
            token = secrets.token_urlsafe(32)
            hashed = token_hash(token)
            if admin:
                db.execute("DELETE FROM admin_sessions WHERE expires_at<=?", (now,))
                db.execute("INSERT INTO admin_sessions(token_hash,admin_id,expires_at,created_at) VALUES(?,?,?,?)",
                           (hashed, fresh_admin["id"], now + ADMIN_SESSION_SECONDS, now))
                self.audit(db, fresh_admin["username"], "admin_login")
                return {"token": token, "expires_at": now + ADMIN_SESSION_SECONDS}
            fresh = db.execute("SELECT * FROM users WHERE uid=?", (uid,)).fetchone()
            if not fresh or fresh["disabled"]:
                raise ApiError(401, "BAD_CREDENTIALS", "Неверный логин или пароль.")
            if fresh["hwid_hash"] is None:
                db.execute("UPDATE users SET hwid_hash=? WHERE uid=?", (device, uid))
            elif not hmac.compare_digest(fresh["hwid_hash"], device):
                raise ApiError(403, "DEVICE_MISMATCH", "Аккаунт привязан к другому устройству. Обратитесь к администратору для сброса HWID.")
            db.execute("DELETE FROM sessions WHERE expires_at<=?", (now,))
            db.execute("INSERT INTO sessions(token_hash,uid,device_hash,expires_at,created_at) VALUES(?,?,?,?,?)",
                       (hashed, uid, device, now + USER_SESSION_SECONDS, now))
            display_name = fresh_admin["username"] if kind == "admin" else fresh["username"]
            return {"token": token, "session_expires_at": now + USER_SESSION_SECONDS, "server_time": now,
                    "user": {"uid": uid, "username": display_name, "is_admin": kind == "admin"},
                    "games": self.games_for(db), "products": self.products_for(db, uid, now)}

    @staticmethod
    def _authenticate_in(db, token, device=None, admin=False):
        # Also used inside sensitive write transactions, so a concurrent reset,
        # ban or logout cannot win between authentication and the write.
        if (not isinstance(token, str) or not TOKEN_RE.fullmatch(token) or
                (not admin and (not isinstance(device, str) or not DEVICE_RE.fullmatch(device)))):
            raise ApiError(401, "SESSION_INVALID", "Сессия больше не действительна. Войдите заново.")
        if admin:
            row = db.execute("""SELECT a.id,a.username,s.expires_at FROM admin_sessions s
                JOIN admins a ON a.id=s.admin_id WHERE s.token_hash=?""", (token_hash(token),)).fetchone()
        else:
            row = db.execute("""SELECT u.uid,COALESCE(a.username,u.username) AS username,u.disabled,
                u.hwid_hash,s.device_hash,s.expires_at,a.id AS admin_id
                FROM sessions s JOIN users u ON u.uid=s.uid
                LEFT JOIN admin_user_links l ON l.uid=u.uid LEFT JOIN admins a ON a.id=l.admin_id
                WHERE s.token_hash=?""", (token_hash(token),)).fetchone()
        if (not row or row["expires_at"] <= unix_now() or
                (not admin and (row["disabled"] or row["hwid_hash"] is None or
                 not hmac.compare_digest(row["hwid_hash"], device) or
                 not hmac.compare_digest(row["device_hash"], device)))):
            raise ApiError(401, "SESSION_INVALID", "Сессия больше не действительна. Войдите заново.")
        return dict(row)

    def authenticate(self, token, device=None, admin=False):
        with self.connect() as db:
            return self._authenticate_in(db, token, device, admin)

    def logout(self, token, admin=False):
        table = "admin_sessions" if admin else "sessions"
        with self.connect() as db:
            db.execute("DELETE FROM " + table + " WHERE token_hash=?", (token_hash(token),))

    def authorize(self, uid, code):
        if not isinstance(code, str) or not CODE_RE.fullmatch(code):
            raise ApiError(400, "BAD_PRODUCT", "Некорректный код продукта.")
        now = unix_now()
        with self.connect() as db:
            row = db.execute("SELECT expires_at FROM subscriptions WHERE uid=? AND product_code=?", (uid, code)).fetchone()
            if not row or row["expires_at"] <= now:
                raise ApiError(403, "NO_SUBSCRIPTION", "Нет активной подписки на этот продукт.")
            return {"code": code, "server_time": now, "expires_at": row["expires_at"]}

    def create_user(self, actor, username, password):
        username, password = check_username(username), check_password(password)
        salt, hashed, rounds = new_password(password)
        try:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT 1 FROM admins WHERE username=?", (username,)).fetchone():
                    raise ApiError(409, "USERNAME_TAKEN", "Этот логин занят администратором.")
                cur = db.execute("INSERT INTO users(username,salt,password_hash,rounds,created_at) VALUES(?,?,?,?,?)",
                                 (username, salt, hashed, rounds, unix_now()))
                self.audit(db, actor, "create_user", cur.lastrowid, username)
                return {"uid": cur.lastrowid, "username": username}
        except sqlite3.IntegrityError:
            raise ApiError(409, "USERNAME_TAKEN", "Этот логин уже занят.")

    def create_game(self, actor, code, name):
        if not isinstance(code, str) or not CODE_RE.fullmatch(code):
            raise ApiError(400, "BAD_GAME", "Код игры: строчные латинские буквы, цифры, точка, дефис или подчёркивание (до 48 символов).")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ApiError(400, "BAD_GAME_NAME", "Название игры: от 1 до 80 символов.")
        try:
            with self.connect() as db:
                db.execute("INSERT INTO games(code,name,created_at) VALUES(?,?,?)", (code, name.strip(), unix_now()))
                self.audit(db, actor, "create_game", None, code)
        except sqlite3.IntegrityError:
            raise ApiError(409, "GAME_EXISTS", "Такая игра уже существует.")
        return {"code": code, "name": name.strip()}

    def create_product(self, actor, code, name, game_code="gta5"):
        if not isinstance(code, str) or not CODE_RE.fullmatch(code):
            raise ApiError(400, "BAD_PRODUCT", "Код: строчные латинские буквы, цифры, точка, дефис или подчёркивание (до 48 символов).")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ApiError(400, "BAD_PRODUCT_NAME", "Название продукта: от 1 до 80 символов.")
        if not isinstance(game_code, str) or not CODE_RE.fullmatch(game_code):
            raise ApiError(400, "BAD_GAME", "Выберите игру для продукта.")
        try:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                game = db.execute("SELECT name FROM games WHERE code=?", (game_code,)).fetchone()
                if not game:
                    raise ApiError(404, "GAME_NOT_FOUND", "Игра не найдена.")
                db.execute("INSERT INTO products(code,name,created_at,game_code) VALUES(?,?,?,?)",
                           (code, name.strip(), unix_now(), game_code))
                self.audit(db, actor, "create_product", None, game_code + "/" + code)
        except sqlite3.IntegrityError:
            raise ApiError(409, "PRODUCT_EXISTS", "Такой продукт уже существует.")
        return {"code": code, "name": name.strip(), "game_code": game_code, "game_name": game["name"]}

    def update_product(self, actor, code, name, game_code):
        if not isinstance(code, str) or not CODE_RE.fullmatch(code):
            raise ApiError(400, "BAD_PRODUCT", "Некорректный код продукта.")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ApiError(400, "BAD_PRODUCT_NAME", "Название продукта: от 1 до 80 символов.")
        if not isinstance(game_code, str) or not CODE_RE.fullmatch(game_code):
            raise ApiError(400, "BAD_GAME", "Выберите игру для продукта.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            game = db.execute("SELECT name FROM games WHERE code=?", (game_code,)).fetchone()
            if not game:
                raise ApiError(404, "GAME_NOT_FOUND", "Игра не найдена.")
            if not db.execute("SELECT code FROM products WHERE code=?", (code,)).fetchone():
                raise ApiError(404, "PRODUCT_NOT_FOUND", "Продукт не найден.")
            db.execute("UPDATE products SET name=?,game_code=? WHERE code=?", (name.strip(), game_code, code))
            self.audit(db, actor, "update_product", None, game_code + "/" + code)
        return {"code": code, "name": name.strip(), "game_code": game_code, "game_name": game["name"]}

    def admin_users(self, query=""):
        now = unix_now()
        if not isinstance(query, str) or len(query) > 64:
            raise ApiError(400, "BAD_QUERY", "Слишком длинный поиск.")
        # Escape LIKE wildcards, so a search is always literal.
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        uid_query = str(int(query)) if re.fullmatch(r"[0-9]+", query) else escaped
        with self.connect() as db:
            rows = db.execute("""SELECT u.uid,COALESCE(a.username,u.username) AS username,u.disabled,u.hwid_hash,u.created_at,
                a.id IS NOT NULL AS is_admin,
                (a.id IS NULL AND EXISTS(SELECT 1 FROM admins conflict WHERE conflict.username=u.username)) AS login_conflict
                FROM users u LEFT JOIN admin_user_links l ON l.uid=u.uid LEFT JOIN admins a ON a.id=l.admin_id
                WHERE COALESCE(a.username,u.username) LIKE ? ESCAPE '\\' OR CAST(u.uid AS TEXT) LIKE ? ESCAPE '\\'
                ORDER BY u.uid DESC LIMIT 500""", ("%" + escaped + "%", "%" + uid_query + "%")).fetchall()
            return {"server_time": now, "users": [
                {"uid": r["uid"], "username": r["username"], "disabled": bool(r["disabled"]),
                 "is_admin": bool(r["is_admin"]), "login_conflict": bool(r["login_conflict"]),
                 "hwid_bound": r["hwid_hash"] is not None, "created_at": r["created_at"],
                 "products": self.products_for(db, r["uid"], now)} for r in rows]}

    def admin_games(self):
        with self.connect() as db:
            return {"games": self.games_for(db)}

    def admin_products(self):
        with self.connect() as db:
            return {"products": [dict(r) for r in db.execute("""SELECT p.code,p.name,p.game_code,g.name AS game_name
                FROM products p JOIN games g ON g.code=p.game_code ORDER BY g.name COLLATE NOCASE,p.name COLLATE NOCASE,p.code""")]}

    def audit_rows(self):
        with self.connect() as db:
            return {"events": [dict(r) for r in db.execute(
                "SELECT at,actor,action,uid,details FROM audit ORDER BY id DESC LIMIT 100")]}

    def change_user(self, actor, uid, action, body):
        if not isinstance(uid, int) or uid <= 0:
            raise ApiError(404, "NOT_FOUND", "Пользователь не найден.")
        salt = hashed = rounds = None
        if action == "password":
            salt, hashed, rounds = new_password(check_password(body.get("password")))
        if action == "status" and type(body.get("enabled")) is not bool:
            raise ApiError(400, "BAD_STATUS", "Укажите состояние аккаунта.")
        if action == "rename":
            new_username = check_username(body.get("username"))
        product = body.get("product")
        if action in ("grant", "set", "revoke") and (not isinstance(product, str) or not CODE_RE.fullmatch(product)):
            raise ApiError(400, "BAD_PRODUCT", "Некорректный код продукта.")
        duration = body.get("seconds")
        if action in ("grant", "set") and (type(duration) is not int or not 60 <= duration <= 10 * 366 * 86400):
            raise ApiError(400, "BAD_DURATION", "Срок должен быть от одной минуты до десяти лет.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT uid FROM users WHERE uid=?", (uid,)).fetchone():
                raise ApiError(404, "NOT_FOUND", "Пользователь не найден.")
            linked = db.execute("SELECT admin_id FROM admin_user_links WHERE uid=?", (uid,)).fetchone()
            result = {"ok": True}
            if action == "reset-hwid":
                db.execute("UPDATE users SET hwid_hash=NULL WHERE uid=?", (uid,))
                db.execute("DELETE FROM sessions WHERE uid=?", (uid,))
                self.audit(db, actor, action, uid)
            elif action == "password":
                if linked:
                    check_password(body.get("password"), True)
                    db.execute("UPDATE admins SET salt=?,password_hash=?,rounds=? WHERE id=?",
                               (salt, hashed, rounds, linked["admin_id"]))
                    db.execute("DELETE FROM admin_sessions WHERE admin_id=?", (linked["admin_id"],))
                db.execute("UPDATE users SET salt=?,password_hash=?,rounds=? WHERE uid=?", (salt, hashed, rounds, uid))
                db.execute("DELETE FROM sessions WHERE uid=?", (uid,))
                self.audit(db, actor, action, uid)
            elif action == "rename":
                if linked:
                    raise ApiError(400, "ADMIN_RENAME", "Логин администратора здесь изменить нельзя.")
                if db.execute("SELECT 1 FROM admins WHERE username=?", (new_username,)).fetchone():
                    raise ApiError(409, "USERNAME_TAKEN", "Этот логин занят администратором.")
                try:
                    db.execute("UPDATE users SET username=? WHERE uid=?", (new_username, uid))
                except sqlite3.IntegrityError:
                    raise ApiError(409, "USERNAME_TAKEN", "Этот логин уже занят.")
                db.execute("DELETE FROM sessions WHERE uid=?", (uid,))
                self.audit(db, actor, "rename_user", uid, new_username)
                result["username"] = new_username
            elif action == "status":
                enabled = body["enabled"]
                db.execute("UPDATE users SET disabled=? WHERE uid=?", (0 if enabled else 1, uid))
                if not enabled:
                    db.execute("DELETE FROM sessions WHERE uid=?", (uid,))
                self.audit(db, actor, "enable" if enabled else "disable", uid)
            elif action in ("grant", "set", "revoke"):
                if not db.execute("SELECT code FROM products WHERE code=?", (product,)).fetchone():
                    raise ApiError(404, "PRODUCT_NOT_FOUND", "Продукт не найден.")
                now = unix_now()
                current = db.execute("SELECT expires_at FROM subscriptions WHERE uid=? AND product_code=?", (uid, product)).fetchone()
                if action == "revoke" and current is None:
                    raise ApiError(404, "SUBSCRIPTION_NOT_FOUND", "У пользователя нет этой подписки.")
                expiry = (max(now, current["expires_at"] if current else now) + duration) if action == "grant" else (now + duration if action == "set" else now)
                db.execute("""INSERT INTO subscriptions(uid,product_code,expires_at) VALUES(?,?,?)
                    ON CONFLICT(uid,product_code) DO UPDATE SET expires_at=excluded.expires_at""", (uid, product, expiry))
                self.audit(db, actor, action, uid, product + (" +%ds" % duration if action == "grant" else " =%ds" % duration if action == "set" else ""))
                result["expires_at"] = expiry
            else:
                raise ApiError(404, "NOT_FOUND", "Действие не найдено.")
            return result

    def change_password(self, token, device, old_password, new_value, confirmation):
        if not isinstance(old_password, str) or len(old_password) > 256:
            raise ApiError(400, "BAD_PASSWORD", "Укажите старый пароль.")
        try:
            old_password.encode("utf-8")
        except UnicodeEncodeError:
            raise ApiError(400, "BAD_PASSWORD", "Пароль содержит недопустимые символы.")
        if not isinstance(confirmation, str) or new_value != confirmation:
            raise ApiError(400, "PASSWORD_MISMATCH", "Новый пароль и подтверждение не совпадают.")
        # Password hashing is performed outside the write lock; the session and
        # the exact hash are rechecked inside it before making any changes.
        with self.connect() as db:
            user = self._authenticate_in(db, token, device)
            row = db.execute("SELECT salt,password_hash,rounds FROM users WHERE uid=?", (user["uid"],)).fetchone()
        check_password(new_value, user["admin_id"] is not None)
        if not row or not hmac.compare_digest(password_hash(old_password, row["salt"], row["rounds"]), row["password_hash"]):
            raise ApiError(403, "WRONG_PASSWORD", "Старый пароль указан неверно.")
        salt, hashed, rounds = new_password(new_value)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            fresh = self._authenticate_in(db, token, device)
            current = db.execute("SELECT salt,password_hash,rounds FROM users WHERE uid=?", (fresh["uid"],)).fetchone()
            if (fresh["uid"] != user["uid"] or not current or current["salt"] != row["salt"] or
                    current["password_hash"] != row["password_hash"] or current["rounds"] != row["rounds"]):
                raise ApiError(409, "PASSWORD_CHANGED", "Пароль уже изменился. Войдите заново.")
            db.execute("UPDATE users SET salt=?,password_hash=?,rounds=? WHERE uid=?", (salt, hashed, rounds, fresh["uid"]))
            if fresh["admin_id"] is not None:
                db.execute("UPDATE admins SET salt=?,password_hash=?,rounds=? WHERE id=?", (salt, hashed, rounds, fresh["admin_id"]))
                db.execute("DELETE FROM admin_sessions WHERE admin_id=?", (fresh["admin_id"],))
            # Keep only the requesting loader session, and revoke other loader
            # sessions and all website sessions for the linked administrator.
            db.execute("DELETE FROM sessions WHERE uid=? AND token_hash<>?", (fresh["uid"], token_hash(token)))
            self.audit(db, fresh["username"], "profile_password", fresh["uid"])
        return {"ok": True}

    def create_key(self, admin_token, body):
        product = body.get("product")
        duration, deadline = body.get("seconds"), body.get("activate_before")
        people, uses, per_user = body.get("max_users"), body.get("max_activations"), body.get("max_per_user", 1)
        if not isinstance(product, str) or not CODE_RE.fullmatch(product):
            raise ApiError(400, "BAD_PRODUCT", "Выберите продукт.")
        if type(duration) is not int or not 60 <= duration <= MAX_DURATION:
            raise ApiError(400, "BAD_DURATION", "Срок подписки должен быть от одной минуты до десяти лет.")
        if type(deadline) is not int or not unix_now() < deadline <= unix_now() + MAX_DURATION:
            raise ApiError(400, "BAD_DEADLINE", "Дата окончания активации должна быть в будущем, не более чем через десять лет.")
        if (any(type(n) is not int or not 1 <= n <= MAX_KEY_USES for n in (people, uses, per_user)) or
                per_user > uses):
            raise ApiError(400, "BAD_LIMITS", "Лимиты должны быть целыми числами от 1 до 1 000 000; на пользователя не больше общего числа активаций.")
        # 128 random bits. Only a hash and a short, non-secret hint are stored.
        raw = secrets.token_hex(16).upper()
        key = "EC-" + "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))
        digest = hashlib.sha256(key.encode("ascii")).hexdigest()
        hint = "EC-••••-" + raw[-4:]
        now = unix_now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            actor = self._authenticate_in(db, admin_token, admin=True)
            if not db.execute("SELECT 1 FROM products WHERE code=?", (product,)).fetchone():
                raise ApiError(404, "PRODUCT_NOT_FOUND", "Продукт не найден.")
            # Recheck the deadline after lock acquisition.
            now = unix_now()
            if deadline <= now:
                raise ApiError(400, "BAD_DEADLINE", "Дата окончания активации должна быть в будущем.")
            cur = db.execute("""INSERT INTO activation_keys(key_hash,key_hint,product_code,duration_seconds,
                activate_before,max_users,max_activations,max_per_user,created_at,created_by)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", (digest, hint, product, duration, deadline, people, uses, per_user, now, actor["username"]))
            self.audit(db, actor["username"], "create_key", None, "id:%d product:%s" % (cur.lastrowid, product))
        return {"id": cur.lastrowid, "key": key, "hint": hint}

    def admin_keys(self):
        with self.connect() as db:
            rows = db.execute("""SELECT k.id,k.key_hint,k.product_code,p.name AS product_name,g.name AS game_name,
                k.duration_seconds,k.activate_before,k.max_users,k.max_activations,k.max_per_user,k.disabled,k.created_at,
                COUNT(ka.id) AS activation_count,COUNT(DISTINCT ka.uid) AS users_count
                FROM activation_keys k JOIN products p ON p.code=k.product_code JOIN games g ON g.code=p.game_code
                LEFT JOIN key_activations ka ON ka.key_id=k.id GROUP BY k.id ORDER BY k.id DESC LIMIT 500""").fetchall()
            return {"keys": [dict(row) for row in rows], "server_time": unix_now()}

    def set_key_enabled(self, admin_token, key_id, enabled):
        if type(enabled) is not bool:
            raise ApiError(400, "BAD_STATUS", "Укажите состояние ключа.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            actor = self._authenticate_in(db, admin_token, admin=True)
            if not db.execute("SELECT 1 FROM activation_keys WHERE id=?", (key_id,)).fetchone():
                raise ApiError(404, "KEY_NOT_FOUND", "Ключ не найден.")
            db.execute("UPDATE activation_keys SET disabled=? WHERE id=?", (0 if enabled else 1, key_id))
            self.audit(db, actor["username"], "enable_key" if enabled else "disable_key", None, "id:%d" % key_id)
        return {"ok": True}

    def activate_key(self, token, device, value, request_id):
        if not isinstance(value, str) or not KEY_RE.fullmatch(value.strip().upper()):
            raise ApiError(400, "BAD_KEY", "Неверный формат ключа.")
        if not isinstance(request_id, str) or not REQUEST_ID_RE.fullmatch(request_id):
            raise ApiError(400, "BAD_REQUEST_ID", "Некорректный идентификатор активации.")
        key_hash = hashlib.sha256(value.strip().upper().encode("ascii")).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            user = self._authenticate_in(db, token, device)
            # Retrying the same request after a lost response never adds time a
            # second time. A deliberate reactivation uses a new request ID.
            previous = db.execute("""SELECT a.expires_at,k.key_hash,k.product_code FROM key_activations a
                JOIN activation_keys k ON k.id=a.key_id WHERE a.uid=? AND a.request_id=?""", (user["uid"], request_id)).fetchone()
            if previous:
                if not hmac.compare_digest(previous["key_hash"], key_hash):
                    raise ApiError(409, "REQUEST_REUSED", "Эта попытка уже относится к другому ключу.")
                return {"product": previous["product_code"], "expires_at": previous["expires_at"], "already_processed": True}
            key = db.execute("SELECT * FROM activation_keys WHERE key_hash=?", (key_hash,)).fetchone()
            if not key:
                raise ApiError(404, "KEY_NOT_FOUND", "Ключ не найден.")
            now = unix_now()
            if key["disabled"]:
                raise ApiError(409, "KEY_DISABLED", "Ключ отключён администратором.")
            if key["activate_before"] <= now:
                raise ApiError(410, "KEY_EXPIRED", "Срок активации ключа закончился.")
            counts = db.execute("""SELECT COUNT(*) AS uses,COUNT(DISTINCT uid) AS people,
                COALESCE(SUM(CASE WHEN uid=? THEN 1 ELSE 0 END),0) AS personal
                FROM key_activations WHERE key_id=?""", (user["uid"], key["id"])).fetchone()
            if counts["uses"] >= key["max_activations"]:
                raise ApiError(409, "KEY_USES_EXHAUSTED", "Лимит активаций ключа исчерпан.")
            if counts["personal"] >= key["max_per_user"]:
                raise ApiError(409, "KEY_PERSONAL_LIMIT", "Вы уже использовали этот ключ максимальное число раз.")
            if counts["personal"] == 0 and counts["people"] >= key["max_users"]:
                raise ApiError(409, "KEY_USERS_EXHAUSTED", "Лимит уникальных пользователей ключа исчерпан.")
            current = db.execute("SELECT expires_at FROM subscriptions WHERE uid=? AND product_code=?",
                                 (user["uid"], key["product_code"])).fetchone()
            base = max(now, current["expires_at"] if current else now)
            if base > 9223372036854775807 - key["duration_seconds"]:
                raise ApiError(409, "BAD_EXPIRY", "Невозможно продлить эту подписку.")
            expiry = base + key["duration_seconds"]
            db.execute("""INSERT INTO subscriptions(uid,product_code,expires_at) VALUES(?,?,?)
                ON CONFLICT(uid,product_code) DO UPDATE SET expires_at=excluded.expires_at""",
                       (user["uid"], key["product_code"], expiry))
            db.execute("INSERT INTO key_activations(key_id,uid,request_id,activated_at,expires_at) VALUES(?,?,?,?,?)",
                       (key["id"], user["uid"], request_id, now, expiry))
            self.audit(db, user["username"], "activate_key", user["uid"], "id:%d product:%s" % (key["id"], key["product_code"]))
            return {"product": key["product_code"], "expires_at": expiry, "already_processed": False}

    def backup(self, destination):
        destination = Path(destination).resolve()
        if destination == self.path:
            raise ValueError("Backup path must differ from the live database")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise ValueError("Backup destination already exists")
        with self.connect() as source, sqlite3.connect(str(destination), factory=ManagedConnection) as dest:
            source.backup(dest)
        try:
            os.chmod(str(destination), 0o600)
        except OSError:
            pass
        return destination


class RateLimiter:
    """Small in-memory per-IP login throttle; not a DDoS/WAF replacement."""
    def __init__(self):
        self.lock = threading.Lock()
        self.failures = collections.OrderedDict()

    def check(self, key):
        with self.lock:
            now = time.monotonic()
            attempts = self.failures.get(key, [])
            attempts = [t for t in attempts if now - t < 900]
            self.failures[key] = attempts
            self.failures.move_to_end(key)
            while len(self.failures) > 4096:
                self.failures.popitem(last=False)
            if len(attempts) >= 8:
                raise ApiError(429, "RATE_LIMIT", "Слишком много попыток. Повторите через 15 минут.")

    def fail(self, key):
        with self.lock:
            self.failures.setdefault(key, []).append(time.monotonic())

    def success(self, key):
        with self.lock:
            self.failures.pop(key, None)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, database, allowed_hosts=None, lan_http_only=False):
        self.database = database
        self.limiter = RateLimiter()
        self.lan_http_only = lan_http_only
        self.allowed_hosts = {s.lower().rstrip(".") for s in (allowed_hosts or ("localhost", "127.0.0.1", "::1"))}
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "EternalCore"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, fmt, *args):
        # Never log query strings, authorization headers, passwords, tokens or HWID.
        sys.stderr.write("%s %s %s\n" % (self.address_string(), self.command, urlsplit(self.path).path))

    def send_bytes(self, status, content, mime):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, status, value):
        self.send_bytes(status, json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), "application/json; charset=utf-8")

    def json_body(self):
        if self.headers.get("Transfer-Encoding"):
            raise ApiError(400, "BAD_ENCODING", "Chunked-запросы не поддерживаются.")
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise ApiError(415, "CONTENT_TYPE", "Ожидается JSON.")
        try:
            size = int(self.headers.get("Content-Length", ""))
        except ValueError:
            raise ApiError(411, "LENGTH_REQUIRED", "Не указан размер запроса.")
        if size < 1 or size > MAX_REQUEST_BYTES:
            raise ApiError(413, "BODY_TOO_LARGE", "Недопустимый размер запроса.")
        try:
            data = json.loads(self.rfile.read(size).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "BAD_JSON", "Некорректный JSON.")
        if not isinstance(data, dict):
            raise ApiError(400, "BAD_JSON", "Ожидается JSON-объект.")
        return data

    def token(self):
        value = self.headers.get("Authorization", "")
        if not value.startswith("Bearer "):
            raise ApiError(401, "SESSION_INVALID", "Требуется вход.")
        return value[7:]

    def authenticate(self, admin=False):
        token = self.token()
        return self.server.database.authenticate(token, self.headers.get("X-RMacro-Device"), admin)

    def check_host(self):
        raw_host = self.headers.get("Host", "")
        try:
            host = urlsplit("//" + raw_host).hostname if not any(c in raw_host for c in "@/\\?#") else None
        except ValueError:
            host = None
        if not host or host.lower().rstrip(".") not in self.server.allowed_hosts:
            raise ApiError(400, "BAD_HOST", "Этот адрес сервера не разрешён. Настройте --allowed-host.")

    def handle_request(self):
        if self.server.lan_http_only and not lan_http_address(self.client_address[0]):
            raise ApiError(403, "LAN_ONLY", "HTTP доступен только из локальной сети.")
        self.check_host()
        parsed = urlsplit(self.path)
        path = parsed.path
        db = self.server.database
        if self.command == "GET":
            static = {"/": "index.html", "/admin": "index.html", "/admin/": "index.html",
                      "/admin/app.js": "app.js", "/admin/style.css": "style.css",
                      "/admin/logo.png": "logo.png", "/admin/mark.png": "mark.png", "/admin/favicon.ico": "favicon.ico"}
            if path in static:
                filename = static[path]
                mime = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
                        ".css": "text/css; charset=utf-8", ".png": "image/png", ".ico": "image/x-icon"}[Path(filename).suffix]
                return self.send_bytes(200, (STATIC / filename).read_bytes(), mime)
            if path == "/api/health":
                return self.send_json(200, {"ok": True, "server_time": unix_now()})
            if path == "/api/me":
                user = self.authenticate()
                return self.send_json(200, db.user_info(user["uid"]))
            if path == "/api/admin/users":
                self.authenticate(admin=True)
                query = parse_qs(parsed.query).get("q", [""])[0]
                return self.send_json(200, db.admin_users(query))
            if path == "/api/admin/games":
                self.authenticate(admin=True)
                return self.send_json(200, db.admin_games())
            if path == "/api/admin/products":
                self.authenticate(admin=True)
                return self.send_json(200, db.admin_products())
            if path == "/api/admin/keys":
                self.authenticate(admin=True)
                return self.send_json(200, db.admin_keys())
            if path == "/api/admin/audit":
                self.authenticate(admin=True)
                return self.send_json(200, db.audit_rows())
        if self.command == "POST":
            body = self.json_body()
            if path in ("/api/login", "/api/admin/login"):
                admin = path.startswith("/api/admin/")
                key = ("admin" if admin else "user", self.client_address[0])
                self.server.limiter.check(key)
                try:
                    result = db.login(body.get("username"), body.get("password"), body.get("device"), admin)
                except ApiError as exc:
                    if exc.status in (401, 403):
                        self.server.limiter.fail(key)
                    raise
                self.server.limiter.success(key)
                return self.send_json(200, result)
            if path == "/api/logout":
                self.authenticate()
                db.logout(self.token())
                return self.send_json(200, {"ok": True})
            if path == "/api/authorize":
                user = self.authenticate()
                return self.send_json(200, db.authorize(user["uid"], body.get("product")))
            if path in ("/api/me/password", "/api/me/activate-key"):
                self.authenticate()  # rate-limit only authenticated sessions
                token = self.token()
                key = ("profile-password" if path.endswith("password") else "activate-key", token_hash(token))
                self.server.limiter.check(key)
                try:
                    if path.endswith("password"):
                        result = db.change_password(token, self.headers.get("X-RMacro-Device"), body.get("old_password"),
                                                    body.get("new_password"), body.get("confirmation"))
                    else:
                        result = db.activate_key(token, self.headers.get("X-RMacro-Device"), body.get("key"), body.get("request_id"))
                except ApiError as exc:
                    if exc.code in ("WRONG_PASSWORD", "BAD_KEY", "KEY_NOT_FOUND"):
                        self.server.limiter.fail(key)
                    raise
                self.server.limiter.success(key)
                return self.send_json(200, result)
            if path == "/api/admin/logout":
                self.authenticate(admin=True)
                db.logout(self.token(), admin=True)
                return self.send_json(200, {"ok": True})
            if path == "/api/admin/users":
                actor = self.authenticate(admin=True)
                return self.send_json(201, db.create_user(actor["username"], body.get("username"), body.get("password")))
            if path == "/api/admin/games":
                actor = self.authenticate(admin=True)
                return self.send_json(201, db.create_game(actor["username"], body.get("code"), body.get("name")))
            if path == "/api/admin/products":
                actor = self.authenticate(admin=True)
                return self.send_json(201, db.create_product(actor["username"], body.get("code"), body.get("name"), body.get("game_code", "gta5")))
            if path == "/api/admin/keys":
                return self.send_json(201, db.create_key(self.token(), body))
            key_match = re.fullmatch(r"/api/admin/keys/([1-9][0-9]{0,18})/status", path)
            if key_match:
                key_id = int(key_match.group(1))
                if key_id > 9223372036854775807:
                    raise ApiError(404, "KEY_NOT_FOUND", "Ключ не найден.")
                return self.send_json(200, db.set_key_enabled(self.token(), key_id, body.get("enabled")))
            product_match = re.fullmatch(r"/api/admin/products/([a-z0-9][a-z0-9_.-]{0,47})", path)
            if product_match:
                actor = self.authenticate(admin=True)
                return self.send_json(200, db.update_product(actor["username"], product_match.group(1), body.get("name"), body.get("game_code")))
            match = re.fullmatch(r"/api/admin/users/([1-9][0-9]{0,18})/(reset-hwid|password|rename|status|grant|set|revoke)", path)
            if match:
                actor = self.authenticate(admin=True)
                uid = int(match.group(1))
                if uid > 9223372036854775807:
                    raise ApiError(404, "NOT_FOUND", "Пользователь не найден.")
                return self.send_json(200, db.change_user(actor["username"], uid, match.group(2), body))
        raise ApiError(404, "NOT_FOUND", "Страница или действие не найдены.")

    def dispatch(self):
        try:
            self.handle_request()
        except ApiError as exc:
            # Close after a rejected body so unread bytes cannot become a second request.
            self.close_connection = True
            self.send_json(exc.status, {"code": exc.code, "message": exc.message})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except Exception:
            self.close_connection = True
            traceback.print_exc()
            try:
                self.send_json(500, {"code": "SERVER_ERROR", "message": "Ошибка сервера. Проверьте журнал сервера."})
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass

    def do_GET(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch()


def loopback_bind(host):
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


LAN_V4_NETWORKS = tuple(ipaddress.ip_network(cidr) for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def lan_http_address(host):
    """HTTP is accepted only for loopback and literal RFC1918 IPv4 addresses.

    This is not a firewall or encryption: forwarding/NAT and untrusted local
    devices still require network isolation by the server owner.
    """
    if loopback_bind(host):
        return True
    try:
        address = ipaddress.ip_address(host)
        return isinstance(address, ipaddress.IPv4Address) and any(address in network for network in LAN_V4_NETWORKS)
    except ValueError:
        return False


# The address is embedded by the owner for convenience, not as a secret: it
# is necessarily observable in the user's client and network connection.
LOADER_CONFIG_MAGIC = b"RMACRO_URL_V1"
LOADER_CONFIG_MAX = 1024


def validate_loader_url(value):
    if not isinstance(value, str) or not value or len(value) > LOADER_CONFIG_MAX or not value.isascii():
        raise ValueError("Адрес должен быть полным ASCII URL; для домена используйте Punycode.")
    if any(ord(c) <= 32 or ord(c) == 127 for c in value) or "\\" in value:
        raise ValueError("Недопустимые символы в адресе сервера.")
    try:
        parsed = urlsplit(value)
        if (parsed.scheme.lower() not in ("http", "https") or not parsed.hostname or
                parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment or
                parsed.path not in ("", "/") or (parsed.port is not None and not 1 <= parsed.port <= 65535)):
            raise ValueError("Нужен адрес вида https://домен или http://127.0.0.1:8765 без пути и пароля.")
        if parsed.scheme.lower() == "http" and not lan_http_address(parsed.hostname):
            raise ValueError("HTTP разрешён только на localhost и частных IPv4-адресах LAN; для публичного адреса нужен HTTPS.")
    except ValueError as exc:
        raise ValueError(str(exc))
    return value.rstrip("/")


def configure_loader(source, destination, address):
    address = validate_loader_url(address)
    source, destination = Path(source).expanduser().resolve(), Path(destination).expanduser().resolve()
    if source == destination:
        raise ValueError("Исходный EXE и результат должны быть разными файлами.")
    content = source.read_bytes()
    marker_utf16 = LOADER_CONFIG_MAGIC.decode("ascii").encode("utf-16le")
    if not content.startswith(b"MZ") or marker_utf16 not in content:
        raise ValueError("Выберите EternalCore.exe с поддержкой настройки адреса.")
    footer_size = 4 + len(LOADER_CONFIG_MAGIC)
    if content.endswith(LOADER_CONFIG_MAGIC):
        if len(content) < footer_size:
            raise ValueError("Повреждённая настройка лоадера.")
        old_size = struct.unpack("<I", content[-footer_size:-len(LOADER_CONFIG_MAGIC)])[0]
        if old_size < 1 or old_size > LOADER_CONFIG_MAX or len(content) < footer_size + old_size:
            raise ValueError("Повреждённая настройка лоадера.")
        content = content[:-footer_size - old_size]
    payload = address.encode("ascii")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite an existing customer build or the original EXE.
    with destination.open("xb") as output:
        output.write(content)
        output.write(payload)
        output.write(struct.pack("<I", len(payload)))
        output.write(LOADER_CONFIG_MAGIC)
    return destination


def password_prompt():
    password = getpass.getpass("Пароль (не менее 12 символов): ")
    again = getpass.getpass("Повторите пароль: ")
    if password != again:
        raise ValueError("Пароли не совпадают.")
    return password


def main(argv=None):
    parser = argparse.ArgumentParser(description="Eternal Core server (Python 3.9+, no packages)")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-admin", help="Create the first administrator interactively")
    commands.add_parser("reset-admin", help="Reset an administrator password locally")
    configure = commands.add_parser("configure-client", help="Create a client EXE with the server URL embedded")
    configure.add_argument("--source", help="Original EternalCore.exe; prompted if omitted")
    configure.add_argument("--output", help="New EternalCore.exe path; prompted if omitted")
    configure.add_argument("--url", help="Server URL; prompted if omitted")
    backup = commands.add_parser("backup", help="Create a consistent SQLite backup")
    backup.add_argument("destination", nargs="?")
    serve = commands.add_parser("serve", help="Run the API and admin web UI")
    serve.add_argument("--host", default="192.168.0.105", help="Bind address; default is the owner's private LAN IPv4")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--allowed-host", action="append", default=[])
    serve.add_argument("--tls-cert", help="PEM certificate chain (required for public binding)")
    serve.add_argument("--tls-key", help="PEM private key (required for public binding)")
    args = parser.parse_args(argv)
    try:
        if args.command == "configure-client":
            source = args.source or input("Путь к распакованному EternalCore.exe: ").strip().strip('"')
            address = args.url or input("Адрес сервера (HTTP только в LAN, иначе HTTPS): ").strip()
            default_output = ROOT / "configured-client" / "EternalCore.exe"
            destination = args.output or input("Новый EXE (Enter: configured-client/EternalCore.exe): ").strip().strip('"') or str(default_output)
            configured = configure_loader(source, destination, address)
            print("Готово: " + str(configured))
            print("Замените EternalCore.exe в копии клиентского архива этим файлом, оставив аварийные BAT рядом.")
            print("Адрес не отображается в лоадере, но может быть обнаружен в клиенте или сети.")
            return 0
        database = Database(args.db)
        if args.command in ("init-admin", "reset-admin"):
            username = input("Логин администратора (латиница): ").strip()
            password = password_prompt()
            if args.command == "init-admin":
                database.init_admin(username, password)
            else:
                database.reset_admin(username, password)
            print("Готово. Пароль не сохранён в открытом виде.")
        elif args.command == "backup":
            destination = args.destination or str(ROOT / "data" / "backups" /
                ("rmacro-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S") + ".db"))
            print("Резервная копия: " + str(database.backup(destination)))
        else:
            if not database.has_admin():
                raise ValueError("Сначала запустите SETUP-ADMIN.bat и создайте администратора.")
            if not 1 <= args.port <= 65535:
                raise ValueError("Порт должен быть от 1 до 65535.")
            if bool(args.tls_cert) != bool(args.tls_key):
                raise ValueError("Нужны оба параметра: --tls-cert и --tls-key.")
            if not lan_http_address(args.host) and not args.tls_cert:
                raise ValueError("HTTP разрешён только на localhost и конкретном частном IPv4 LAN. Для публичного интерфейса нужен HTTPS.")
            allowed = ["localhost", "127.0.0.1", "::1", args.host] + args.allowed_host
            httpd = Server((args.host, args.port), database, allowed, lan_http_only=not bool(args.tls_cert))
            if args.tls_cert:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                context.load_cert_chain(args.tls_cert, args.tls_key)
                httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
            scheme = "https" if args.tls_cert else "http"
            print("Eternal Core server: %s://%s:%s/admin/" % (scheme, args.host, args.port), flush=True)
            if not args.tls_cert and not loopback_bind(args.host):
                print("ВНИМАНИЕ: HTTP в LAN не шифрует пароли, токены и ключи. Не открывайте порт в интернет.", flush=True)
            print("База: " + str(database.path), flush=True)
            print("Для остановки нажмите Ctrl+C. Не раздавайте базу и закрытый TLS-ключ.", flush=True)
            try:
                httpd.serve_forever(poll_interval=0.3)
            except KeyboardInterrupt:
                print("\nСервер остановлен.")
            finally:
                httpd.server_close()
        return 0
    except (ApiError, ValueError, OSError, ssl.SSLError) as exc:
        print("Ошибка: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    # On Windows an English console or redirected stdout can use a legacy
    # codepage that cannot encode Russian messages. Do not fail after a file
    # or database operation just because a status message cannot be printed.
    # The supplied BAT files use UTF-8; legacy redirections get escaped text.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, OSError, ValueError):
            pass
    sys.exit(main())
