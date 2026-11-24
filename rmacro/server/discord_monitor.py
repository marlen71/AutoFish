#!/usr/bin/env python3
"""Independent Eternal Core status and release monitor (Python 3.9+).

Run exactly one copy on a machine independent of the server being monitored.
Webhook credentials are read only from an owner-protected local configuration;
never put them in source control, a client build, or command-line arguments.
"""
import argparse
import contextlib
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

STATUSES = {"UPDATED", "ON UPDATE", "AT YOUR OWN RISK", "OUTDATED"}
RELEASE_API = "https://api.github.com/repos/marlen71/AutoFish/releases?per_page=100&page="
WEBHOOK = re.compile(r"^/api/webhooks/([0-9]{5,25})/([A-Za-z0-9._-]{20,200})$")
MESSAGE_ID = re.compile(r"^[0-9]{5,25}$")
VERSION = re.compile(r"^(eternal-core|rmfish-product)-v(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})$")
MAX_RESPONSE = 8 * 1024 * 1024
MAX_ASSET = 50 * 1024 * 1024


def validated_webhook(value):
    if not isinstance(value, str) or len(value) > 350:
        raise ValueError("Некорректный URL Discord webhook.")
    try:
        u = urllib.parse.urlsplit(value)
        valid = (u.scheme == "https" and u.hostname == "discord.com" and u.port in (None, 443)
                 and not u.username and not u.password and not u.query and not u.fragment
                 and WEBHOOK.fullmatch(u.path))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Webhook должен быть полным HTTPS-адресом discord.com/api/webhooks/… без параметров.")
    return value


def validated_status_url(value):
    if not isinstance(value, str) or len(value) > 1000:
        raise ValueError("Некорректный адрес статуса сервера.")
    try:
        u = urllib.parse.urlsplit(value)
        local = u.hostname == "localhost"
        try:
            local = local or ipaddress.ip_address(u.hostname).is_loopback
        except ValueError:
            pass
        valid = (u.scheme in ("http", "https") and u.hostname and
                 (u.scheme == "https" or local) and u.port != 0 and
                 not u.username and not u.password and not u.query and not u.fragment and u.path == "/api/status")
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Нужен HTTPS-адрес сервера, заканчивающийся /api/status (HTTP только для localhost).")
    return value


def read_configuration(path):
    path = Path(path).expanduser().resolve()
    with path.open("r", encoding="utf-8") as stream:
        config = json.load(stream)
    if not isinstance(config, dict):
        raise ValueError("Настройки должны быть JSON-объектом.")
    status_hook = validated_webhook(config.get("status_webhook"))
    update_hook = validated_webhook(config.get("update_webhook"))
    if status_hook == update_hook:
        raise ValueError("Для статуса и обновлений нужны два разных webhook.")
    url = validated_status_url(config.get("status_url"))
    interval = config.get("interval_seconds", 60)
    if type(interval) is not int or not 15 <= interval <= 3600:
        raise ValueError("Интервал проверки должен быть от 15 до 3600 секунд.")
    ca = config.get("server_ca_file")
    if ca is not None and (not isinstance(ca, str) or not ca.strip()):
        raise ValueError("server_ca_file должен быть путём к публичному CA или null.")
    if ca:
        ca = Path(ca).expanduser()
        if not ca.is_absolute():
            ca = path.parent / ca
        ca = str(ca.resolve())
        if urllib.parse.urlsplit(url).scheme != "https":
            raise ValueError("Сертификат CA можно использовать только с HTTPS.")
    return {"status_webhook": status_hook, "update_webhook": update_hook, "status_url": url,
            "interval_seconds": interval, "server_ca_file": ca, "config_path": path}


def version_tuple(tag):
    match = VERSION.fullmatch(tag or "")
    if not match:
        return None
    numbers = tuple(int(n) for n in match.groups()[1:])
    if any(n > 65535 for n in numbers):
        return None
    return numbers


