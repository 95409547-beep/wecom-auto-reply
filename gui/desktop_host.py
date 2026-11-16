"""Independent Windows window for the local workbench.

The UI runs in a separate process so WebView2 and the existing Tk coordinator
each retain their required main thread. No customer delivery logic lives here.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

from app_paths import app_dir
from app_session import session_path


def open_desktop_window(owner):
    owner._desktop_focus = getattr(owner, "_desktop_focus", 0) + 1
    process = getattr(owner, "_desktop_process", None)
    if process is not None and process.poll() is None:
        return
    args = [sys.executable]
    if not getattr(sys, "frozen", False):
        args.append(str(app_dir() / "main.py"))
    args.append("--desktop-window")
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    log_path = app_dir() / "logs" / "desktop.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as stream:
        process = subprocess.Popen(args, cwd=app_dir(), env=env,
            stdout=stream, stderr=stream,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    owner._desktop_process = process

    def check_host():
        if owner._should_exit:
            return
        if process.poll() is None:
            owner.root.after(500, check_host)
        else:
            # Never continue replying invisibly if the independent UI crashes.
            if not owner.is_paused():
                owner.toggle_pause()
            owner.root.deiconify()
            owner.set_banner("桌面窗口已关闭或未能启动，请点击「打开新版工作台」重试。详情见 logs/desktop.log。", "error")
    owner.root.after(1000, check_host)


class DesktopSession:
    def __init__(self, url):
        parts = urlsplit(url)
        if parts.scheme != "http" or parts.hostname != "127.0.0.1" or not parts.port or parts.username or parts.password:
            raise ValueError("桌面窗口只能连接本机工作区")
        self.token = parse_qs(parts.fragment).get("session", [""])[0]
        if not self.token:
            raise ValueError("本机会话已失效")
        self.url = url
        self.origin = f"http://127.0.0.1:{parts.port}"

    def request(self, path, payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Authorization": "Bearer " + self.token, "Origin": self.origin,
                   "Content-Type": "application/json"}
        with urlopen(Request(self.origin + path, data=data, headers=headers), timeout=2) as response:
            return json.load(response)

    def close_application(self):
        """Return a rejection message, or None once shutdown has been accepted."""
        identifier = str(uuid.uuid4())
        try:
            self.request("/api/command", {"action": "exit", "requestId": identifier})
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                result = self.request("/api/result?id=" + identifier)
                if result.get("status") == "done":
                    return None
                if result.get("status") == "error":
                    return result.get("message", "请稍后重试")
                time.sleep(.1)
            return "程序仍在处理操作，请稍后再关闭窗口。"
        except OSError:
            return None  # The coordinator has already stopped.


def run():
    from app_version import version_label
    import webview

    session = DesktopSession(json.loads(session_path().read_text(encoding="utf-8"))["url"])
    session.request("/api/identity")
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["ALLOW_FILE_URLS"] = False
    window = webview.create_window("企业微信智能客服 " + version_label(), session.url,
        width=1440, height=900, min_size=(1000, 660), background_color="#1e1f22",
        text_select=True)
    stopped = threading.Event()
    exiting = threading.Event()
    minimized = threading.Event()

    def style_titlebar():
        # Match our own app chrome to the dark workspace, without changing Windows settings.
        if sys.platform == "win32":
            import ctypes
            enabled = ctypes.c_int(1)
            hwnd = ctypes.c_void_p(window.native.Handle.ToInt64())
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(enabled), 4)

    def closing():
        if exiting.is_set():
            return True
        rejection = session.close_application()
        if rejection:
            window.evaluate_js("alert(" + json.dumps(rejection) + ")")
            return False
        exiting.set()
        return True

    def watch():
        last_focus = -1
        failures = 0
        while not stopped.wait(.4):
            try:
                state = session.request("/api/identity")
                failures = 0
                if not state.get("connected"):
                    exiting.set()
                    window.destroy()
                    return
                focus = state.get("desktopFocus", 0)
                if focus != last_focus:
                    if last_focus != -1:
                        if minimized.is_set():
                            window.restore()
                        window.show()
                    last_focus = focus
            except OSError:
                failures += 1
                if failures >= 4:
                    exiting.set()
                    window.destroy()
                    return
            except Exception:
                logging.exception("Desktop window monitor failed")
                return

    window.events.closing += closing
    window.events.closed += lambda: stopped.set()
    window.events.shown += style_titlebar
    window.events.minimized += lambda: minimized.set()
    window.events.restored += lambda: minimized.clear()
    window.events.maximized += lambda: minimized.clear()
    webview.start(watch, gui="edgechromium", debug=False, private_mode=True,
                  storage_path=str(app_dir() / "data" / "desktop-cache"),
                  icon=str(Path(__file__).resolve().parent.parent / "assets" / "app.ico"))
