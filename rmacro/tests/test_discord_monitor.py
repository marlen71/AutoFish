"""No real Discord hooks or network: monitor state-machine and privacy tests."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[1] / "server" / "discord_monitor.py"
spec = importlib.util.spec_from_file_location("discord_monitor", PATH)
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)

STATUS_HOOK = "https://discord.com/api/webhooks/12345678901234567/" + "a" * 32
UPDATE_HOOK = "https://discord.com/api/webhooks/23456789012345678/" + "b" * 32


def release(tag, name, draft=False, preview=False, digest=None):
    return {"tag_name": tag, "draft": draft, "prerelease": preview, "assets": [{
        "name": name, "size": 100, "digest": digest or "sha256:" + "d" * 64}]}


class FakeTransport:
    def __init__(self):
        self.products = [{"code": "rmfish", "name": "RMFish", "game_name": "GTA5", "status": "UPDATED"}]
        self.versions = {"loader": "eternal-core-v1.3.0", "rmfish": "rmfish-product-v1.29.0"}
        self.messages, self.calls = {}, []
        self.next_id = 100000
        self.offline = False
        self.create_ambiguous = False
        self.create_rejected = False
        self.update_results = []
        self.total_products = None

    def status(self):
        if self.offline:
            raise OSError("offline")
        return {"ok": True, "products": self.products,
                "total_products": len(self.products) if self.total_products is None else self.total_products}

    def releases(self):
        return dict(self.versions)

    def webhook(self, hook, method, payload=None, message_id=None):
        self.calls.append((hook, method, payload, message_id))
        if hook == UPDATE_HOOK:
            if self.update_results:
                result = self.update_results.pop(0)
                if isinstance(result, Exception):
                    raise result
                return result, None
            return 204, None
        if method == "POST":
            if self.create_rejected:
                self.create_rejected = False
                return 429, None
            self.next_id += 1
            mid = str(self.next_id)
            self.messages[mid] = payload
            if self.create_ambiguous:
                raise TimeoutError("response lost")
            return 200, {"id": mid}
        if method == "DELETE":
            if self.messages.pop(message_id, None) is None:
                return 404, None
            return 204, None
        if method == "PATCH":
            if message_id not in self.messages:
                return 404, None
            self.messages[message_id] = payload
            return 200, {"id": message_id}
        raise AssertionError(method)


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temp.name) / "private-state.json"
        self.config = {"status_webhook": STATUS_HOOK, "update_webhook": UPDATE_HOOK}
        self.fake = FakeTransport()
        self.instance = monitor.Monitor(self.config, self.state_path, self.fake)

    def tearDown(self):
        self.temp.cleanup()

    def test_one_message_is_edited_and_restart_deletes_then_recreates(self):
        self.instance.tick()
        self.assertEqual(len(self.fake.messages), 1)
        first = next(iter(self.fake.messages))
        desc = self.fake.messages[first]["embeds"][0]["description"]
        self.assertIn("Online", desc)
        self.assertIn("1.3.0", desc)
        self.assertIn("RMFish", desc)
        self.assertIn("UPDATED", desc)
        calls = len(self.fake.calls)
        self.instance.tick()
        self.assertEqual(len(self.fake.calls), calls, "identical checks do not edit or post")
        self.fake.products[0]["status"] = "ON UPDATE"
        self.instance.tick()
        self.assertEqual(list(self.fake.messages), [first])
        self.assertIn("ON UPDATE", self.fake.messages[first]["embeds"][0]["description"])
        self.assertEqual(self.fake.calls[-1][1], "PATCH")
        # A single failed probe doesn't flap an already-online service.
        self.fake.offline = True
        self.instance.tick()
        self.assertIn("Online", self.fake.messages[first]["embeds"][0]["description"])
        self.instance.tick()
        self.assertIn("Offline", self.fake.messages[first]["embeds"][0]["description"])
        self.assertIn("ON UPDATE", self.fake.messages[first]["embeds"][0]["description"], "last catalog is retained offline")
        self.fake.offline = False
        self.instance.tick()
        self.assertIn("Online", self.fake.messages[first]["embeds"][0]["description"])
        restarted = monitor.Monitor(self.config, self.state_path, self.fake)
        before = len(self.fake.calls)
        restarted.tick()
        self.assertEqual([c[1] for c in self.fake.calls[before:] if c[0] == STATUS_HOOK], ["DELETE", "POST"])
        self.assertEqual(len(self.fake.messages), 1)
        self.assertNotEqual(next(iter(self.fake.messages)), first)
        stored = self.state_path.read_text(encoding="utf-8")
        self.assertNotIn(STATUS_HOOK, stored)
        self.assertNotIn(UPDATE_HOOK, stored)

    def test_initial_release_baseline_then_short_only_new_release_logs(self):
        self.instance.tick()
        self.assertEqual([c for c in self.fake.calls if c[0] == UPDATE_HOOK], [])
        self.fake.versions = {"loader": "eternal-core-v1.4.0", "rmfish": "rmfish-product-v1.30.0"}
        self.instance.tick()
        logs = [c for c in self.fake.calls if c[0] == UPDATE_HOOK]
        self.assertEqual(len(logs), 2)
        self.assertIn("Eternal Core v1.4.0", logs[0][2]["content"])
        self.assertIn("RMFish v1.30.0", logs[1][2]["content"])
        self.assertTrue(all(len(c[2]["content"]) < 100 and c[2]["allowed_mentions"] == {"parse": []} for c in logs))
        self.instance.tick()
        self.assertEqual(len([c for c in self.fake.calls if c[0] == UPDATE_HOOK]), 2)
        self.fake.versions["loader"] = "eternal-core-v1.3.0"
        self.instance.tick()
        self.assertEqual(len([c for c in self.fake.calls if c[0] == UPDATE_HOOK]), 2, "rollback is not announced as an update")

    def test_explicit_update_rejections_are_retried_without_duplicate_success(self):
        for rejection in (400, 401, 403, 404, 429):
            with self.subTest(status=rejection), tempfile.TemporaryDirectory() as folder:
                fake = FakeTransport()
                instance = monitor.Monitor(self.config, Path(folder) / "state.json", fake)
                instance.tick()  # establish baseline
                fake.versions["loader"] = "eternal-core-v1.4.0"
                fake.update_results = [rejection]
                instance.tick()
                self.assertEqual(instance.state["announced"]["loader"], "eternal-core-v1.3.0")
                instance.tick()  # retry receives 204
                instance.tick()
                attempts = [c for c in fake.calls if c[0] == UPDATE_HOOK]
                self.assertEqual(len(attempts), 2)
                self.assertEqual(instance.state["announced"]["loader"], "eternal-core-v1.4.0")

    def test_ambiguous_update_is_not_resent_after_restart(self):
        self.instance.tick()
        self.fake.versions["loader"] = "eternal-core-v1.4.0"
        self.fake.update_results = [TimeoutError("unknown result")]
        self.instance.tick()
        restarted = monitor.Monitor(self.config, self.state_path, self.fake)
        restarted.tick()
        self.assertEqual(len([c for c in self.fake.calls if c[0] == UPDATE_HOOK]), 1)
        self.assertEqual(restarted.state["announced"]["loader"], "eternal-core-v1.4.0")

    def test_omitted_server_products_are_visible_and_survive_offline(self):
        self.fake.total_products = 112
        self.instance.tick()
        mid = next(iter(self.fake.messages))
        self.assertIn("…и ещё 111 продуктов.", self.fake.messages[mid]["embeds"][0]["description"])
        self.fake.offline = True
        restarted = monitor.Monitor(self.config, self.state_path, self.fake)
        restarted.tick()
        mid = next(iter(self.fake.messages))
        self.assertIn("Offline", self.fake.messages[mid]["embeds"][0]["description"])
        self.assertIn("…и ещё 111 продуктов.", self.fake.messages[mid]["embeds"][0]["description"])
        bad = {"ok": True, "products": self.fake.products, "total_products": 0}
        with self.assertRaises(ValueError):
            monitor.validated_snapshot(bad)
        many_emoji = [{"code": str(i), "name": "🎣" * 80, "game_name": "GTA5", "status": "UPDATED"} for i in range(100)]
        desc = monitor.status_payload(True, many_emoji, "eternal-core-v1.3.0")["embeds"][0]["description"]
        self.assertLessEqual(monitor.discord_length(desc), 4096)
        self.assertIn("…и ещё", desc)

    def test_ambiguous_creation_never_retries_or_duplicates_after_restart(self):
        self.fake.create_ambiguous = True
        self.instance.tick()
        self.assertEqual(len(self.fake.messages), 1)
        self.assertTrue(json.loads(self.state_path.read_text())["create_pending"])
        self.fake.create_ambiguous = False
        restarted = monitor.Monitor(self.config, self.state_path, self.fake)
        restarted.tick()
        restarted.tick()
        self.assertEqual(len(self.fake.messages), 1)
        self.assertEqual(len([c for c in self.fake.calls if c[0] == STATUS_HOOK and c[1] == "POST"]), 1)

    def test_explicit_429_creates_once_after_retry(self):
        self.fake.create_rejected = True
        self.instance.tick()
        self.assertFalse(json.loads(self.state_path.read_text())["create_pending"])
        self.instance.tick()
        self.assertEqual(len(self.fake.messages), 1)

    def test_deleted_message_is_recreated_without_spam(self):
        self.instance.tick()
        old = next(iter(self.fake.messages))
        del self.fake.messages[old]
        self.fake.products[0]["status"] = "OUTDATED"
        self.instance.tick()  # PATCH 404
        self.instance.tick()  # new POST
        self.assertEqual(len(self.fake.messages), 1)
        self.assertNotEqual(next(iter(self.fake.messages)), old)

    def test_public_snapshot_and_rendering_reject_malicious_content(self):
        data = {"ok": True, "products": [{"code": "rmfish", "name": "@everyone\n**hi**", "game_name": "GTA5", "status": "UPDATED"}]}
        p = monitor.validated_snapshot(data)
        payload = monitor.status_payload(True, p, "eternal-core-v1.3.0")
        desc = payload["embeds"][0]["description"]
        self.assertNotIn("@everyone", desc)
        self.assertNotIn("\n**hi**", desc)
        self.assertIn("\\*\\*hi\\*\\*", desc)
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        data["products"][0]["status"] = "ONLINE"
        with self.assertRaises(ValueError):
            monitor.validated_snapshot(data)

    def test_release_selection_excludes_other_assets_preview_and_untrusted_metadata(self):
        items = [release("eternal-core-v1.3.0", "EternalCore.exe"),
                 release("eternal-core-v9.0.0", "EternalCore.exe", preview=True),
                 release("eternal-core-v8.0.0", "other.exe"),
                 release("eternal-core-v02.0.0", "EternalCore.exe"),
                 release("rmfish-product-v1.30.0", "RMFishProduct.dll"),
                 release("rmfish-product-v99.0.0", "RMFishProduct.dll", digest="md5:bad")]
        self.assertEqual(monitor.select_releases([items]), {"loader": "eternal-core-v1.3.0", "rmfish": "rmfish-product-v1.30.0"})
        self.assertIsNone(monitor.version_tuple("eternal-core-v65536.0.0"))

    def test_url_validation_rejects_embedded_secrets_plaintext_and_lookalike_hosts(self):
        self.assertEqual(monitor.validated_webhook(STATUS_HOOK), STATUS_HOOK)
        for url in [STATUS_HOOK.replace("https:", "http:"), STATUS_HOOK.replace("discord.com", "discord.com.evil.test"),
                    STATUS_HOOK + "?secret=x", STATUS_HOOK.replace("discord.com", "user@discord.com")]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                monitor.validated_webhook(url)
        self.assertEqual(monitor.validated_status_url("https://example.com/api/status"), "https://example.com/api/status")
        self.assertEqual(monitor.validated_status_url("http://127.0.0.1:8765/api/status"), "http://127.0.0.1:8765/api/status")
        for url in ["http://example.com/api/status", "https://example.com/api/status?secret=x", "https://u:p@example.com/api/status"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                monitor.validated_status_url(url)


if __name__ == "__main__":
    unittest.main()
