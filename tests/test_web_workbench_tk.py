"""Real MainWindow smoke test with isolated data and a fake delivery callback."""
import json
from types import SimpleNamespace
from urllib.request import Request, urlopen

import pytest


@pytest.mark.parametrize("web_mode", [False, True])
def test_native_entry_shares_queue_and_dispatches_on_tk_thread(monkeypatch, tmp_path, web_mode):
    import tkinter as tk
    import threading
    from gui import main_window
    from gui.web_workbench import open_workbench

    monkeypatch.setattr(main_window, "load_reply_history", lambda: [])
    monkeypatch.setattr(main_window, "always_on_top_enabled", lambda: False)
    monkeypatch.setenv("WECOM_AUTOSTART", "0")
    monkeypatch.setattr("app_session.session_path", lambda: tmp_path / "session.json")
    opened = []
    monkeypatch.setattr("gui.desktop_host.open_desktop_window", lambda w: opened.append(w._web_workbench.url))
    try:
        window = main_window.MainWindow(web_mode=web_mode)
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable: {error}")
    server = None
    try:
        if web_mode:
            window.root.update_idletasks()
            assert window.root.state() == "withdrawn"
        window.root.withdraw()
        entry = SimpleNamespace(key="test::two", customer_name="测试客户", customer_message="第二条问题",
            ai_reply="完整草稿", timestamp=1780000000, confidence=.56, guard_decision="low_risk",
            send_status="pending", send_error="")
        window.refresh_pending_queue([entry])
        calls = []
        def on_edit(key, text):
            calls.append((key, text, threading.get_ident()))
            entry.ai_reply = text
            entry.send_status = "queued"
            window.refresh_pending_queue([entry])
        window.set_pending_callbacks(on_edit=on_edit)
        open_workbench(window)
        server = window._web_workbench
        assert opened == [server.url]
        if web_mode:
            assert window.root.state() == "withdrawn"
            assert json.loads((tmp_path / "session.json").read_text())["url"] == server.url
        headers = {"Authorization": "Bearer " + server.token, "Origin": server.origin}
        with urlopen(Request(server.origin + "/api/state", headers=headers)) as response:
            row = json.load(response)["items"][0]
        payload = {"action": "edit", "key": row["key"], "revision": row["revision"],
                   "text": "手动编辑的全文", "requestId": "tk-test-001"}
        with urlopen(Request(server.origin + "/api/command", json.dumps(payload).encode(), headers)) as response:
            assert response.status == 202
        assert calls == []
        # Execute the same main-thread pump registered by root.after.
        server.tick()
        assert calls == [("test::two", "手动编辑的全文", threading.get_ident())]
        assert server.state["items"][0]["send_status"] == "queued"
        assert server.operations["tk-test-001"]["status"] == "done"
    finally:
        window.root.destroy()
        if server:
            assert server.closed
        assert not (tmp_path / "session.json").exists()
