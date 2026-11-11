"""Exercise tray startup without importing Windows GUI dependencies."""
import ast
import logging
from pathlib import Path
import socket
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / "tray.py"
FUNCTIONS = {
    "auto_start_web", "_web_port_available", "_start_web", "_start_web_locked",
    "on_icon_ready",
}


def startup_namespace():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    nodes = [node for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS]
    scope = {
        "socket": socket, "threading": threading, "logging": logging,
        "_web_start_lock": threading.Lock(), "web_process": None,
        "action_file_logger": Mock(), "load_config": Mock(return_value={}),
        "get_web_port": Mock(return_value=8002),
        "get_web_status": Mock(return_value="Stopped"),
        "notify_now": Mock(), "wait_until": Mock(),
        "subprocess": SimpleNamespace(Popen=Mock(), CREATE_NO_WINDOW=0, DEVNULL=-3),
        "sys": SimpleNamespace(executable="pythonw.exe"), "BASE_DIR": ".",
        "status_watcher": Mock(), "_log_crash": Mock(),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), scope)
    return scope


class AutoStartTests(unittest.TestCase):
    def setUp(self):
        self.scope = startup_namespace()
        self.icon = Mock()
        self.start = self.scope["_start_web"] = Mock(return_value=True)

    def test_missing_setting_defaults_to_enabled(self):
        self.scope["auto_start_web"](self.icon)
        self.start.assert_called_once_with(self.icon, quiet=True)
        self.scope["action_file_logger"].info.assert_any_call(
            "Web auto-start: ready on port %s", 8002)

    def test_explicit_true_starts(self):
        self.scope["load_config"].return_value = {"web": {"auto_start": True}}
        self.scope["auto_start_web"](self.icon)
        self.start.assert_called_once()

    def test_false_disables(self):
        self.scope["load_config"].return_value = {"web": {"auto_start": False}}
        self.scope["auto_start_web"](self.icon)
        self.start.assert_not_called()

    def test_already_running_is_left_alone(self):
        self.scope["get_web_status"].return_value = "Running"
        self.scope["auto_start_web"](self.icon)
        self.start.assert_not_called()

    def test_failed_start_is_logged_without_raising(self):
        self.start.return_value = False
        self.scope["auto_start_web"](self.icon)
        self.scope["action_file_logger"].warning.assert_called_once()

    def test_start_exception_does_not_escape(self):
        self.start.side_effect = RuntimeError("test startup failure")
        self.scope["auto_start_web"](self.icon)
        self.scope["action_file_logger"].exception.assert_called_once()

    def test_config_exception_does_not_escape(self):
        self.scope["load_config"].side_effect = ValueError("test invalid config")
        self.scope["auto_start_web"](self.icon)
        self.start.assert_not_called()
        self.scope["action_file_logger"].exception.assert_called_once()

    def test_setup_launches_background_worker(self):
        threads = SimpleNamespace(Thread=Mock())
        self.scope["threading"] = threads
        self.scope["on_icon_ready"](self.icon)
        self.assertTrue(self.icon.visible)
        threads.Thread.assert_any_call(
            target=self.scope["auto_start_web"], args=(self.icon,),
            daemon=True, name="qbc-web-auto-start")

    def test_worker_creation_failure_does_not_stop_tray(self):
        self.scope["threading"] = SimpleNamespace(
            Thread=Mock(side_effect=[Mock(), RuntimeError("test thread failure")]))
        self.scope["on_icon_ready"](self.icon)
        self.scope["action_file_logger"].exception.assert_called_once()


class StartGuardTests(unittest.TestCase):
    def setUp(self):
        self.scope = startup_namespace()
        self.icon = Mock()
        self.available = self.scope["_web_port_available"] = Mock(return_value=True)
        self.popen = self.scope["subprocess"].Popen

    def test_running_server_does_not_spawn(self):
        self.scope["get_web_status"].return_value = "Running"
        self.assertTrue(self.scope["_start_web"](self.icon, quiet=True))
        self.popen.assert_not_called()

    def test_occupied_port_does_not_spawn(self):
        self.available.return_value = False
        self.assertFalse(self.scope["_start_web"](self.icon, quiet=True))
        self.popen.assert_not_called()

    def test_successful_start_spawns_one_child(self):
        self.scope["get_web_status"].side_effect = ["Stopped", "Running"]
        self.assertTrue(self.scope["_start_web"](self.icon, quiet=True))
        self.popen.assert_called_once_with(
            ["pythonw.exe", "web.py"], cwd=".", stdout=self.scope["subprocess"].DEVNULL,
            stderr=self.scope["subprocess"].DEVNULL, creationflags=0)

    def test_process_failure_returns_false(self):
        self.popen.side_effect = OSError("test process failure")
        self.assertFalse(self.scope["_start_web"](self.icon, quiet=True))
        self.scope["notify_now"].assert_not_called()

    def test_non_listening_bound_port_is_unavailable(self):
        real_check = startup_namespace()["_web_port_available"]
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as bound:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                bound.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            bound.bind(("127.0.0.1", 0))
            self.assertFalse(real_check(bound.getsockname()[1]))

    def test_freed_port_is_available(self):
        real_check = startup_namespace()["_web_port_available"]
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as bound:
            bound.bind(("127.0.0.1", 0))
            port = bound.getsockname()[1]
        self.assertTrue(real_check(port))


if __name__ == "__main__":
    unittest.main()
