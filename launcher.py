"""Homeboard's desktop entry point for Windows, macOS and Linux.

The installer freezes this file as Homeboard.exe. A normal launch opens the
browser after the per-user server is healthy; --background is for login startup.
--serve and --stop are the cooperating worker and installer entry points.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import html
import http.client
import ipaddress
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal as process_signal
import socket
import subprocess
import sys
import threading
import time
import uuid
import webbrowser

PRODUCT = "homeboard"
FIRST_PORT = 8787
LAST_PORT = 8797
START_TIMEOUT = 15.0
STOP_TIMEOUT = 15.0
LOG = logging.getLogger("homeboard.launcher")
IS_WINDOWS = sys.platform == "win32"
WAIT_OBJECT_0 = 0
WAIT_ABANDONED = 0x80
WAIT_TIMEOUT = 0x102
EVENT_MODIFY_STATE = 0x0002


class LaunchError(Exception):
    """An actionable error that is safe to show in a desktop dialog."""


class AppPaths:
    def __init__(self, root=None):
        if root is None:
            if IS_WINDOWS:
                local = os.environ.get("LOCALAPPDATA")
                if not local:
                    raise LaunchError("Windows could not find your local application folder (LOCALAPPDATA).")
                root = Path(local) / "Homeboard"
            elif sys.platform == "darwin":
                root = Path.home() / "Library" / "Application Support" / "Homeboard"
            else:
                local = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
                if not local.is_absolute():
                    local = Path.home() / ".local" / "share"
                root = local / "homeboard"
        self.root = Path(root).expanduser().resolve()
        self.data = self.root / "data"
        self.logs = self.root / "logs"
        self.config = self.root / "launcher.json"
        # No credential is encoded in this name. It scopes controls to this profile.
        scope = hashlib.sha256(os.path.normcase(str(self.root)).encode("utf-8")).hexdigest()[:24]
        self.control_name = "Local\\Homeboard-" + scope

    def ensure(self):
        for path in (self.root, self.data, self.logs):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)


def windows_kernel():
    """Declare HANDLE signatures explicitly; 64-bit Windows must not truncate them."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    declarations = {
        "CreateMutexW": ([ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        "ReleaseMutex": ([wintypes.HANDLE], wintypes.BOOL),
        "CreateEventW": ([ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        "OpenEventW": ([wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        "SetEvent": ([wintypes.HANDLE], wintypes.BOOL),
        "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
    }
    for name, (arguments, result) in declarations.items():
        function = getattr(kernel, name)
        function.argtypes = arguments
        function.restype = result
    return kernel


class InstanceLock:
    """A Windows named mutex; a file lock keeps source development portable."""
    def __init__(self, paths, purpose, timeout=0):
        self.paths, self.purpose, self.timeout = paths, purpose, timeout
        self.handle = None
        self.file = None
        self.acquired = False
        self.kernel = None

    def __enter__(self):
        if IS_WINDOWS:
            self.kernel = windows_kernel()
            self.handle = self.kernel.CreateMutexW(None, False, self.paths.control_name + "-" + self.purpose)
            if not self.handle:
                raise LaunchError("Windows could not create the Homeboard startup lock.")
            result = self.kernel.WaitForSingleObject(self.handle, int(self.timeout * 1000))
            if result in (WAIT_OBJECT_0, WAIT_ABANDONED):
                self.acquired = True
            elif result != WAIT_TIMEOUT:
                self.close()
                raise LaunchError("Windows could not check the Homeboard startup lock.")
        else:
            import fcntl
            self.file = (self.paths.root / ("." + self.purpose + ".lock")).open("a+b")
            deadline = time.monotonic() + self.timeout
            while True:
                try:
                    fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.acquired = True
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(0.05)
        return self

    def close(self):
        if self.handle:
            if self.acquired:
                self.kernel.ReleaseMutex(self.handle)
            self.kernel.CloseHandle(self.handle)
            self.handle = None
        if self.file:
            self.file.close()
            self.file = None
        self.acquired = False

    def __exit__(self, *_):
        self.close()


class StopSignal:
    """An installer may signal this event; it cannot stop an unrelated process."""
    def __init__(self, paths):
        self.kernel = windows_kernel()
        # Auto-reset means a completed stop cannot poison the next worker launch.
        self.handle = self.kernel.CreateEventW(None, False, False, paths.control_name + "-stop")
        if not self.handle:
            raise LaunchError("Windows could not create the Homeboard shutdown event.")

    def watch(self, stop):
        while not stop.is_set():
            result = self.kernel.WaitForSingleObject(self.handle, 250)
            if result == WAIT_OBJECT_0:
                stop.set()
                return
            if result != WAIT_TIMEOUT:
                LOG.error("The Windows shutdown event failed.")
                return

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class FileStopSignal:
    """Cooperative Unix shutdown scoped to a private, locked storage profile."""
    def __init__(self, paths, config):
        self.path = paths.root / '.stop-request.json'
        self.instance_id = config['instance_id']
        # A completed stop must not affect the next launch. The startup lock
        # prevents a new stop request until this worker has reported healthy.
        self.path.unlink(missing_ok=True)

    def watch(self, stop):
        while not stop.wait(0.25):
            try:
                with self.path.open('rb') as request:
                    raw = request.read(4097)
                value = json.loads(raw) if len(raw) <= 4096 else {}
                if isinstance(value, dict) and value.get('instance_id') == self.instance_id:
                    stop.set()
            except (OSError, ValueError):
                pass

    def close(self):
        self.path.unlink(missing_ok=True)


def configure_logging(paths, worker=False):
    handler = RotatingFileHandler(paths.logs / ("server.log" if worker else "launcher.log"),
                                  maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def read_config(paths):
    if not paths.config.exists():
        return {"version": 1, "port": FIRST_PORT, "instance_id": str(uuid.uuid4())}
    try:
        value = json.loads(paths.config.read_text(encoding="utf-8"))
        if (not isinstance(value, dict) or value.get("version") != 1
                or type(value.get("port")) is not int or not FIRST_PORT <= value["port"] <= LAST_PORT
                or str(uuid.UUID(value.get("instance_id", ""))) != value["instance_id"]):
            raise ValueError("Invalid launcher configuration")
        return value
    except (ValueError, TypeError, AttributeError, OSError) as error:
        raise LaunchError(f"Homeboard could not read {paths.config}. Your family data is still in {paths.data}. "
                          "Check the launcher log or contact support before changing this file.") from error


def write_config(paths, value):
    temporary = paths.config.with_name("launcher-" + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, paths.config)
    finally:
        temporary.unlink(missing_ok=True)


def is_healthy(port, instance_id):
    """Bypass browser/proxy settings, redirects, and arbitrary HTTP responders."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.5)
    try:
        connection.request("GET", "/api/health", headers={"Host": f"127.0.0.1:{port}"})
        response = connection.getresponse()
        if response.status != 200:
            return False
        body = response.read(4097)
        if len(body) > 4096:
            return False
        result = json.loads(body)
        return (isinstance(result, dict) and result.get("ok") is True
                and result.get("product") == PRODUCT and result.get("instance_id") == instance_id)
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def port_available(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        try:
            if IS_WINDOWS:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def choose_port(preferred):
    candidates = [preferred] + [port for port in range(FIRST_PORT, LAST_PORT + 1) if port != preferred]
    for port in candidates:
        if port_available(port):
            return port
    raise LaunchError(f"Homeboard could not find a free port between {FIRST_PORT} and {LAST_PORT}. "
                      "Close the application using these ports, then open Homeboard again.")


def private_addresses():
    addresses = set()
    try:
        for entry in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM):
            address = ipaddress.ip_address(entry[4][0])
            if any(address in ipaddress.ip_network(network) for network in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
                addresses.add(str(address))
    except (OSError, ValueError):
        LOG.warning("Could not discover private network addresses; local browser access remains available.")
    if not addresses:
        # UDP connect asks the OS which local address its default route uses;
        # no data is sent and no internet response or DNS lookup is required.
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
                route.connect(('192.0.2.1', 9))
                address = ipaddress.ip_address(route.getsockname()[0])
                if any(address in ipaddress.ip_network(network) for network in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
                    addresses.add(str(address))
        except (OSError, ValueError):
            pass
    return sorted(addresses)


def server_environment(paths, config):
    port = config["port"]
    hosts = {"localhost", "127.0.0.1", "[::1]", *private_addresses()}
    return {
        "DATA_DIR": str(paths.data), "PORT": str(port), "HOST": "0.0.0.0",
        "LOCAL_SETUP": "1", "HOMEBOARD_INSTANCE_ID": config["instance_id"],
        "COOKIE_SECURE": "0", "PUBLIC_ORIGIN": "",
        "ALLOWED_HOSTS": ",".join(sorted(f"{host}:{port}" for host in hosts)),
    }


def worker_command(paths):
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command.append(str(Path(__file__).resolve()))
    return command + ["--serve", "--app-dir", str(paths.root)]


def start_worker(paths):
    options = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
               "close_fds": True, "cwd": str(paths.root)}
    if IS_WINDOWS:
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        options["start_new_session"] = True
    return subprocess.Popen(worker_command(paths), **options)


def wait_until_healthy(config, deadline, process=None):
    while time.monotonic() < deadline:
        if is_healthy(config["port"], config["instance_id"]):
            return True
        if process is not None and process.poll() is not None:
            return False
        time.sleep(0.2)
    return False


def ensure_running(paths):
    with InstanceLock(paths, "start", START_TIMEOUT + 5) as startup:
        if not startup.acquired:
            raise LaunchError("Homeboard is taking longer to start. Wait a moment, then open it again.")
        config = read_config(paths)
        if is_healthy(config["port"], config["instance_id"]):
            return f"http://127.0.0.1:{config['port']}/"
        deadline = time.monotonic() + START_TIMEOUT
        with InstanceLock(paths, "worker") as worker:
            already_running = not worker.acquired
        if already_running:
            if wait_until_healthy(config, deadline):
                return f"http://127.0.0.1:{config['port']}/"
            raise LaunchError(f"Homeboard is running but is not responding. Check {paths.logs / 'server.log'}, "
                              "or run Homeboard.exe --stop before opening it again.")
        # If another application wins the short bind-to-start race, try the next
        # port only after our child exits; never leave multiple workers running.
        while time.monotonic() < deadline:
            config["port"] = choose_port(config["port"])
            write_config(paths, config)
            LOG.info("Starting Homeboard on port %s", config["port"])
            process = start_worker(paths)
            if wait_until_healthy(config, deadline, process):
                return f"http://127.0.0.1:{config['port']}/"
            if process.poll() is not None and not port_available(config["port"]):
                continue
            break
        raise LaunchError(f"Homeboard could not start. Check {paths.logs / 'server.log'} "
                          "for details, then open Homeboard again.")


def serve(paths):
    with InstanceLock(paths, "worker") as worker:
        if not worker.acquired:
            LOG.info("A Homeboard worker is already running for this profile.")
            return 0
        if not paths.config.exists():
            raise LaunchError("Open Homeboard normally before starting its background worker.")
        config = read_config(paths)
        os.environ.update(server_environment(paths, config))
        # A machine-wide deployment environment must not override desktop setup.
        os.environ.pop("SETUP_KEY", None)
        stop = threading.Event()
        signal = StopSignal(paths) if IS_WINDOWS else FileStopSignal(paths, config)
        previous_handlers = {}
        if not IS_WINDOWS and threading.current_thread() is threading.main_thread():
            for number in (process_signal.SIGTERM, process_signal.SIGINT):
                previous_handlers[number] = process_signal.signal(number, lambda *_: stop.set())
        watcher = None
        try:
            if signal:
                watcher = threading.Thread(target=signal.watch, args=(stop,), daemon=True)
                watcher.start()
            import server
            server.main(stop_event=stop,
                        allowed_hosts_provider=lambda: server_environment(paths, config)["ALLOWED_HOSTS"].split(","))
        finally:
            stop.set()
            if watcher:
                # Each native wait is at most 250 ms. Finish it before closing
                # the handle; Windows forbids closing a handle during a wait.
                watcher.join()
            if signal:
                signal.close()
            for number, handler in previous_handlers.items():
                process_signal.signal(number, handler)
        return 0


def stop_worker(paths):
    with InstanceLock(paths, "start", STOP_TIMEOUT + 5) as startup:
        if not startup.acquired:
            raise LaunchError("Homeboard is still starting. Wait a moment and try the update again.")
        with InstanceLock(paths, "worker") as worker:
            if worker.acquired:
                return 0
        if not IS_WINDOWS:
            config = read_config(paths)
            if not is_healthy(config['port'], config['instance_id']):
                raise LaunchError('Homeboard is not responding. Check the server log before updating.')
            temporary = paths.root / ('.stop-' + uuid.uuid4().hex + '.tmp')
            try:
                with temporary.open('x', encoding='utf-8') as request:
                    os.chmod(temporary, 0o600)
                    json.dump({'instance_id': config['instance_id']}, request)
                os.replace(temporary, paths.root / '.stop-request.json')
            finally:
                temporary.unlink(missing_ok=True)
            with InstanceLock(paths, 'worker', STOP_TIMEOUT) as stopped:
                if not stopped.acquired:
                    raise LaunchError('Homeboard has not finished saving. Wait a moment before updating.')
            LOG.info('Homeboard stopped gracefully.')
            return 0
        kernel = windows_kernel()
        handle = kernel.OpenEventW(EVENT_MODIFY_STATE, False, paths.control_name + "-stop")
        if not handle:
            raise LaunchError("Homeboard's shutdown control is unavailable. Close Homeboard or sign out of "
                              "Windows, then try the update again. Your family data will be kept.")
        try:
            if not kernel.SetEvent(handle):
                raise LaunchError("Windows could not ask Homeboard to stop. Try the update again after signing out.")
        finally:
            kernel.CloseHandle(handle)
        with InstanceLock(paths, "worker", STOP_TIMEOUT) as stopped:
            if not stopped.acquired:
                raise LaunchError("Homeboard has not finished saving. Wait a moment before trying the update again.")
        LOG.info("Homeboard stopped gracefully.")
        return 0


def show_error(message, paths=None):
    if paths:
        message += f"\n\nLogs: {paths.logs}\nFamily data: {paths.data}"
    if IS_WINDOWS:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
        user32.MessageBoxW.restype = ctypes.c_int
        user32.MessageBoxW(None, message, "Homeboard could not open", 0x10)
    else:
        print(message, file=sys.stderr)
        if paths:
            try:
                page = paths.logs / 'could-not-open.html'
                page.write_text('<!doctype html><meta charset="utf-8"><title>Homeboard</title>'
                    '<body style="font:18px system-ui;max-width:650px;margin:10vh auto;padding:24px">'
                    '<h1>Homeboard could not open.</h1><pre style="white-space:pre-wrap;font:inherit">'
                    + html.escape(message) + '</pre></body>', encoding='utf-8')
                webbrowser.open(page.as_uri(), new=2)
            except OSError:
                pass


def main(argv=None):
    parser = argparse.ArgumentParser(description="Open your Homeboard family dashboard.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--background", action="store_true", help="Start without opening a browser.")
    mode.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    mode.add_argument("--stop", action="store_true", help="Save and stop this profile's server for an update.")
    mode.add_argument('--install', action='store_true', help='Install the Linux bundle for this user.')
    mode.add_argument('--enable-startup', action='store_true', help='Start at login on macOS or Linux.')
    mode.add_argument('--disable-startup', action='store_true', help='Remove macOS or Linux login startup.')
    parser.add_argument("--app-dir", type=Path, help="Override the storage root containing data and logs.")
    arguments = parser.parse_args(argv)
    paths = None
    try:
        paths = AppPaths(arguments.app_dir)
        paths.ensure()
        configure_logging(paths, arguments.serve)
        if arguments.install:
            if not sys.platform.startswith('linux') or not getattr(sys, 'frozen', False):
                raise LaunchError('Use the Linux download and run its install.sh script.')
            import desktop_install
            installed = desktop_install.install_linux(sys.executable, paths, stop_worker)
            subprocess.Popen([str(installed)], start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return 0
        if arguments.enable_startup or arguments.disable_startup:
            import desktop_install
            desktop_install.configure_startup(sys.executable, arguments.enable_startup)
            return 0
        if arguments.serve:
            return serve(paths)
        if arguments.stop:
            return stop_worker(paths)
        url = ensure_running(paths)
        if not arguments.background:
            if not webbrowser.open(url, new=2):
                raise LaunchError(f"Homeboard is ready at {url} but Windows could not open your browser. "
                                  "Copy this address into your browser.")
        return 0
    except Exception as error:
        LOG.exception("Homeboard launch failed.")
        message = str(error) if isinstance(error, LaunchError) else "Homeboard could not open. Check the launcher log for details."
        # Workers and login startup must not create invisible or repeated dialogs.
        if not (arguments.serve or arguments.background):
            show_error(message, paths)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
