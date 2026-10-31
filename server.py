"""Local family dashboard server. Python 3.13 standard library only.

The browser UI remains one index.html; SQLite, sessions and push notifications
live here so phones and the kitchen display can share one authoritative state.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import http.cookies
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import threading
import time
from contextlib import closing, contextmanager
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

LOG = logging.getLogger("family")
BASE_DIR = Path(__file__).resolve().parent
PRODUCT_VERSION = "0.2.0-rc.1"
MAX_BODY = 2 * 1024 * 1024
SESSION_SECONDS = 30 * 24 * 60 * 60
SCRYPT_N = 2 ** 17
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_MAXMEM = 256 * 1024 * 1024
PASSWORD_SLOTS = threading.BoundedSemaphore(2)
ID_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,100}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
REPEATS = {"none", "daily", "weekly", "monthly", "yearly"}


class APIError(Exception):
    def __init__(self, status: int, message: str, **details):
        self.status, self.message, self.details = status, message, details
        super().__init__(message)


def require(condition, message):
    if not condition:
        raise APIError(422, message)


def string(value, label, limit=200, default="", required=False):
    if value is None:
        value = default
    require(isinstance(value, str), f"{label} must be text.")
    require(len(value) <= limit and "\x00" not in value, f"{label} is too long or invalid.")
    require(not required or bool(value.strip()), f"{label} is required.")
    return value


def identifier(value, label):
    require(isinstance(value, str) and ID_RE.fullmatch(value), f"{label} is invalid.")
    return value


def day(value, label, optional=False):
    if optional and value in (None, ""):
        return ""
    require(isinstance(value, str) and DATE_RE.fullmatch(value), f"{label} must be YYYY-MM-DD.")
    try:
        result = date.fromisoformat(value)
        require(1900 <= result.year <= 2200, f"{label} must be between 1900 and 2200.")
    except ValueError:
        raise APIError(422, f"{label} is not a real date.") from None
    return value


def clock(value, label):
    if value in (None, ""):
        return ""
    require(isinstance(value, str) and TIME_RE.fullmatch(value), f"{label} must be HH:MM.")
    return value


def boolean(value, label, default=False):
    if value is None:
        return default
    require(type(value) is bool, f"{label} must be true or false.")
    return value


def choice(value, allowed, label, default):
    if value is None:
        value = default
    require(isinstance(value, str) and value in allowed, f"{label} is invalid.")
    return value


def timestamp(value):
    # Early UI snapshots may use epoch milliseconds. Normalize to ISO for storage.
    if value in (None, "", 0):
        return ""
    if isinstance(value, (int, float)) and type(value) is not bool:
        try:
            return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            raise APIError(422, "Completion timestamp is invalid.") from None
    value = string(value, "Completion timestamp", 60)
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise APIError(422, "Completion timestamp is invalid.") from None
    return value


def rows(state, key, limit):
    result = state.get(key, [])
    require(isinstance(result, list) and len(result) <= limit, f"Too many or invalid {key}.")
    require(all(isinstance(row, dict) for row in result), f"Invalid {key} entry.")
    ids = [identifier(row.get("id"), f"{key} ID") for row in result]
    require(len(ids) == len(set(ids)), f"Duplicate {key} IDs.")
    return result


def empty_state():
    return {
        "schema": 1,
        "members": [{"id": "family", "name": "Family", "color": "sage"}],
        "events": [], "tasks": [], "items": [], "notes": [], "meals": {},
        "preferences": {"household": "Our home", "timezone": "UTC",
                        "hour24": True, "theme": "premium"},
    }


def validate_state(state):
    """Validate and rebuild known fields. Imported objects are never merged blindly."""
    require(isinstance(state, dict) and type(state.get("schema")) is int and state["schema"] == 1,
            "Unsupported household data format.")
    clean = {"schema": 1}
    clean["members"] = [{"id": row["id"],
                         "name": string(row.get("name"), "Member name", 60, required=True),
                         "color": choice(row.get("color"), {"sage", "blue", "rose", "amber"},
                                         "Member color", "sage")}
                        for row in rows(state, "members", 30)]
    require(bool(clean["members"]), "At least one family member is required.")
    member_ids = {row["id"] for row in clean["members"]}
    require("family" in member_ids, "The Family profile is required.")
    default_member = "family"

    def member(row):
        result = row.get("memberId") or default_member
        require(result in member_ids, "An assigned family member does not exist.")
        return result

    clean["events"] = []
    for row in rows(state, "events", 5000):
        exceptions = row.get("exceptions", [])
        require(isinstance(exceptions, list) and len(exceptions) <= 2000,
                "Event exceptions are invalid or too numerous.")
        weekdays = row.get("weekdays", [])
        require(isinstance(weekdays, list) and len(weekdays) <= 7 and
                all(type(value) is int and 1 <= value <= 7 for value in weekdays) and
                len(weekdays) == len(set(weekdays)), "Weekdays must be unique numbers from 1 (Monday) to 7 (Sunday).")
        reminder = row.get("reminder", 0)
        require(type(reminder) is int and reminder in {0, 15, 30, 60, 1440}, "Event reminder is invalid.")
        event = {"id": row["id"], "title": string(row.get("title"), "Event title", 200, required=True),
                 "date": day(row.get("date"), "Event date"),
                 "time": clock(row.get("time"), "Event time"),
                 "endTime": clock(row.get("endTime"), "Event end time"),
                 "allDay": boolean(row.get("allDay"), "All-day event"),
                 "memberId": member(row),
                 "repeat": choice(row.get("repeat"), REPEATS, "Event repeat", "none"),
                 "weekdays": sorted(weekdays),
                 "until": day(row.get("until"), "Event repeat-until date", True),
                 "exceptions": sorted({day(value, "Exception date") for value in exceptions}),
                 "description": string(row.get("description"), "Event description", 4000),
                 "location": string(row.get("location"), "Event location", 300),
                 "reminder": reminder, "private": boolean(row.get("private"), "Private event")}
        require(not event["until"] or event["until"] >= event["date"], "Repeat-until cannot precede the event.")
        require(event["allDay"] or not event["time"] or not event["endTime"] or event["endTime"] > event["time"], "Event end time must follow start time.")
        if row.get("seriesId"):
            event["seriesId"] = identifier(row["seriesId"], "Event series ID")
        clean["events"].append(event)

    clean["tasks"] = []
    for row in rows(state, "tasks", 5000):
        task = {"id": row["id"], "title": string(row.get("title"), "Task title", 200, required=True),
                "due": day(row.get("due"), "Task due date", True), "memberId": member(row),
                "repeat": choice(row.get("repeat"), REPEATS, "Task repeat", "none"),
                "done": boolean(row.get("done"), "Task completion"),
                "completedAt": timestamp(row.get("completedAt"))}
        require(task["repeat"] == "none" or bool(task["due"]), "A recurring task needs a due date.")
        if row.get("seriesId"):
            task["seriesId"] = identifier(row["seriesId"], "Task series ID")
        clean["tasks"].append(task)

    clean["items"] = []
    for row in rows(state, "items", 5000):
        quantity = row.get("quantity", "")
        if type(quantity) in (int, float):
            quantity = str(quantity)
        clean["items"].append({"id": row["id"],
            "title": string(row.get("title"), "Shopping item", 200, required=True),
            "quantity": string(quantity, "Quantity", 80),
            "category": string(row.get("category"), "Category", 80, default="Other"),
            "list": string(row.get("list"), "Shopping list", 80, default="Groceries"),
            "done": boolean(row.get("done"), "Item completion"),
            "completedAt": timestamp(row.get("completedAt"))})

    clean["notes"] = [{"id": row["id"], "text": string(row.get("text"), "Note", 2000, required=True),
                       "expires": day(row.get("expires"), "Note expiry", True),
                       "private": boolean(row.get("private"), "Private note")}
                      for row in rows(state, "notes", 300)]
    meals = state.get("meals", {})
    require(isinstance(meals, dict) and len(meals) <= 1500, "Meal plan is invalid or too large.")
    clean["meals"] = {day(key, "Meal date"): string(value, "Meal", 300) for key, value in meals.items()}
    prefs = state.get("preferences", {})
    require(isinstance(prefs, dict), "Preferences are invalid.")
    tz = string(prefs.get("timezone"), "Timezone", 100, default="UTC")
    try:
        from zoneinfo import ZoneInfo, available_timezones
        ZoneInfo(tz)
    except (ValueError, KeyError):
        # Windows can lack IANA data; the browser still needs a real known zone.
        fallback_zones = {"UTC", "Asia/Yekaterinburg", "Europe/Moscow", "Europe/Samara",
                          "Asia/Omsk", "Asia/Novosibirsk", "Asia/Krasnoyarsk", "Asia/Irkutsk",
                          "Asia/Yakutsk", "Asia/Vladivostok", "Asia/Magadan", "Asia/Kamchatka",
                          "Europe/London", "Europe/Berlin", "America/New_York", "America/Los_Angeles"}
        require(not available_timezones() and tz in fallback_zones, "Timezone is invalid or unavailable on this server.")
    clean["preferences"] = {
        "household": string(prefs.get("household"), "Household name", 100, default="Our home", required=True),
        "timezone": tz, "hour24": boolean(prefs.get("hour24"), "24-hour clock", True),
        "theme": choice(prefs.get("theme"), {"warm", "premium", "smart"}, "Theme", "premium")}
    return clean


def display_state(state):
    result = copy.deepcopy(state)
    for event in result["events"]:
        event["description"] = ""
        event["location"] = ""
        if event.get("private"):
            event["title"] = "Busy"
    result["notes"] = [row for row in result["notes"] if not row.get("private")]
    return result


def hash_password(password):
    salt = secrets.token_bytes(16)
    with PASSWORD_SLOTS:
        derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N,
                                 r=SCRYPT_R, p=SCRYPT_P, maxmem=SCRYPT_MAXMEM, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${derived.hex()}"


def verify_password(password, encoded):
    try:
        kind, n, r, p, salt, expected = encoded.split("$")
        if kind != "scrypt":
            return False
        with PASSWORD_SLOTS:
            derived = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=int(n),
                                     r=int(r), p=int(p), maxmem=SCRYPT_MAXMEM, dklen=32)
        return hmac.compare_digest(derived.hex(), expected)
    except (ValueError, TypeError):
        return False


def password_value(value):
    result = string(value, "Password", 256, required=True)
    require(len(result) >= 12, "Use a password of at least 12 characters.")
    return result


def new_recovery_code():
    raw = secrets.token_hex(24).upper()
    return "HBR-" + "-".join(raw[index:index + 6] for index in range(0, len(raw), 6))


def recovery_digest(code):
    normalized = "".join(code.upper().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def account_fields(data):
    name = string(data.get("name"), "Name", 60, required=True).strip()
    username = string(data.get("username"), "Username", 40, required=True).strip().lower()
    require(bool(re.fullmatch(r"[a-z0-9_.-]{3,40}", username)),
            "Username must be 3–40 letters, numbers, periods, underscores or hyphens.")
    password = password_value(data.get("password"))
    return name, username, password


class FamilyStore:
    def __init__(self, data_dir, setup_key=None):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "family.sqlite3"
        self.changed = threading.Condition()
        self.started_at = time.monotonic()
        self.backup_lock = threading.Lock()
        self.rate_lock = threading.Lock()
        self.attempts = {}
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                  id TEXT PRIMARY KEY, name TEXT NOT NULL, username TEXT NOT NULL UNIQUE,
                  password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','adult','display')));
                CREATE TABLE IF NOT EXISTS sessions (
                  token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  csrf TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS household (
                  id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL, revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS recovery_codes (
                  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                  code_hash TEXT NOT NULL, rotated_at TEXT NOT NULL);
            """)
            db.execute("INSERT OR IGNORE INTO household VALUES(1,?,0)", (json.dumps(empty_state()),))
        self.setup_key = setup_key
        if not setup_key and not self.initialized():
            key_path = self.data_dir / "setup-key.txt"
            if key_path.exists():
                self.setup_key = key_path.read_text(encoding="utf-8").strip()
            else:
                self.setup_key = secrets.token_urlsafe(32)
                key_path.write_text(self.setup_key + "\n", encoding="utf-8")
                try:
                    key_path.chmod(0o600)
                except OSError:
                    pass
            LOG.info("First-run setup key is in %s (open the file locally).", key_path)
        self.dummy_password = hash_password(secrets.token_urlsafe(24))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialized(self):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None

    def throttle(self, ip, username):
        now = time.monotonic()
        with self.rate_lock:
            self.attempts = {key: [v for v in values if v > now - 900]
                             for key, values in self.attempts.items() if any(v > now - 900 for v in values)}
            keys = [("ip", ip), ("login", ip, username)]
            if len(self.attempts.get(keys[0], [])) >= 30 or len(self.attempts.get(keys[1], [])) >= 10:
                raise APIError(429, "Too many sign-in attempts. Try again in 15 minutes.")
            for key in keys:
                self.attempts.setdefault(key, []).append(now)

    def create_user(self, name, username, password, role="adult", first=False, setup_key=""):
        require(role in {"admin", "adult", "display"}, "Account role is invalid.")
        if first and (not self.setup_key or not setup_key or not hmac.compare_digest(str(setup_key).encode(), str(self.setup_key).encode())):
            raise APIError(403, "Setup key is incorrect.")
        encoded = hash_password(password)
        user_id = secrets.token_hex(12)
        try:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if first and db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                    raise APIError(409, "This household is already initialized.")
                db.execute("INSERT INTO users VALUES(?,?,?,?,?)", (user_id, name, username, encoded, role))
        except sqlite3.IntegrityError:
            raise APIError(409, "That username is already in use.") from None
        return {"id": user_id, "name": name, "username": username, "role": role}

    def setup_household(self, data):
        """Claim a fresh install atomically, without leaving a partial owner."""
        require(isinstance(data, dict), "Setup details are invalid.")
        key = string(data.get("setupKey"), "Setup key", 300)
        if not self.setup_key or not key or not hmac.compare_digest(key.encode(), self.setup_key.encode()):
            raise APIError(403, "Setup key is incorrect.")
        name, username, password = account_fields(data)
        household = data.get("household", {})
        require(isinstance(household, dict), "Household settings are invalid.")
        members = data.get("members", [])
        require(isinstance(members, list) and len(members) <= 12, "Add no more than 12 additional family members.")
        require(all(isinstance(member, dict) for member in members), "Family members are invalid.")
        state = empty_state()
        state["preferences"] = {
            "household": string(household.get("name"), "Household name", 100, default="Our home", required=True).strip(),
            "timezone": string(household.get("timezone"), "Timezone", 100, default="UTC"),
            "hour24": boolean(household.get("hour24"), "24-hour clock", True),
            "theme": choice(household.get("theme"), {"warm", "premium", "smart"}, "Theme", "premium")}
        state["members"].append({"id": "member-" + secrets.token_hex(8), "name": name, "color": "blue"})
        for member in members:
            state["members"].append({
                "id": "member-" + secrets.token_hex(8),
                "name": string(member.get("name"), "Member name", 60, required=True).strip(),
                "color": choice(member.get("color"), {"sage", "blue", "rose", "amber"}, "Member color", "sage")})
        clean = validate_state(state)
        encoded = hash_password(password)
        recovery_code = new_recovery_code()
        user_id = secrets.token_hex(12)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                raise APIError(409, "This household is already initialized.")
            db.execute("INSERT INTO users VALUES(?,?,?,?,?)", (user_id, name, username, encoded, "admin"))
            db.execute("UPDATE household SET state=?,revision=revision+1 WHERE id=1",
                       (json.dumps(clean, ensure_ascii=False, allow_nan=False),))
            db.execute("INSERT INTO recovery_codes VALUES(?,?,?)",
                       (user_id, recovery_digest(recovery_code), datetime.now(timezone.utc).isoformat()))
        with self.changed:
            self.changed.notify_all()
        return {"id": user_id, "name": name, "username": username, "role": "admin"}, recovery_code

    def rotate_recovery_code(self, user_id, password):
        with self.connect() as db:
            user = db.execute("SELECT role,password FROM users WHERE id=?", (user_id,)).fetchone()
        if not user or user["role"] != "admin":
            raise APIError(403, "Administrator access is required.")
        if not verify_password(password, user["password"]):
            raise APIError(401, "Password is incorrect.")
        code = new_recovery_code()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT password FROM users WHERE id=? AND role='admin'", (user_id,)).fetchone()
            if not current or current["password"] != user["password"]:
                raise APIError(409, "Account security changed. Sign in again before continuing.")
            db.execute("INSERT INTO recovery_codes VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                       "code_hash=excluded.code_hash,rotated_at=excluded.rotated_at",
                       (user_id, recovery_digest(code), datetime.now(timezone.utc).isoformat()))
        return code

    def recover_account(self, username, code, password):
        password = password_value(password)
        digest = recovery_digest(code)
        with self.connect() as db:
            user = db.execute("SELECT users.id,recovery_codes.code_hash FROM users "
                              "JOIN recovery_codes ON users.id=recovery_codes.user_id "
                              "WHERE users.username=? AND users.role='admin'", (username,)).fetchone()
        if not user or not code or not hmac.compare_digest(user["code_hash"], digest):
            raise APIError(401, "The username or recovery code is incorrect.")
        encoded = hash_password(password)
        rotated = new_recovery_code()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            updated = db.execute("UPDATE recovery_codes SET code_hash=?,rotated_at=? WHERE user_id=? AND code_hash=?",
                                 (recovery_digest(rotated), datetime.now(timezone.utc).isoformat(), user["id"], digest))
            if updated.rowcount != 1:
                raise APIError(401, "The username or recovery code is incorrect.")
            db.execute("UPDATE users SET password=? WHERE id=?", (encoded, user["id"]))
            db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
        with self.changed:
            self.changed.notify_all()
        return rotated

    def system_info(self, user_id=None):
        folder = self.data_dir / "backups"
        files = list(folder.glob("family-backup-????-??-??.sqlite3")) if folder.exists() else []
        latest = max(files, key=lambda path: path.stat().st_mtime) if files else None
        with self.connect() as db:
            recovery_ready = bool(user_id and db.execute("SELECT 1 FROM recovery_codes WHERE user_id=?", (user_id,)).fetchone())
        return {"version": PRODUCT_VERSION, "database": "SQLite", "uptimeSeconds": int(time.monotonic() - self.started_at),
                "recoveryCodeConfigured": recovery_ready,
                "backup": {"lastCreatedAt": datetime.fromtimestamp(latest.stat().st_mtime, timezone.utc).isoformat() if latest else None,
                           "fileCount": len(files)}}

    def login(self, username, password):
        with self.connect() as db:
            user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        valid = verify_password(password, user["password"] if user else self.dummy_password)
        if not user or not valid:
            raise APIError(401, "Username or password is incorrect.")
        return dict(user)

    def new_session(self, user_id):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
            db.execute("INSERT INTO sessions VALUES(?,?,?,?)",
                       (hashlib.sha256(token.encode()).hexdigest(), user_id, csrf, time.time() + SESSION_SECONDS))
        return token

    def session(self, token):
        if not token:
            return None
        with self.connect() as db:
            row = db.execute("""SELECT users.id, users.name, users.role, sessions.csrf, sessions.expires
                FROM sessions JOIN users ON users.id=sessions.user_id
                WHERE sessions.token_hash=? AND sessions.expires>?""",
                (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        return dict(row) if row else None

    def logout(self, token):
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
        with self.changed:
            self.changed.notify_all()

    def users(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT id,name,username,role FROM users ORDER BY name")]

    def delete_user(self, user_id, caller_id):
        if user_id == caller_id:
            raise APIError(409, "You cannot remove your own administrator account.")
        with self.connect() as db:
            row = db.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
            if not row:
                raise APIError(404, "Account was not found.")
            if row["role"] == "admin":
                raise APIError(403, "Administrator accounts cannot be removed here.")
            db.execute("DELETE FROM users WHERE id=?", (user_id,))
        with self.changed:
            self.changed.notify_all()

    def get_state(self, role="admin"):
        with self.connect() as db:
            row = db.execute("SELECT state,revision FROM household WHERE id=1").fetchone()
        state = json.loads(row["state"])
        return {"state": display_state(state) if role == "display" else state, "revision": row["revision"]}

    def revision(self):
        with self.connect() as db:
            return db.execute("SELECT revision FROM household WHERE id=1").fetchone()[0]

    def put_state(self, state, revision):
        require(type(revision) is int and revision >= 0, "State revision is invalid.")
        clean = validate_state(state)
        encoded = json.dumps(clean, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        require(len(encoded.encode("utf-8")) <= MAX_BODY, "Household data is too large.")
        with self.connect() as db:
            result = db.execute("UPDATE household SET state=?,revision=revision+1 WHERE id=1 AND revision=?",
                                (encoded, revision))
            if result.rowcount != 1:
                current = db.execute("SELECT revision FROM household WHERE id=1").fetchone()[0]
                raise APIError(409, "Someone else changed the household. Reload before saving again.", revision=current)
        with self.changed:
            self.changed.notify_all()
        return {"state": clean, "revision": revision + 1}

    def backup(self, force=False):
        """Create a consistent daily snapshot, or refresh today on demand; retain seven."""
        folder = self.data_dir / "backups"
        folder.mkdir(exist_ok=True)
        target = folder / ("family-backup-" + datetime.now(timezone.utc).strftime("%Y-%m-%d") + ".sqlite3")
        with self.backup_lock:
            if target.exists() and not force:
                return target
            temporary = target.with_suffix(".pending")
            with self.connect() as source:
                with closing(sqlite3.connect(temporary)) as destination:
                    source.backup(destination)
                    if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise RuntimeError("Backup integrity check failed.")
            temporary.replace(target)
            for old in sorted(folder.glob("family-backup-????-??-??.sqlite3"), reverse=True)[7:]:
                old.unlink()
        return target


class FamilyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32

    def __init__(self, address, store, index_path=None, cookie_secure=False, public_origin="", allowed_hosts=None, local_setup=False, instance_id=""):
        self.store = store
        self.index_path = Path(index_path or BASE_DIR / "index.html")
        self.cookie_secure = cookie_secure
        self.public_origin = public_origin.rstrip("/")
        self.configured_hosts = tuple(dict.fromkeys(value.lower().strip() for value in (allowed_hosts or []) if value.strip()))
        self.allowed_hosts = set(self.configured_hosts)
        self.local_setup = bool(local_setup)
        self.instance_id = str(instance_id)[:100]
        super().__init__(address, FamilyHandler)

    def connection_info(self):
        # These are configured addresses, never values supplied in a request or
        # forwarded headers. Desktop adapters are added by the trusted launcher.
        transport = "http"
        public = None
        if self.public_origin:
            try:
                origin = urlsplit(self.public_origin)
                if (origin.scheme in {"http", "https"} and origin.hostname and
                        not (origin.username or origin.password or origin.path or origin.query or origin.fragment)):
                    origin.port
                    public = origin
                    transport = origin.scheme
            except ValueError:
                pass
        allowed = self.allowed_hosts.copy()
        hosts = [host for host in self.configured_hosts if host in allowed]
        hosts.extend(sorted(allowed.difference(hosts)))
        private_ranges = (ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12"),
                          ipaddress.ip_network("192.168.0.0/16"))
        urls = []
        for host in hosts:
            try:
                if not host or any(character.isspace() for character in host):
                    continue
                parsed = urlsplit("http://" + host)
                if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
                    continue
                address = ipaddress.ip_address(parsed.hostname or "")
                if address.version != 4 or not any(address in network for network in private_ranges):
                    continue
                port = parsed.port if parsed.port is not None else self.server_address[1]
                if not 1 <= port <= 65535:
                    continue
                # TLS belongs to a configured reverse proxy, not this HTTP
                # socket. Do not invent HTTPS endpoints on unrelated NICs.
                if transport == "https" and (public.hostname != str(address) or (public.port or 443) != port):
                    continue
                url = f"{transport}://{address}:{port}"
                if url not in urls:
                    urls.append(url)
            except ValueError:
                continue
        return {"networkUrls": urls, "transport": transport}


class FamilyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Homeboard"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def log_message(self, fmt, *args):
        # Request bodies and query strings can contain secrets; never log them.
        LOG.info("%s %s %s", self.client_address[0], self.command, urlsplit(self.path).path)

    def headers_common(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                         "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
                         "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")

    def send_json(self, status, value, cookie=None, download=False):
        body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.headers_common()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        if download:
            self.send_header("Content-Disposition", 'attachment; filename="family-backup.json"')
        self.end_headers()
        self.wfile.write(body)

    def cookie(self, token="", clear=False):
        value = f"family_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={0 if clear else SESSION_SECONDS}"
        return value + ("; Secure" if self.server.cookie_secure else "")

    def token(self):
        try:
            jar = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
            value = jar.get("family_session")
            return value.value if value else ""
        except http.cookies.CookieError:
            return ""

    def authorize(self, write=False, admin=False):
        session = self.server.store.session(self.token())
        if not session:
            raise APIError(401, "Please sign in.")
        if admin and session["role"] != "admin":
            raise APIError(403, "Administrator access is required.")
        if write:
            csrf = self.headers.get("X-CSRF-Token", "")
            if not hmac.compare_digest(csrf.encode(), session["csrf"].encode()):
                raise APIError(403, "Session check failed. Reload and try again.")
        return session

    def check_origin(self, path):
        host = self.headers.get("Host", "")
        require(bool(host) and not any(char.isspace() for char in host), "Host header is invalid.")
        try:
            parsed = urlsplit("http://" + host)
            hostname = parsed.hostname or ""
            parsed.port
        except ValueError:
            raise APIError(400, "Host header is invalid.") from None
        if parsed.username or parsed.password or parsed.path:
            raise APIError(400, "Host header is invalid.")
        loopback_health = path == "/healthz" and self.client_address[0] in {"127.0.0.1", "::1"}
        if self.server.allowed_hosts and not loopback_health:
            if host.lower() not in self.server.allowed_hosts and hostname.lower() not in self.server.allowed_hosts:
                raise APIError(403, "This hostname is not allowed.")
        origin = self.headers.get("Origin")
        if origin:
            expected = self.server.public_origin or (("https://" if self.server.cookie_secure else "http://") + host)
            if origin != expected:
                raise APIError(403, "Cross-origin requests are not allowed.")
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise APIError(403, "Cross-site requests are not allowed.")

    def read_json(self):
        if self.headers.get("Transfer-Encoding"):
            raise APIError(400, "Chunked requests are not supported.")
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise APIError(415, "Send JSON data.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise APIError(400, "Invalid request length.") from None
        if length <= 0 or length > MAX_BODY:
            raise APIError(413, "Request is empty or too large.")
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise APIError(400, "Incomplete request body.")
            body = json.loads(raw.decode("utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise APIError(400, "Invalid JSON data.") from None
        require(isinstance(body, dict), "Request must be a JSON object.")
        return body

    def me(self, token=None):
        session = self.server.store.session(self.token() if token is None else token)
        result = {"initialized": self.server.store.initialized(), "authenticated": bool(session)}
        if session:
            result["user"] = {key: session[key] for key in ("id", "name", "role")}
            result["csrf"] = session["csrf"]
        return result

    def local_setup_available(self):
        if not self.server.local_setup or self.server.public_origin or self.server.store.initialized():
            return False
        if self.client_address[0] not in {"127.0.0.1", "::1"}:
            return False
        try:
            hostname = urlsplit("http://" + self.headers.get("Host", "")).hostname
        except ValueError:
            return False
        return hostname in {"localhost", "127.0.0.1", "::1"}

    def route(self):
        path = urlsplit(self.path).path
        self.check_origin(path)
        store = self.server.store
        if self.command == "GET":
            if path in {"/healthz", "/api/health"}:
                return self.send_json(200, {"ok": True, "product": "homeboard", "version": PRODUCT_VERSION,
                                           "instance_id": self.server.instance_id})
            if path in {"/", "/display", "/index.html"}:
                try:
                    body = self.server.index_path.read_bytes()
                except OSError:
                    raise APIError(503, "The dashboard interface is not installed.") from None
                self.send_response(200)
                self.headers_common()
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/product":
                return self.send_json(200, {"name": "Homeboard", "version": PRODUCT_VERSION,
                                           "edition": "Self-hosted", "setupRequired": not store.initialized(),
                                           "localSetupAvailable": self.local_setup_available()})
            if path == "/api/setup/local":
                if not self.local_setup_available():
                    raise APIError(403, "Automatic setup is available only on this computer before setup is complete.")
                return self.send_json(200, {"setupKey": store.setup_key})
            if path == "/api/system":
                user = self.authorize(admin=True)
                return self.send_json(200, {**store.system_info(user["id"]), **self.server.connection_info()})
            if path == "/api/me":
                return self.send_json(200, self.me())
            if path == "/api/state":
                user = self.authorize()
                return self.send_json(200, store.get_state(user["role"]))
            if path == "/api/events":
                self.authorize()
                return self.stream_events()
            if path == "/api/users":
                self.authorize(admin=True)
                return self.send_json(200, {"users": store.users()})
            if path == "/api/backup":
                self.authorize(admin=True)
                return self.send_json(200, {**store.get_state(), "exportedAt": datetime.now(timezone.utc).isoformat()}, download=True)
        elif self.command == "POST":
            data = self.read_json()
            if path == "/api/setup":
                store.throttle(self.client_address[0], "__setup__")
                if store.initialized():
                    raise APIError(409, "This household is already initialized.")
                user, recovery_code = store.setup_household(data)
                token = store.new_session(user["id"])
                backup_created = False
                try:
                    store.backup(force=True)
                    backup_created = True
                except Exception:
                    # The owner has committed. Preserve successful setup and
                    # the only plaintext recovery kit even if storage is full.
                    LOG.exception("First household backup failed; setup is complete. Create a backup from Settings after checking storage.")
                return self.send_json(201, {**self.me(token), "recoveryCode": recovery_code,
                                            "backupCreated": backup_created}, cookie=self.cookie(token))
            if path == "/api/recover":
                username = string(data.get("username"), "Username", 40).strip().lower()
                code = string(data.get("recoveryCode"), "Recovery code", 200)
                password = password_value(data.get("password"))
                store.throttle(self.client_address[0], "__recover__:" + username)
                recovery_code = store.recover_account(username, code, password)
                return self.send_json(200, {"authenticated": False, "recoveryCode": recovery_code},
                                      cookie=self.cookie(clear=True))
            if path == "/api/recovery-code":
                user = self.authorize(write=True, admin=True)
                password = string(data.get("password"), "Password", 256, required=True)
                store.throttle(self.client_address[0], "__recovery_code__:" + user["id"])
                recovery_code = store.rotate_recovery_code(user["id"], password)
                return self.send_json(200, {"recoveryCode": recovery_code})
            if path == "/api/backups":
                self.authorize(write=True, admin=True)
                target = store.backup(force=True)
                return self.send_json(201, {"createdAt": datetime.fromtimestamp(target.stat().st_mtime, timezone.utc).isoformat(),
                                           "filename": target.name})
            if path == "/api/login":
                username = string(data.get("username"), "Username", 40).strip().lower()
                password = string(data.get("password"), "Password", 256)
                store.throttle(self.client_address[0], username)
                user = store.login(username, password)
                token = store.new_session(user["id"])
                return self.send_json(200, self.me(token), cookie=self.cookie(token))
            if path == "/api/logout":
                self.authorize(write=True)
                store.logout(self.token())
                return self.send_json(200, {"authenticated": False}, cookie=self.cookie(clear=True))
            if path == "/api/users":
                self.authorize(write=True, admin=True)
                name, username, password = account_fields(data)
                role = choice(data.get("role"), {"adult", "display"}, "Account role", "adult")
                user = store.create_user(name, username, password, role)
                return self.send_json(201, {"user": user})
        elif self.command == "PUT" and path == "/api/state":
            user = self.authorize(write=True)
            if user["role"] == "display":
                raise APIError(403, "This display is read-only.")
            data = self.read_json()
            return self.send_json(200, store.put_state(data.get("state"), data.get("revision")))
        elif self.command == "DELETE" and path.startswith("/api/users/"):
            user = self.authorize(write=True, admin=True)
            target = identifier(path.rsplit("/", 1)[-1], "Account ID")
            store.delete_user(target, user["id"])
            return self.send_json(200, {"ok": True})
        raise APIError(404, "Page or operation was not found.")

    def stream_events(self):
        self.send_response(200)
        self.headers_common()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        token, last_revision = self.token(), -1
        deadline = time.monotonic() + 240
        try:
            while time.monotonic() < deadline:
                if not self.server.store.session(token):
                    self.wfile.write(b"event: expired\ndata: {}\n\n")
                    self.wfile.flush()
                    break
                current = self.server.store.revision()
                if current != last_revision:
                    body = f"id: {current}\ndata: {{\"revision\":{current}}}\n\n".encode()
                    self.wfile.write(body)
                    last_revision = current
                else:
                    self.wfile.write(b": heartbeat\n\n")
                self.wfile.flush()
                with self.server.store.changed:
                    # Predicate avoids losing a commit between sending and waiting.
                    self.server.store.changed.wait_for(
                        lambda: self.server.store.revision() != last_revision or not self.server.store.session(token),
                        timeout=5)
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            pass
        finally:
            self.close_connection = True

    def handle_request(self):
        try:
            self.route()
        except APIError as error:
            # Close after rejected requests so unread bodies never become requests.
            self.close_connection = True
            self.send_json(error.status, {"error": error.message, **error.details})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except Exception:
            LOG.exception("Request failed for %s", urlsplit(self.path).path)
            self.close_connection = True
            self.send_json(500, {"error": "The server could not complete this operation."})

    do_GET = handle_request
    do_POST = handle_request
    do_PUT = handle_request
    do_DELETE = handle_request


def backup_loop(store, stop):
    while not stop.is_set():
        try:
            store.backup()
        except Exception:
            LOG.exception("Daily backup failed; check free space and data-directory permissions.")
        stop.wait(60 * 60)


def main(stop_event=None, allowed_hosts_provider=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = FamilyStore(os.environ.get("DATA_DIR", BASE_DIR / "data"), os.environ.get("SETUP_KEY"))
    server = FamilyServer((os.environ.get("HOST", "0.0.0.0"), int(os.environ.get("PORT", "8080"))), store,
                          cookie_secure=os.environ.get("COOKIE_SECURE") == "1",
                          public_origin=os.environ.get("PUBLIC_ORIGIN", ""),
                          allowed_hosts=os.environ.get("ALLOWED_HOSTS", "").split(","),
                          local_setup=os.environ.get("LOCAL_SETUP") == "1",
                          instance_id=os.environ.get("HOMEBOARD_INSTANCE_ID", ""))
    stop = stop_event if stop_event is not None else threading.Event()
    backup_thread = threading.Thread(target=backup_loop, args=(store, stop), daemon=True)
    backup_thread.start()
    refresh_thread = None
    if allowed_hosts_provider is not None and server.local_setup and not server.public_origin:
        def refresh_hosts():
            while not stop.is_set():
                try:
                    hosts = allowed_hosts_provider()
                    refreshed = {host.lower().strip() for host in hosts if isinstance(host, str) and host.strip()}
                    if refreshed:
                        server.allowed_hosts = refreshed
                except Exception:
                    LOG.warning("Could not refresh local addresses; retaining the previous hostname allowlist.")
                stop.wait(30)
        refresh_thread = threading.Thread(target=refresh_hosts, daemon=True)
        refresh_thread.start()
    if stop_event is not None:
        def stop_server():
            stop.wait()
            server.shutdown()
        threading.Thread(target=stop_server, daemon=True).start()
    LOG.info("Family dashboard listening on %s:%s", *server.server_address)
    if not server.cookie_secure:
        LOG.info("HTTP testing mode: configure trusted HTTPS and COOKIE_SECURE=1 before daily credential use.")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        backup_thread.join(timeout=5)
        if refresh_thread is not None:
            refresh_thread.join(timeout=2)


if __name__ == "__main__":
    main()
