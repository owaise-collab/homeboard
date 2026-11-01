"""Meaningful persistence, permission and recovery checks; no third-party packages."""
import copy
import http.client
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("family_server_under_test", ROOT / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

KEY = "test-setup-key-with-enough-entropy"
PASSWORD = "An example family passphrase!"


def temporary_folder():
    # Some managed Windows profiles allow SQLite only inside the workspace.
    base = ROOT / "tests" / ".temporary"
    base.mkdir(exist_ok=True)
    result = tempfile.TemporaryDirectory(dir=base)
    assert Path(result.name).resolve().is_relative_to(ROOT.resolve())
    return result


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.folder = temporary_folder()
        # Production uses 2**17; reduce only test hashing cost, never the application.
        self.scrypt_patch = patch.object(server, "SCRYPT_N", 2 ** 14)
        self.scrypt_patch.start()
        self.store = server.FamilyStore(self.folder.name, KEY)

    def tearDown(self):
        self.scrypt_patch.stop()
        self.folder.cleanup()

    def owner(self):
        return self.store.create_user("Owner", "owner", PASSWORD, "admin", first=True, setup_key=KEY)

    def setup_details(self, **overrides):
        return {"setupKey": KEY, "name": "Alex", "username": "alex", "password": PASSWORD,
                "household": {"name": "The Rowan household", "timezone": "UTC", "hour24": False, "theme": "premium"},
                "members": [{"name": "Jordan", "color": "rose"}], **overrides}

    def test_fresh_install_has_only_generic_defaults(self):
        state = self.store.get_state()["state"]
        self.assertEqual(state["members"], [{"id": "family", "name": "Family", "color": "sage"}])
        self.assertEqual(state["preferences"]["timezone"], "UTC")
        self.assertEqual(state["preferences"]["theme"], "premium")
        self.assertEqual(state["preferences"]["household"], "Our home")
        self.assertTrue(state["preferences"]["hour24"])
        for collection in ("events", "tasks", "items", "notes"):
            self.assertEqual(state[collection], [])
        self.assertEqual(state["meals"], {})
        self.assertFalse(self.store.initialized())

    def test_atomic_setup_creates_owner_household_profiles_and_hashed_recovery(self):
        user, code = self.store.setup_household(self.setup_details())
        state = self.store.get_state()
        self.assertEqual(state["revision"], 1)
        self.assertEqual(state["state"]["preferences"]["household"], "The Rowan household")
        self.assertFalse(state["state"]["preferences"]["hour24"])
        self.assertEqual([member["name"] for member in state["state"]["members"]], ["Family", "Alex", "Jordan"])
        self.assertEqual(self.store.login("alex", PASSWORD)["id"], user["id"])
        with self.store.connect() as db:
            record = db.execute("SELECT code_hash FROM recovery_codes WHERE user_id=?", (user["id"],)).fetchone()
            self.assertEqual(record["code_hash"], server.recovery_digest(code))
            self.assertNotIn(code, json.dumps(dict(record)))
        self.assertTrue(code.startswith("HBR-"))
        self.assertGreaterEqual(len(code), 50)
        with self.assertRaises(server.APIError):
            self.store.setup_household(self.setup_details())

    def test_invalid_setup_never_claims_owner_or_changes_household(self):
        before = self.store.get_state()
        cases = [
            self.setup_details(setupKey=""),
            self.setup_details(setupKey="wrong"),
            self.setup_details(password="short"),
            self.setup_details(household={"name": "Home", "timezone": "Not/A_Zone"}),
            self.setup_details(members=[{"name": "Child", "color": "invalid"}]),
            self.setup_details(members=[{"name": "Member"}] * 13),
            self.setup_details(household={"name": "Home", "hour24": "false"}),
        ]
        for details in cases:
            with self.subTest(details=list(details.keys())):
                with self.assertRaises(server.APIError):
                    self.store.setup_household(details)
                self.assertFalse(self.store.initialized())
                self.assertEqual(self.store.get_state(), before)
                with self.store.connect() as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM recovery_codes").fetchone()[0], 0)

    def test_setup_database_failure_rolls_back_owner_and_recovery_code(self):
        before = self.store.get_state()
        with self.store.connect() as db:
            db.execute("CREATE TRIGGER block_setup BEFORE UPDATE ON household BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.setup_household(self.setup_details())
        self.assertFalse(self.store.initialized())
        self.assertEqual(self.store.get_state(), before)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM recovery_codes").fetchone()[0], 0)

    def test_competing_first_run_claims_have_exactly_one_complete_winner(self):
        barrier, outcomes = threading.Barrier(2), []
        def claim(username):
            barrier.wait()
            try:
                self.store.setup_household(self.setup_details(username=username, name=username))
                outcomes.append(201)
            except server.APIError as error:
                outcomes.append(error.status)
        workers = [threading.Thread(target=claim, args=(name,)) for name in ("first", "second")]
        for worker in workers: worker.start()
        for worker in workers: worker.join(timeout=10)
        self.assertEqual(sorted(outcomes), [201, 409])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM recovery_codes").fetchone()[0], 1)
        self.assertEqual(self.store.get_state()["revision"], 1)

    def test_recovery_is_single_use_revokes_sessions_and_rotates_only_hashed_code(self):
        user, code = self.store.setup_household(self.setup_details())
        session = self.store.new_session(user["id"])
        self.assertIsNotNone(self.store.session(session))
        new_password = "A new household passphrase!"
        with self.assertRaises(server.APIError):
            self.store.recover_account("alex", "wrong", new_password)
        self.assertIsNotNone(self.store.session(session))
        rotated = self.store.recover_account("alex", code.lower(), new_password)
        self.assertNotEqual(code, rotated)
        self.assertIsNone(self.store.session(session))
        self.assertEqual(self.store.login("alex", new_password)["id"], user["id"])
        with self.assertRaises(server.APIError): self.store.login("alex", PASSWORD)
        with self.assertRaises(server.APIError): self.store.recover_account("alex", code, PASSWORD)
        with self.assertRaises(server.APIError): self.store.recover_account("missing", rotated, PASSWORD)
        with self.store.connect() as db:
            stored = db.execute("SELECT code_hash FROM recovery_codes").fetchone()[0]
        self.assertEqual(stored, server.recovery_digest(rotated))
        self.assertNotIn(rotated, stored)

    def test_recovery_rotation_checks_current_password_and_invalidates_previous_kit(self):
        user, code = self.store.setup_household(self.setup_details())
        with self.assertRaises(server.APIError):
            self.store.rotate_recovery_code(user["id"], "wrong")
        fresh = self.store.rotate_recovery_code(user["id"], PASSWORD)
        with self.assertRaises(server.APIError):
            self.store.recover_account("alex", code, PASSWORD)
        self.assertNotEqual(self.store.recover_account("alex", fresh, PASSWORD), fresh)
        adult = self.store.create_user("Adult", "adult", PASSWORD)
        with self.assertRaises(server.APIError):
            self.store.rotate_recovery_code(adult["id"], PASSWORD)

    def test_competing_recovery_attempts_can_use_a_kit_only_once(self):
        unused, code = self.store.setup_household(self.setup_details())
        barrier, outcomes = threading.Barrier(2), []
        def recover():
            barrier.wait()
            try:
                self.store.recover_account("alex", code, PASSWORD)
                outcomes.append(200)
            except server.APIError as error:
                outcomes.append(error.status)
        workers = [threading.Thread(target=recover) for _ in range(2)]
        for worker in workers: worker.start()
        for worker in workers: worker.join(timeout=10)
        self.assertEqual(sorted(outcomes), [200, 401])

    def test_upgrading_existing_database_keeps_records_accounts_and_sessions(self):
        owner = self.owner()
        state = self.store.get_state()
        state["state"]["preferences"]["household"] = "Existing customer's home"
        state["state"]["members"].append({"id": "personal", "name": "Existing person", "color": "amber"})
        self.store.put_state(state["state"], state["revision"])
        before = self.store.get_state()
        token = self.store.new_session(owner["id"])
        with self.store.connect() as db:
            db.execute("DROP TABLE recovery_codes")
        upgraded = server.FamilyStore(self.folder.name)
        self.assertTrue(upgraded.initialized())
        self.assertEqual(upgraded.get_state(), before)
        self.assertEqual(upgraded.session(token)["id"], owner["id"])
        self.assertFalse(upgraded.system_info(owner["id"])["recoveryCodeConfigured"])
        code = upgraded.rotate_recovery_code(owner["id"], PASSWORD)
        self.assertTrue(code.startswith("HBR-"))

    def test_manual_backup_refreshes_today_and_system_status_reports_real_files(self):
        user, unused_code = self.store.setup_household(self.setup_details())
        target = self.store.backup()
        saved = self.store.get_state()
        saved["state"]["notes"] = [{"id": "new", "text": "A newer note", "expires": "", "private": False}]
        self.store.put_state(saved["state"], saved["revision"])
        with closing(sqlite3.connect(target)) as db:
            self.assertEqual(json.loads(db.execute("SELECT state FROM household").fetchone()[0])["notes"], [])
        self.assertEqual(self.store.backup(force=True), target)
        with closing(sqlite3.connect(target)) as db:
            self.assertEqual(json.loads(db.execute("SELECT state FROM household").fetchone()[0])["notes"][0]["text"], "A newer note")
        status = self.store.system_info(user["id"])
        self.assertEqual(status["version"], server.PRODUCT_VERSION)
        self.assertEqual(status["backup"]["fileCount"], 1)
        self.assertTrue(status["backup"]["lastCreatedAt"])
        self.assertNotIn("lastVerified", status["backup"])
        self.assertTrue(status["recoveryCodeConfigured"])

    def test_setup_key_single_initialization_and_hashed_password(self):
        self.assertFalse(self.store.initialized())
        with self.assertRaises(server.APIError) as error:
            self.store.create_user("Bad", "bad", PASSWORD, "admin", first=True, setup_key="wrong")
        self.assertEqual(error.exception.status, 403)
        user = self.owner()
        self.assertTrue(self.store.initialized())
        with self.assertRaises(server.APIError):
            self.store.create_user("Other", "other", PASSWORD, "admin", first=True, setup_key=KEY)
        with self.store.connect() as db:
            stored = db.execute("SELECT password FROM users WHERE id=?", (user["id"],)).fetchone()[0]
        self.assertNotIn(PASSWORD, stored)
        self.assertTrue(stored.startswith("scrypt$"))
        self.assertEqual(self.store.login("owner", PASSWORD)["id"], user["id"])
        with self.assertRaises(server.APIError):
            self.store.login("owner", "wrong")

    def test_generated_setup_key_is_a_file_and_persists(self):
        folder = Path(self.folder.name) / "generated"
        first = server.FamilyStore(folder)
        key = (folder / "setup-key.txt").read_text().strip()
        second = server.FamilyStore(folder)
        self.assertGreaterEqual(len(key), 32)
        self.assertEqual(first.setup_key, second.setup_key)

    def test_revision_conflict_preserves_first_change(self):
        initial = self.store.get_state()
        one, two = copy.deepcopy(initial["state"]), copy.deepcopy(initial["state"])
        one["notes"].append({"id": "one", "text": "First", "expires": "", "private": False})
        two["notes"].append({"id": "two", "text": "Second", "expires": "", "private": False})
        self.assertEqual(self.store.put_state(one, initial["revision"])["revision"], 1)
        with self.assertRaises(server.APIError) as error:
            self.store.put_state(two, initial["revision"])
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(error.exception.details["revision"], 1)
        self.assertEqual(self.store.get_state()["state"]["notes"][0]["text"], "First")

    def test_concurrent_writes_have_one_winner(self):
        outcomes = []
        barrier = threading.Barrier(2)
        def write(title):
            state = self.store.get_state()["state"]
            state["preferences"]["household"] = title
            barrier.wait()
            try:
                self.store.put_state(state, 0)
                outcomes.append(200)
            except server.APIError as exc:
                outcomes.append(exc.status)
        threads = [threading.Thread(target=write, args=(title,)) for title in ("One", "Two")]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=10)
        self.assertEqual(sorted(outcomes), [200, 409])
        self.assertEqual(self.store.get_state()["revision"], 1)

    def test_validation_drops_unknown_fields_and_checks_references_dates(self):
        state = server.empty_state()
        state["adminSecret"] = "never stored"
        state["items"].append({"id": "milk", "title": "Milk", "quantity": 2, "done": False, "completedAt": ""})
        clean = server.validate_state(state)
        self.assertNotIn("adminSecret", clean)
        self.assertEqual(clean["items"][0]["quantity"], "2")
        self.assertEqual(clean["items"][0]["category"], "Other")
        duplicate = copy.deepcopy(state)
        duplicate["items"].append(duplicate["items"][0])
        with self.assertRaises(server.APIError): server.validate_state(duplicate)
        state["tasks"] = [{"id": "bad", "title": "Task", "due": "2026-02-30", "memberId": "family"}]
        with self.assertRaises(server.APIError): server.validate_state(state)
        state["tasks"][0]["due"] = "2026-02-28"
        state["tasks"][0]["memberId"] = "missing"
        with self.assertRaises(server.APIError): server.validate_state(state)

    def test_display_never_receives_private_note_or_event_details(self):
        state = server.empty_state()
        state["events"] = [{"id": "appointment", "title": "Private appointment", "date": "2026-10-31",
                            "time": "12:00", "description": "Sensitive description", "location": "Sensitive location",
                            "private": True, "memberId": "family"}]
        state["notes"] = [{"id": "private", "text": "Private note", "private": True},
                          {"id": "public", "text": "Dinner at six", "private": False}]
        self.store.put_state(state, 0)
        output = self.store.get_state("display")["state"]
        encoded = json.dumps(output)
        self.assertNotIn("Sensitive", encoded)
        self.assertNotIn("Private appointment", encoded)
        self.assertNotIn("Private note", encoded)
        self.assertEqual(output["events"][0]["title"], "Busy")
        self.assertEqual(len(output["notes"]), 1)
        self.assertEqual(self.store.get_state()["state"]["events"][0]["title"], "Private appointment")

    def test_weekday_selections_persist_and_legacy_events_remain_valid(self):
        state = server.empty_state()
        state["events"] = [{"id": "school", "title": "School run", "date": "2026-10-31",
                            "repeat": "weekly", "weekdays": [5, 1, 3]}]
        self.store.put_state(state, 0)
        self.assertEqual(self.store.get_state()["state"]["events"][0]["weekdays"], [1, 3, 5])
        del state["events"][0]["weekdays"]
        self.assertEqual(server.validate_state(state)["events"][0]["weekdays"], [])
        for days in [[0], [8], [True], [1, 1], ["1"], [{}]]:
            state["events"][0]["weekdays"] = days
            with self.assertRaises(server.APIError):
                server.validate_state(state)

    def test_sessions_are_revocable_and_deleting_user_revokes_all(self):
        admin = self.owner()
        user = self.store.create_user("Partner", "partner", PASSWORD)
        token = self.store.new_session(user["id"])
        self.assertEqual(self.store.session(token)["role"], "adult")
        self.store.logout(token)
        self.assertIsNone(self.store.session(token))
        token = self.store.new_session(user["id"])
        self.store.delete_user(user["id"], admin["id"])
        self.assertIsNone(self.store.session(token))
        with self.assertRaises(server.APIError): self.store.delete_user(admin["id"], admin["id"])

    def test_backup_is_restorable_contains_accounts_and_prunes_only_own_files(self):
        self.owner()
        state = server.empty_state()
        state["notes"] = [{"id": "note", "text": "Restore this", "expires": "", "private": False}]
        self.store.put_state(state, 0)
        folder = Path(self.folder.name) / "backups"
        folder.mkdir()
        for index in range(1, 10):
            (folder / f"family-backup-2020-01-{index:02}.sqlite3").write_bytes(b"old placeholder")
        unrelated = folder / "keep-my-file.txt"
        unrelated.write_text("keep")
        target = self.store.backup()
        self.assertTrue(unrelated.exists())
        self.assertEqual(len(list(folder.glob("family-backup-*.sqlite3"))), 7)
        with closing(sqlite3.connect(target)) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)
            restored = json.loads(db.execute("SELECT state FROM household").fetchone()[0])
        self.assertEqual(restored["notes"][0]["text"], "Restore this")

    def test_login_rate_limit(self):
        for _ in range(10): self.store.throttle("127.0.0.1", "owner")
        with self.assertRaises(server.APIError) as error: self.store.throttle("127.0.0.1", "owner")
        self.assertEqual(error.exception.status, 429)


class HTTPCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = temporary_folder()
        cls.scrypt_patch = patch.object(server, "SCRYPT_N", 2 ** 14)
        cls.scrypt_patch.start()
        cls.store = server.FamilyStore(cls.folder.name, KEY)
        cls.store.create_user("Owner", "owner", PASSWORD, "admin", first=True, setup_key=KEY)
        cls.store.create_user("Display", "display", PASSWORD, "display")
        try:
            cls.httpd = server.FamilyServer(("127.0.0.1", 0), cls.store, index_path=ROOT / "index.html")
        except OSError as error:
            cls.scrypt_patch.stop()
            cls.folder.cleanup()
            raise unittest.SkipTest(f"Loopback sockets unavailable: {error}")
        cls.port = cls.httpd.server_address[1]
        cls.worker = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.worker.join(timeout=5)
        cls.scrypt_patch.stop()
        cls.folder.cleanup()

    def request(self, method, path, data=None, cookie=None, csrf=None, origin=None, extra=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Origin": origin or f"http://127.0.0.1:{self.port}"}
        body = None
        if data is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data)
        if cookie: headers["Cookie"] = cookie
        if csrf: headers["X-CSRF-Token"] = csrf
        if extra: headers.update(extra)
        connection.request(method, path, body, headers)
        response = connection.getresponse()
        status, response_headers = response.status, dict(response.getheaders())
        raw = response.read()
        connection.close()
        return status, json.loads(raw) if raw else {}, response_headers

    def login(self, username="owner"):
        status, result, headers = self.request("POST", "/api/login", {"username": username, "password": PASSWORD})
        self.assertEqual(status, 200)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        return headers["Set-Cookie"].split(";", 1)[0], result["csrf"]

    def test_authentication_csrf_display_permissions_and_logout(self):
        self.assertEqual(self.request("GET", "/api/state")[0], 401)
        cookie, csrf = self.login()
        state = self.request("GET", "/api/state", cookie=cookie)[1]
        self.assertEqual(self.request("PUT", "/api/state", state, cookie=cookie)[0], 403)
        self.assertEqual(self.request("PUT", "/api/state", state, cookie=cookie, csrf=csrf)[0], 200)
        display_cookie, display_csrf = self.login("display")
        current = self.request("GET", "/api/state", cookie=display_cookie)[1]
        self.assertEqual(self.request("PUT", "/api/state", current, cookie=display_cookie, csrf=display_csrf)[0], 403)
        self.assertEqual(self.request("GET", "/api/users", cookie=display_cookie)[0], 403)
        self.assertEqual(self.request("GET", "/api/backup", cookie=display_cookie)[0], 403)
        self.assertEqual(self.request("POST", "/api/logout", {}, cookie=cookie, csrf=csrf)[0], 200)
        self.assertEqual(self.request("GET", "/api/state", cookie=cookie)[0], 401)

    def test_cross_origin_blocked(self):
        cookie, csrf = self.login()
        self.assertEqual(self.request("GET", "/api/state", cookie=cookie, origin="https://untrusted.example")[0], 403)

    def test_admin_user_management(self):
        cookie, csrf = self.login()
        result = self.request("POST", "/api/users", {"name": "Test adult", "username": "other", "password": PASSWORD,
                                                     "role": "adult"}, cookie=cookie, csrf=csrf)
        self.assertEqual(result[0], 201)
        self.assertNotIn("password", result[1]["user"])
        user_id = result[1]["user"]["id"]
        self.assertEqual(self.request("DELETE", "/api/users/" + user_id, cookie=cookie, csrf=csrf)[0], 200)

    def test_sse_notifies_committed_revision_and_revokes_stream_on_logout(self):
        cookie, csrf = self.login()
        stream = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        stream.request("GET", "/api/events", headers={"Cookie": cookie})
        response = stream.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "text/event-stream; charset=utf-8")

        def event():
            fields = {}
            while True:
                line = response.readline().decode().strip()
                if not line:
                    if fields: return fields
                    continue
                if line.startswith(":"): continue
                key, value = line.split(":", 1)
                fields[key] = value.strip()

        first = event()
        current = self.request("GET", "/api/state", cookie=cookie)[1]
        self.assertEqual(json.loads(first["data"])["revision"], current["revision"])
        current["state"]["preferences"]["household"] = "SSE verified"
        saved = self.request("PUT", "/api/state", current, cookie=cookie, csrf=csrf)
        self.assertEqual(saved[0], 200)
        pushed = event()
        self.assertEqual(json.loads(pushed["data"]), {"revision": saved[1]["revision"]})
        self.assertEqual(self.request("POST", "/api/logout", {}, cookie=cookie, csrf=csrf)[0], 200)
        self.assertEqual(event()["event"], "expired")
        response.close()
        stream.close()