def select_releases(pages):
    """Choose only published stable releases with a unique, digest-bearing asset."""
    selected = {}
    for releases in pages:
        if not isinstance(releases, list) or len(releases) > 100:
            raise ValueError("Некорректный список релизов.")
        for release in releases:
            if not isinstance(release, dict) or release.get("draft") is not False or release.get("prerelease") is not False:
                continue
            tag = release.get("tag_name")
            if not isinstance(tag, str):
                continue
            parsed = version_tuple(tag)
            if parsed is None:
                continue
            kind = "loader" if tag.startswith("eternal-core-") else "rmfish"
            expected = "EternalCore.exe" if kind == "loader" else "RMFishProduct.dll"
            assets = release.get("assets")
            if not isinstance(assets, list) or len(assets) > 200:
                continue
            matches = [a for a in assets if isinstance(a, dict) and a.get("name") == expected]
            if len(matches) != 1:
                continue
            asset = matches[0]
            if (type(asset.get("size")) is not int or not 0 < asset["size"] <= MAX_ASSET or
                    not isinstance(asset.get("digest"), str) or
                    not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", asset["digest"])):
                continue
            if kind not in selected or parsed > version_tuple(selected[kind]):
                selected[kind] = tag
    return selected


def validated_snapshot(data):
    if not isinstance(data, dict) or data.get("ok") is not True or not isinstance(data.get("products"), list):
        raise ValueError("Некорректный ответ статуса.")
    if len(data["products"]) > 100:
        raise ValueError("Слишком много продуктов.")
    total = data.get("total_products", len(data["products"]))
    if type(total) is not int or total < len(data["products"]) or total > 2_147_483_647:
        raise ValueError("Некорректное число продуктов.")
    result, codes = [], set()
    for p in data["products"]:
        if not isinstance(p, dict):
            raise ValueError("Некорректный продукт.")
        code, name, game, status = p.get("code"), p.get("name"), p.get("game_name"), p.get("status")
        if (not isinstance(code, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,47}", code) or code in codes or
                not isinstance(name, str) or not 1 <= len(name) <= 80 or
                not isinstance(game, str) or not 1 <= len(game) <= 80 or status not in STATUSES):
            raise ValueError("Некорректный продукт или статус.")
        codes.add(code)
        result.append({"code": code, "name": name, "game_name": game, "status": status})
    return result


def safe_text(value):
    # Text comes from an admin-controlled catalog. Prevent mentions, multiline
    # spoofing and Discord markdown from changing the meaning of status lines.
    clean = " ".join(str(value).split())
    clean = "".join(c for c in clean if ord(c) >= 32 and ord(c) != 127)
    clean = clean.replace("@", "@\u200b")
    return re.sub(r"([\\`*_~|>\[\]()#])", r"\\\1", clean)


def discord_length(text):
    # Discord/JavaScript can count a non-BMP character as two UTF-16 units.
    return len(text.encode("utf-16-le", errors="surrogatepass")) // 2


def status_payload(online, products, loader_tag, omitted_products=0):
    shown = loader_tag[len("eternal-core-v"):] if isinstance(loader_tag, str) and version_tuple(loader_tag) else "неизвестна"
    lines = ["**Сервер:** " + ("🟢 Online" if online else "🔴 Offline"),
             "**Версия лоадера:** `" + shown + "`", "", "**Продукты**"]
    # Discord limits a message's combined embed text to 6000 characters. Keep
    # a clear truncation indicator rather than posting additional messages.
    max_chars, omitted = 3900, omitted_products
    for product in products:
        line = "• " + safe_text(product["name"]) + " · **" + product["status"] + "**"
        if sum(discord_length(s) + 1 for s in lines) + discord_length(line) > max_chars:
            omitted += 1
        else:
            lines.append(line)
    if not products:
        lines.append("Пока нет данных о продуктах.")
    if omitted:
        lines.append("…и ещё %d продуктов." % omitted)
    return {"allowed_mentions": {"parse": []}, "embeds": [{"title": "✦ ETERNAL CORE",
        "description": "\n".join(lines), "color": 0x35c4b3 if online else 0xe25159,
        "footer": {"text": "Доступность с точки наблюдателя · статусы продуктов задаёт администратор"}}]}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Transport:
    def __init__(self, config):
        self.config = config
        self.normal = urllib.request.build_opener(NoRedirect())
        context = ssl.create_default_context(cafile=config["server_ca_file"]) if config["server_ca_file"] else ssl.create_default_context()
        self.server = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context))

    @staticmethod
    def _json(opener, url, method="GET", body=None, maximum=MAX_RESPONSE):
        data = None if body is None else json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {"User-Agent": "EternalCore-StatusMonitor/1", "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with opener.open(request, timeout=10) as response:
                raw = response.read(maximum + 1)
                if len(raw) > maximum:
                    raise ValueError("Слишком большой ответ.")
                return response.status, json.loads(raw.decode("utf-8")) if raw else None
        except urllib.error.HTTPError as exc:
            # Never expose the URL or HTTP response in logs: a webhook URL is
            # a bearer credential. Status alone is enough for retry decisions.
            return exc.code, None

    def status(self):
        # 100 max-length Unicode names can exceed 64 KiB after JSON encoding.
        code, body = self._json(self.server, self.config["status_url"], maximum=256 * 1024)
        if code != 200:
            raise ValueError("Сервер не вернул статус.")
        validated_snapshot(body)
        return body

    def releases(self):
        pages = []
        for page in range(1, 4):
            code, body = self._json(self.normal, RELEASE_API + str(page))
            if code != 200 or not isinstance(body, list) or len(body) > 100:
                raise ValueError("GitHub не вернул список релизов.")
            pages.append(body)
            if len(body) < 100:
                break
        return select_releases(pages)

    def webhook(self, hook, method, payload=None, message_id=None):
        suffix = "/messages/" + message_id if message_id else ""
        query = "?wait=true" if method == "POST" else ""
        return self._json(self.normal, hook + suffix + query, method, payload, maximum=65536)


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), prefix=".discord-state-", delete=False) as output:
            temp = output.name
            json.dump(data, output, ensure_ascii=False, separators=(",", ":"))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, str(path))
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)


