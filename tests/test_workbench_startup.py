import json
import subprocess
import sys
from unittest.mock import Mock

import app_session
from gui.web_workbench import WorkbenchServer, WindowAdapter


def test_relaunch_reopens_authenticated_instance(monkeypatch,tmp_path):
    monkeypatch.setattr(app_session,"session_path",lambda:tmp_path/"session.json")
    opened=Mock(return_value=True)
    monkeypatch.setattr("webbrowser.open",opened)
    commands=[]
    server=WorkbenchServer(lambda:{"connected":True,"items":[]},commands.append,assets=tmp_path)
    try:
        app_session.save_session(server.url)
        assert app_session.reopen_running()
        opened.assert_not_called()
        server.tick()
        assert len(commands)==1 and commands[0]["action"]=="focus"
        app_session.clear_session("different-session")
        assert app_session.session_path().exists()
        app_session.clear_session(server.url)
        assert not app_session.session_path().exists()
    finally: server.close()


def test_stale_or_nonlocal_session_never_opens(monkeypatch,tmp_path):
    monkeypatch.setattr(app_session,"session_path",lambda:tmp_path/"session.json")
    opened=Mock()
    monkeypatch.setattr("webbrowser.open",opened)
    for url in ("https://example.com/#session=private", "http://127.0.0.1:1/#session=expired"):
        app_session.save_session(url)
        assert not app_session.reopen_running()
    opened.assert_not_called()


def test_service_does_not_reveal_legacy_window_or_bypass_start_guard():
    from types import SimpleNamespace
    import pytest
    root=Mock()
    w=SimpleNamespace(root=root,_should_exit=False,is_paused=lambda:True,
                      _start_allowed=lambda:(False,"missing key"),toggle_pause=Mock())
    with pytest.raises(ValueError,match="设置"):
        WindowAdapter(w).dispatch({"action":"service"})
    w.toggle_pause.assert_not_called()
    root.deiconify.assert_not_called()


def test_importing_app_does_not_load_embedding_runtime():
    result=subprocess.run([sys.executable,"-c","import main,sys; assert 'sentence_transformers' not in sys.modules; assert 'torch' not in sys.modules"],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
