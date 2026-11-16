from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from gui.desktop_host import DesktopSession, open_desktop_window


@pytest.mark.parametrize("url", ["https://example.com/#session=x", "http://localhost:80/#session=x", "http://127.0.0.1:80/", "file:///tmp/app.html"])
def test_only_authenticated_loopback_session_is_allowed(url):
    with pytest.raises(ValueError):
        DesktopSession(url)


def test_busy_backend_keeps_window_open(monkeypatch):
    session=DesktopSession("http://127.0.0.1:1234/#session=test")
    call=Mock(side_effect=[{}, {"status":"error", "message":"资料操作仍在进行"}])
    monkeypatch.setattr(session,"request",call)
    assert session.close_application()=="资料操作仍在进行"
    assert call.call_args_list[0].args[1]["action"]=="exit"


def test_accepted_shutdown_allows_window_close(monkeypatch):
    session=DesktopSession("http://127.0.0.1:1234/#session=test")
    monkeypatch.setattr(session,"request",Mock(side_effect=[{}, {"status":"done"}]))
    assert session.close_application() is None


def test_repeated_launch_focuses_existing_host_without_spawning(monkeypatch):
    owner=SimpleNamespace(_desktop_focus=2,_desktop_process=Mock())
    owner._desktop_process.poll.return_value=None
    spawn=Mock()
    monkeypatch.setattr("gui.desktop_host.subprocess.Popen",spawn)
    open_desktop_window(owner)
    assert owner._desktop_focus==3
    spawn.assert_not_called()