def initial_state(hook):
    return {"schema": 1, "hook_id": hashlib.sha256(hook.encode("utf-8")).hexdigest(),
            "message_id": None, "create_pending": False, "products": [], "omitted_products": 0,
            "releases": {}, "announced": {}}


def load_state(path, hook):
    if not Path(path).exists():
        return initial_state(hook)
    with open(path, "r", encoding="utf-8") as stream:
        state = json.load(stream)
    if not isinstance(state, dict) or state.get("schema") != 1:
        raise ValueError("Неизвестный файл состояния Discord; не удаляйте его без проверки канала.")
    if state.get("hook_id") != hashlib.sha256(hook.encode("utf-8")).hexdigest():
        # The old token is intentionally not saved. A rotated webhook cannot
        # delete a message belonging to the old one; owner must remove it.
        print("Webhook статуса изменён: удалите старое сообщение вручную, если оно осталось.", file=sys.stderr)
        return initial_state(hook)
    mid = state.get("message_id")
    if (mid is not None and (not isinstance(mid, str) or not MESSAGE_ID.fullmatch(mid))) or type(state.get("create_pending")) is not bool:
        raise ValueError("Повреждён файл состояния Discord; проверьте канал до восстановления.")
    if not isinstance(state.get("releases"), dict) or not isinstance(state.get("announced"), dict):
        raise ValueError("Повреждён файл состояния обновлений.")
    for name in ("releases", "announced"):
        for key, tag in state[name].items():
            if key not in ("loader", "rmfish") or version_tuple(tag) is None or not tag.startswith("eternal-core-" if key == "loader" else "rmfish-product-"):
                raise ValueError("Повреждён файл состояния обновлений.")
    state["products"] = validated_snapshot({"ok": True, "products": state.get("products")})
    omitted = state.get("omitted_products", 0)  # compatible with earlier state files
    if type(omitted) is not int or omitted < 0 or omitted > 2_147_483_647 - len(state["products"]):
        raise ValueError("Повреждено число продуктов в файле состояния.")
    state["omitted_products"] = omitted
    return state


