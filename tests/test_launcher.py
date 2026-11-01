"""Desktop lifecycle checks without starting processes or changing Windows settings."""
import importlib.util
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, call, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("homeboard_launcher_under_test", ROOT / "launcher.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class FakeLock:
    def __init__(self, acquired=True):
        self.acquired = acquired

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class LauncherCase(unittest.TestCase):
    def setUp(self):
        base = ROOT / "tests" / ".temporary"
        base.mkdir(exist_ok=True)
        self.folder = tempfile.TemporaryDirectory(dir=base)
        self.paths = launcher.AppPaths(self.folder.name)
        self.paths.ensure()
        self.config = launcher.read_config(self.paths)
        launcher.write_config(self.paths, self.config)

    def tearDown(self):
        self.folder.cleanup()

    def test_windows_profile_paths_and_existing_data_survive_configuration(self):
        with patch.dict(launcher.os.environ, {"LOCALAPPDATA": self.folder.name}):
            paths = launcher.AppPaths()
        self.assertEqual(paths.root, Path(self.folder.name).resolve() / "Homeboard")
        self.assertEqual(paths.data, paths.root / "data")
        sentinel = self.paths.data / "family.sqlite3"
        sentinel.write_bytes(b"existing family data")
        self.paths.ensure()
        self.config["port"] = 8789
        launcher.write_config(self.paths, self.config)
        self.assertEqual(sentinel.read_bytes(), b"existing family data")
        self.assertEqual(launcher.read_config(self.paths), self.config)
        self.assertFalse(list(self.paths.root.glob("*.tmp")))

    def test_invalid_configuration_is_not_overwritten(self):
        self.paths.config.write_text('{"port": 8000}', encoding="utf-8")
        with self.assertRaises(launcher.LaunchError):
            launcher.read_config(self.paths)
        self.assertEqual(self.paths.config.read_text(), '{"port": 8000}')

    def test_health_requires_our_product_instance_and_success(self):
        connection = MagicMock()
        response = connection.getresponse.return_value
        response.status = 200
        for body, expected in [
            ({"ok": True, "product": "homeboard", "instance_id": self.config["instance_id"]}, True),
            ({"ok": True, "product": "other", "instance_id": self.config["instance_id"]}, False),
            ({"ok": True, "product": "homeboard", "instance_id": "another-profile"}, False),
            ({"ok": False, "product": "homeboard", "instance_id": self.config["instance_id"]}, False),
            (["unexpected JSON"], False),
        ]:
            with self.subTest(body=body), patch.object(launcher.http.client, "HTTPConnection", return_value=connection):
                response.read.return_value = json.dumps(body).encode()
                self.assertIs(launcher.is_healthy(8787, self.config["instance_id"]), expected)
        response.read.return_value = b"<html>some other app</html>"
        with patch.object(launcher.http.client, "HTTPConnection", return_value=connection):
            self.assertFalse(launcher.is_healthy(8787, self.config["instance_id"]))
        connection.close.assert_called()
        connection.request.assert_called_with("GET", "/api/health", headers={"Host": "127.0.0.1:8787"})

    def test_busy_default_chooses_an_available_port_and_persists_it(self):
        with patch.object(launcher, "InstanceLock", return_value=FakeLock()), \
                patch.object(launcher, "is_healthy", return_value=False), \
                patch.object(launcher, "port_available", side_effect=lambda port: port == 8789), \
                patch.object(launcher, "start_worker") as start, \
                patch.object(launcher, "wait_until_healthy", return_value=True):
            self.assertEqual(launcher.ensure_running(self.paths), "http://127.0.0.1:8789/")
        start.assert_called_once_with(self.paths)
        self.assertEqual(launcher.read_config(self.paths)["port"], 8789)
        self.assertEqual(launcher.read_config(self.paths)["instance_id"], self.config["instance_id"])

    def test_busy_port_range_fails_without_starting_a_process(self):
        with patch.object(launcher, "port_available", return_value=False):
            with self.assertRaisesRegex(launcher.LaunchError, "free port"):
                launcher.choose_port(8787)

    def test_existing_healthy_worker_is_reused_without_spawn(self):
        with patch.object(launcher, "InstanceLock", return_value=FakeLock()), \
                patch.object(launcher, "is_healthy", return_value=True), \
                patch.object(launcher, "start_worker") as start:
            self.assertEqual(launcher.ensure_running(self.paths), "http://127.0.0.1:8787/")
        start.assert_not_called()

    def test_starting_worker_is_waited_for_without_duplicate_spawn(self):
        with patch.object(launcher, "InstanceLock", side_effect=[FakeLock(), FakeLock(False)]), \
                patch.object(launcher, "is_healthy", return_value=False), \
                patch.object(launcher, "wait_until_healthy", return_value=True), \
                patch.object(launcher, "start_worker") as start:
            self.assertEqual(launcher.ensure_running(self.paths), "http://127.0.0.1:8787/")
        start.assert_not_called()

    def test_unhealthy_existing_worker_does_not_spawn_a_second(self):
        with patch.object(launcher, "InstanceLock", side_effect=[FakeLock(), FakeLock(False)]), \
                patch.object(launcher, "is_healthy", return_value=False), \
                patch.object(launcher, "wait_until_healthy", return_value=False), \
                patch.object(launcher, "start_worker") as start:
            with self.assertRaisesRegex(launcher.LaunchError, "not responding"):
                launcher.ensure_running(self.paths)
        start.assert_not_called()

    def test_frozen_worker_has_hidden_window_and_no_shell(self):
        with patch.object(launcher, "IS_WINDOWS", True), \
                patch.object(launcher.sys, "frozen", True, create=True), \
                patch.object(launcher.sys, "executable", r"C:\Program Files\Homeboard\Homeboard.exe"), \
                patch.object(launcher.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True), \
                patch.object(launcher.subprocess, "Popen") as popen:
            launcher.start_worker(self.paths)
        args, kwargs = popen.call_args
        self.assertEqual(args[0], [r"C:\Program Files\Homeboard\Homeboard.exe", "--serve", "--app-dir", str(self.paths.root)])
        self.assertEqual(kwargs["creationflags"], 0x08000000)
        self.assertEqual(kwargs["stdin"], launcher.subprocess.DEVNULL)
        self.assertFalse(kwargs.get("shell", False))

    def test_environment_allows_specific_private_hosts_and_local_setup(self):
        results = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))
                   for ip in ("192.168.1.6", "10.0.0.4", "8.8.8.8", "127.0.0.1", "169.254.1.1")]
        with patch.object(launcher.socket, "getaddrinfo", return_value=results):
            env = launcher.server_environment(self.paths, self.config)
        self.assertEqual(env["DATA_DIR"], str(self.paths.data))
        self.assertEqual(env["LOCAL_SETUP"], "1")
        self.assertEqual(env["HOMEBOARD_INSTANCE_ID"], self.config["instance_id"])
        hosts = set(env["ALLOWED_HOSTS"].split(","))
        self.assertEqual(hosts, {"127.0.0.1:8787", "localhost:8787", "[::1]:8787", "192.168.1.6:8787", "10.0.0.4:8787"})
        self.assertNotIn("*", env["ALLOWED_HOSTS"])

    def test_double_click_opens_browser_and_background_does_not(self):
        with patch.object(launcher, "configure_logging"), \
                patch.object(launcher, "ensure_running", return_value="http://127.0.0.1:8787/"), \
                patch.object(launcher.webbrowser, "open", return_value=True) as browser:
            self.assertEqual(launcher.main(["--app-dir", str(self.paths.root)]), 0)
            browser.assert_called_once_with("http://127.0.0.1:8787/", new=2)
            browser.reset_mock()
            self.assertEqual(launcher.main(["--background", "--app-dir", str(self.paths.root)]), 0)
            browser.assert_not_called()

    def test_worker_passes_persistent_storage_and_cooperative_shutdown_to_server(self):
        fake_server = MagicMock()
        signal = MagicMock()
        with patch.object(launcher, "InstanceLock", return_value=FakeLock()), \
                patch.object(launcher, "StopSignal", return_value=signal), \
                patch.object(launcher, "private_addresses", return_value=[]), \
                patch.object(launcher, "IS_WINDOWS", True), \
                patch.dict(sys.modules, {"server": fake_server}), \
                patch.dict(launcher.os.environ, {"SETUP_KEY": "unrelated inherited secret"}):
            self.assertEqual(launcher.serve(self.paths), 0)
            self.assertNotIn("SETUP_KEY", launcher.os.environ)
            self.assertEqual(launcher.os.environ["DATA_DIR"], str(self.paths.data))
            stop = fake_server.main.call_args.kwargs["stop_event"]
            self.assertTrue(stop.is_set())
            provider = fake_server.main.call_args.kwargs["allowed_hosts_provider"]
            self.assertIn("127.0.0.1:8787", provider())
        signal.close.assert_called_once()

    def test_windows_mutex_releases_owned_handle_and_closes_on_timeout(self):
        kernel = MagicMock()
        kernel.CreateMutexW.return_value = 9876543210  # More than 32 bits.
        for result, acquired in [(launcher.WAIT_OBJECT_0, True), (launcher.WAIT_ABANDONED, True), (launcher.WAIT_TIMEOUT, False)]:
            kernel.reset_mock()
            kernel.WaitForSingleObject.return_value = result
            with patch.object(launcher, "IS_WINDOWS", True), patch.object(launcher, "windows_kernel", return_value=kernel):
                with launcher.InstanceLock(self.paths, "worker") as lock:
                    self.assertIs(lock.acquired, acquired)
            kernel.CloseHandle.assert_called_once_with(9876543210)
            self.assertEqual(kernel.ReleaseMutex.call_count, int(acquired))

    @unittest.skipUnless(sys.platform == "win32", "Native Windows handle smoke check")
    def test_native_windows_controls_work_across_threads_without_processes(self):
        results = []

        def contender():
            with launcher.InstanceLock(self.paths, "native-test") as lock:
                results.append(lock.acquired)

        with launcher.InstanceLock(self.paths, "native-test") as owner:
            self.assertTrue(owner.acquired)
            thread = threading.Thread(target=contender)
            thread.start()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
        contender()
        self.assertEqual(results, [False, True])
        signal = launcher.StopSignal(self.paths)
        stopped = threading.Event()
        watcher = threading.Thread(target=signal.watch, args=(stopped,))
        watcher.start()
        kernel = launcher.windows_kernel()
        handle = kernel.OpenEventW(launcher.EVENT_MODIFY_STATE, False, self.paths.control_name + "-stop")
        try:
            self.assertTrue(handle)
            self.assertTrue(kernel.SetEvent(handle))
            self.assertTrue(stopped.wait(timeout=2))
        finally:
            if handle:
                kernel.CloseHandle(handle)
            stopped.set()
            watcher.join(timeout=2)
            signal.close()

    def test_stop_only_signals_owned_event_and_waits_for_worker(self):
        kernel = MagicMock()
        kernel.OpenEventW.return_value = 123
        with patch.object(launcher, "IS_WINDOWS", True), \
                patch.object(launcher, "windows_kernel", return_value=kernel), \
                patch.object(launcher, "InstanceLock", side_effect=[FakeLock(), FakeLock(False), FakeLock()]) as locks, \
                patch.object(launcher.subprocess, "Popen") as spawn:
            self.assertEqual(launcher.stop_worker(self.paths), 0)
        kernel.OpenEventW.assert_called_once_with(launcher.EVENT_MODIFY_STATE, False, self.paths.control_name + "-stop")
        kernel.SetEvent.assert_called_once_with(123)
        kernel.CloseHandle.assert_called_once_with(123)
        locks.assert_has_calls([call(self.paths, "worker", launcher.STOP_TIMEOUT)])
        spawn.assert_not_called()

    def test_stop_never_targets_an_arbitrary_process_without_owned_control(self):
        kernel = MagicMock()
        kernel.OpenEventW.return_value = 0
        with patch.object(launcher, "IS_WINDOWS", True), \
                patch.object(launcher, "windows_kernel", return_value=kernel), \
                patch.object(launcher, "InstanceLock", side_effect=[FakeLock(), FakeLock(False)]):
            with self.assertRaisesRegex(launcher.LaunchError, "shutdown control"):
                launcher.stop_worker(self.paths)
        kernel.SetEvent.assert_not_called()


if __name__ == "__main__":
    unittest.main()