class ProductHTTPCase(unittest.TestCase):
    def setUp(self):
        self.folder = temporary_folder()
        self.scrypt_patch = patch.object(server, "SCRYPT_N", 2 ** 14)
        self.scrypt_patch.start()
        self.store = server.FamilyStore(self.folder.name, KEY)
        try:
            self.httpd = server.FamilyServer(("127.0.0.1", 0), self.store, index_path=ROOT / "index.html",
                                            instance_id="desktop-instance")
        except OSError as error:
            self.scrypt_patch.stop()
            self.folder.cleanup()
            raise unittest.SkipTest(f"Loopback sockets unavailable: {error}")
        self.port = self.httpd.server_address[1]
        self.worker = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=5)
        self.scrypt_patch.stop()
        self.folder.cleanup()

    request = HTTPCase.request

    def claim(self):
        status, body, headers = self.request("POST", "/api/setup", {
            "setupKey": KEY, "name": "Owner", "username": "owner", "password": PASSWORD,
            "household": {"name": "A customer's household", "timezone": "UTC", "theme": "premium"},
            "members": [{"name": "Partner", "color": "rose"}]})
        self.assertEqual(status, 201)
        return body, headers["Set-Cookie"].split(";", 1)[0]

    def test_public_product_metadata_does_not_include_claim_or_account_secrets(self):
        status, info, unused = self.request("GET", "/api/product")
        self.assertEqual(status, 200)
        self.assertEqual(info["version"], server.PRODUCT_VERSION)
        self.assertEqual(info["name"], "Homeboard")
        self.assertTrue(info["setupRequired"])
        self.assertFalse(info["localSetupAvailable"])
        self.assertNotIn(KEY, json.dumps(info))
        health = self.request("GET", "/api/health")[1]
        self.assertEqual(health["product"], "homeboard")
        self.assertEqual(health["instance_id"], "desktop-instance")
        self.assertEqual(self.request("GET", "/api/system")[0], 401)
        self.claim()
        self.assertFalse(self.request("GET", "/api/product")[1]["setupRequired"])

    def test_local_setup_claim_is_opt_in_loopback_only_and_stops_after_claim(self):
        self.assertEqual(self.request("GET", "/api/setup/local")[0], 403)
        self.httpd.local_setup = True
        self.assertTrue(self.request("GET", "/api/product")[1]["localSetupAvailable"])
        self.assertEqual(self.request("GET", "/api/setup/local")[1], {"setupKey": KEY})
        self.claim()
        self.assertFalse(self.request("GET", "/api/product")[1]["localSetupAvailable"])
        self.assertEqual(self.request("GET", "/api/setup/local")[0], 403)

    def test_local_setup_ignores_forwarded_addresses_and_rejects_lan_or_untrusted_host(self):
        handler = object.__new__(server.FamilyHandler)
        handler.server = SimpleNamespace(local_setup=True, public_origin="", store=self.store)
        cases = [
            ("192.168.1.20", "localhost", False),
            ("127.0.0.1", "192.168.1.20", False),
            ("127.0.0.1", "localhost.evil.example", False),
            ("127.0.0.1", "localhost:8080", True),
            ("127.0.0.1", "127.0.0.1:8080", True),
            ("::1", "[::1]:8080", True),
        ]
        for client, host, expected in cases:
            handler.client_address = (client, 1000)
            handler.headers = {"Host": host, "X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1"}
            self.assertEqual(handler.local_setup_available(), expected, (client, host))
        handler.client_address = ("127.0.0.1", 1000)
        handler.headers = {"Host": "localhost"}
        handler.server.public_origin = "https://proxy.example"
        self.assertFalse(handler.local_setup_available())

    def test_setup_http_returns_kit_once_and_existing_owner_cannot_be_claimed_again(self):
        result, cookie = self.claim()
        self.assertTrue(result["authenticated"])
        self.assertTrue(result["recoveryCode"].startswith("HBR-"))
        self.assertTrue(result["backupCreated"])
        snapshots = list((self.store.data_dir / "backups").glob("family-backup-*.sqlite3"))
        self.assertEqual(len(snapshots), 1)
        with closing(sqlite3.connect(snapshots[0])) as backup:
            self.assertEqual(backup.execute("SELECT username FROM users").fetchone()[0], "owner")
            snapshot = json.loads(backup.execute("SELECT state FROM household WHERE id=1").fetchone()[0])
            self.assertEqual(snapshot["preferences"]["household"], "A customer's household")
            self.assertEqual(backup.execute("SELECT count(*) FROM recovery_codes").fetchone()[0], 1)
        me = self.request("GET", "/api/me", cookie=cookie)[1]
        self.assertNotIn("recoveryCode", me)
        state = self.request("GET", "/api/state", cookie=cookie)[1]["state"]
        self.assertEqual(state["preferences"]["household"], "A customer's household")
        self.assertEqual([person["name"] for person in state["members"]], ["Family", "Owner", "Partner"])
        self.assertEqual(self.request("POST", "/api/setup", {
            "setupKey": KEY, "name": "Other", "username": "other", "password": PASSWORD})[0], 409)

    def test_setup_preserves_owner_session_and_recovery_kit_if_initial_backup_fails(self):
        with patch.object(self.store, "backup", side_effect=OSError("test full disk")), self.assertLogs(server.LOG, level="ERROR"):
            result, cookie = self.claim()
        self.assertFalse(result["backupCreated"])
        self.assertTrue(result["recoveryCode"].startswith("HBR-"))
        self.assertTrue(self.request("GET", "/api/me", cookie=cookie)[1]["authenticated"])
        self.assertEqual(self.store.login("owner", PASSWORD)["role"], "admin")
        self.assertEqual(self.request("GET", "/api/system", cookie=cookie)[1]["backup"]["fileCount"], 0)

    def test_http_recovery_revokes_old_session_and_requires_sign_in_with_new_password(self):
        result, cookie = self.claim()
        new_password = "The new recovery passphrase!"
        status, recovered, headers = self.request("POST", "/api/recover", {
            "username": "owner", "recoveryCode": result["recoveryCode"], "password": new_password})
        self.assertEqual(status, 200)
        self.assertFalse(recovered["authenticated"])
        self.assertNotEqual(recovered["recoveryCode"], result["recoveryCode"])
        self.assertIn("Max-Age=0", headers["Set-Cookie"])
        self.assertEqual(self.request("GET", "/api/state", cookie=cookie)[0], 401)
        self.assertEqual(self.request("POST", "/api/recover", {
            "username": "owner", "recoveryCode": result["recoveryCode"], "password": PASSWORD})[0], 401)
        self.assertEqual(self.request("POST", "/api/login", {
            "username": "owner", "password": new_password})[0], 200)

    def test_recovery_attempts_are_rate_limited(self):
        for _ in range(10):
            self.assertEqual(self.request("POST", "/api/recover", {
                "username": "owner", "recoveryCode": "wrong", "password": PASSWORD})[0], 401)
        self.assertEqual(self.request("POST", "/api/recover", {
            "username": "owner", "recoveryCode": "wrong", "password": PASSWORD})[0], 429)

    def test_recovery_rotation_and_manual_backups_require_admin_and_csrf(self):
        result, cookie = self.claim()
        self.assertEqual(self.request("POST", "/api/recovery-code", {"password": PASSWORD}, cookie=cookie)[0], 403)
        self.assertEqual(self.request("POST", "/api/recovery-code", {"password": "wrong"}, cookie=cookie, csrf=result["csrf"])[0], 401)
        status, rotated, unused = self.request("POST", "/api/recovery-code", {"password": PASSWORD},
                                              cookie=cookie, csrf=result["csrf"])
        self.assertEqual(status, 200)
        self.assertNotEqual(result["recoveryCode"], rotated["recoveryCode"])
        self.assertEqual(self.request("POST", "/api/backups", {}, cookie=cookie)[0], 403)
        status, backup, unused = self.request("POST", "/api/backups", {}, cookie=cookie, csrf=result["csrf"])
        self.assertEqual(status, 201)
        self.assertTrue(backup["filename"].startswith("family-backup-"))
        info = self.request("GET", "/api/system", cookie=cookie)[1]
        self.assertEqual(info["backup"]["fileCount"], 1)
        self.assertTrue(info["recoveryCodeConfigured"])
        self.assertEqual(info["networkUrls"], [])
        self.assertEqual(info["transport"], "http")
        for role in ("adult", "display"):
            self.store.create_user(role.title(), role, PASSWORD, role)
            token = self.store.new_session(self.store.login(role, PASSWORD)["id"])
            session = self.store.session(token)
            other_cookie = "family_session=" + token
            self.assertEqual(self.request("GET", "/api/system", cookie=other_cookie)[0], 403)
            self.assertEqual(self.request("POST", "/api/recovery-code", {"password": PASSWORD},
                                          cookie=other_cookie, csrf=session["csrf"])[0], 403)
            self.assertEqual(self.request("POST", "/api/backups", {},
                                          cookie=other_cookie, csrf=session["csrf"])[0], 403)

    def test_connection_urls_use_only_trusted_private_literals_and_configured_ports(self):
        self.httpd.configured_hosts = ("192.168.50.20:8087", "10.0.0.20")
        self.httpd.allowed_hosts = {*self.httpd.configured_hosts, "172.17.0.1:8080", "localhost:8787",
                                   "127.0.0.1:8787", "[::1]:8787", "[fd00::1]:8787", "8.8.8.8:8787",
                                   "example.com:8787", "169.254.2.3:8787", "0.0.0.0:8787", "192.168.0.2:0",
                                   "192.168.0.2:65536", "192.168.0.2:word", "user@192.168.0.2:8787",
                                   "192.168.0.2:8787/evil", "192.168.0.2:8787?bad=1", "192.168.0.2:8787#bad",
                                   "192.168.0.2:8787 ", "http://192.168.0.2:8787"}
        self.assertEqual(self.httpd.connection_info(), {
            "networkUrls": ["http://192.168.50.20:8087", f"http://10.0.0.20:{self.port}", "http://172.17.0.1:8080"],
            "transport": "http"})
        # COOKIE_SECURE alone does not prove that the browser uses TLS.
        self.httpd.cookie_secure = True
        self.assertEqual(self.httpd.connection_info()["transport"], "http")
        self.httpd.public_origin = "https://homeboard.example"
        self.assertEqual(self.httpd.connection_info()["transport"], "https")
        self.assertEqual(self.httpd.connection_info()["networkUrls"], [])
        self.httpd.public_origin = "https://192.168.50.20:8087"
        self.assertEqual(self.httpd.connection_info()["networkUrls"], ["https://192.168.50.20:8087"])
        # Refresh can remove a no-longer-present adapter and add its replacement.
        self.httpd.public_origin = ""
        self.httpd.allowed_hosts = {"192.168.1.21:8787"}
        self.assertEqual(self.httpd.connection_info()["networkUrls"], ["http://192.168.1.21:8787"])

    def test_system_share_urls_ignore_request_and_forwarded_host_headers(self):
        result, cookie = self.claim()
        self.httpd.configured_hosts = ("192.168.50.20:8087",)
        # The existing request helper uses the loopback connection, so keep that
        # host trusted while proving it is never advertised to another device.
        self.httpd.allowed_hosts = {"192.168.50.20:8087", f"127.0.0.1:{self.port}"}
        info = self.request("GET", "/api/system", cookie=cookie, extra={
            "X-Forwarded-Host": "attacker.example", "X-Forwarded-Proto": "https"})[1]
        self.assertEqual(info["networkUrls"], ["http://192.168.50.20:8087"])
        self.assertEqual(info["transport"], "http")

    def test_main_accepts_graceful_stop_and_refreshes_trusted_local_hosts(self):
        stop = threading.Event()
        refreshed = threading.Event()
        created = []
        original = server.FamilyServer
        def create(*args, **kwargs):
            result = original(*args, **kwargs)
            created.append(result)
            return result
        def provider():
            refreshed.set()
            return ["localhost:8787", "192.168.1.22:8787"]
        environment = {"HOST": "127.0.0.1", "PORT": "0", "DATA_DIR": str(Path(self.folder.name) / "main"),
                       "PUBLIC_ORIGIN": "", "LOCAL_SETUP": "1", "COOKIE_SECURE": "0"}
        with patch.dict(server.os.environ, environment), patch.object(server, "FamilyServer", side_effect=create):
            worker = threading.Thread(target=server.main, kwargs={"stop_event": stop, "allowed_hosts_provider": provider})
            worker.start()
            self.assertTrue(refreshed.wait(5))
            stop.set()
            worker.join(timeout=8)
            self.assertFalse(worker.is_alive())
        self.assertTrue(created)
        self.assertEqual(created[0].allowed_hosts, {"localhost:8787", "192.168.1.22:8787"})
        self.assertEqual(created[0].socket.fileno(), -1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