class Monitor:
    def __init__(self, config, state_path, transport):
        self.config, self.state_path, self.transport = config, Path(state_path), transport
        self.state = load_state(self.state_path, config["status_webhook"])
        self.rotating = True
        self.online = None
        self.failures = 0
        self.last_payload = None
        self.creation_uncertain_reported = False

    def save(self):
        atomic_json(self.state_path, self.state)

    def _status_message(self, payload):
        state, hook = self.state, self.config["status_webhook"]
        if self.rotating and state["message_id"]:
            try:
                code, _ = self.transport.webhook(hook, "DELETE", message_id=state["message_id"])
            except Exception:
                return
            if code not in (200, 204, 404):
                return
            state["message_id"] = None
            self.save()
        if not state["message_id"]:
            if state["create_pending"]:
                if not self.creation_uncertain_reported:
                    print("Результат создания сообщения неизвестен: проверьте канал и файл состояния; автоматический повтор запрещён.", file=sys.stderr)
                    self.creation_uncertain_reported = True
                return
            # Save intent before POST: after a crash or lost response we cannot
            # know if Discord accepted the message, so never blindly retry.
            state["create_pending"] = True
            self.save()
            try:
                code, response = self.transport.webhook(hook, "POST", payload)
            except Exception:
                return
            if code in (400, 401, 403, 404, 429):
                state["create_pending"] = False
                self.save()
                return
            mid = response.get("id") if isinstance(response, dict) else None
            if code not in (200, 201) or not isinstance(mid, str) or not MESSAGE_ID.fullmatch(mid):
                return  # ambiguous delivery: keep create_pending
            state["message_id"], state["create_pending"] = mid, False
            self.save()
            self.last_payload, self.rotating = payload, False
            return
        self.rotating = False
        if self.last_payload == payload:
            return
        try:
            code, _ = self.transport.webhook(hook, "PATCH", payload, state["message_id"])
        except Exception:
            return
        if code in (200, 204):
            self.last_payload = payload
        elif code == 404:
            state["message_id"] = None
            self.save()
            self.last_payload = None

    def _update_logs(self, releases):
        for kind in ("loader", "rmfish"):
            tag = releases.get(kind)
            if not tag:
                continue
            previous = self.state["announced"].get(kind)
            if previous is None:
                # First start establishes a baseline rather than replaying all
                # old releases. Future strictly newer releases get one log.
                self.state["announced"][kind] = tag
                self.save()
                continue
            if version_tuple(tag) <= version_tuple(previous):
                continue
            # At-most-once on ambiguous network failure: record before sending
            # rather than flooding the channel after a lost HTTP response.
            self.state["announced"][kind] = tag
            self.save()
            version = tag.split("-v", 1)[1]
            text = "📦 " + ("Eternal Core" if kind == "loader" else "RMFish") + " v" + version + " — опубликовано обновление."
            try:
                code, _ = self.transport.webhook(self.config["update_webhook"], "POST",
                    {"content": text, "allowed_mentions": {"parse": []}})
                if code in (400, 401, 403, 404, 429):
                    # Discord explicitly rejected the request; unlike a lost
                    # response, it is safe to retry on a later poll.
                    self.state["announced"][kind] = previous
                    self.save()
                elif code not in (200, 201, 204):
                    print("Не удалось подтвердить доставку краткого лога обновления.", file=sys.stderr)
            except Exception:
                print("Не удалось подтвердить доставку краткого лога обновления.", file=sys.stderr)

    def tick(self):
        try:
            snapshot = self.transport.status()
            products = validated_snapshot(snapshot)
            self.state["products"] = products
            self.state["omitted_products"] = snapshot.get("total_products", len(products)) - len(products)
            self.failures, self.online = 0, True
        except Exception:
            self.failures += 1
            if self.online is None or self.failures >= 2:
                self.online = False
        try:
            releases = self.transport.releases()
            # Validate even injected transports: state may be persisted.
            if not isinstance(releases, dict):
                raise ValueError("Некорректные релизы.")
            for kind, tag in releases.items():
                if kind not in ("loader", "rmfish") or version_tuple(tag) is None or not tag.startswith("eternal-core-" if kind == "loader" else "rmfish-product-"):
                    raise ValueError("Некорректные релизы.")
            self.state["releases"].update(releases)
            self._update_logs(releases)
        except Exception:
            pass  # keep last known version; do not claim a new release
        self.save()
        payload = status_payload(bool(self.online), self.state["products"], self.state["releases"].get("loader"),
                                 self.state["omitted_products"])
        self._status_message(payload)


@contextlib.contextmanager
def single_instance(path):
    """Best-effort local OS lock; do not configure this webhook on two hosts."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise ValueError("Другой наблюдатель уже запущен с этим файлом состояния.")
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ValueError("Другой наблюдатель уже запущен с этим файлом состояния.")
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Independent Eternal Core Discord monitor")
    parser.add_argument("--config", required=True, help="Path to a private local JSON configuration")
    args = parser.parse_args(argv)
    try:
        config = read_configuration(args.config)
        state = config["config_path"].with_name("discord-monitor-state.json")
        with single_instance(state.with_suffix(".lock")):
            monitor = Monitor(config, state, Transport(config))
            print("Наблюдатель запущен. Для Offline при выключении сервера он должен работать на другом устройстве.", flush=True)
            while True:
                monitor.tick()
                time.sleep(config["interval_seconds"])
    except KeyboardInterrupt:
        print("\nНаблюдатель остановлен.")
        return 0
    except Exception as exc:
        # Do not print exception values from networking: they may include the
        # bearer webhook URL. The generic failure is deliberately secret-free.
        print("Наблюдатель не запущен: проверьте локальные настройки, CA и права на файлы (" + type(exc).__name__ + ").", file=sys.stderr)
        return 1


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="backslashreplace")
        except (AttributeError, OSError, ValueError):
            pass
    sys.exit(main())
