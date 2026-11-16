"""The UI bridge must preserve message identity, delivery guards and Tk threading."""
import json
import threading
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import Mock

import pytest

from gui.web_workbench import WindowAdapter, WorkbenchServer, serialize_pending


def item(key="person::one", **extra):
    return SimpleNamespace(**dict(dict(key=key, customer_name="同一个客户", customer_message="第一条问题",
        ai_reply="第一条草稿", timestamp=1780000000, confidence=.5, guard_decision="low_risk",
        send_status="pending", send_error=""), **extra))


def window(*items):
    w = SimpleNamespace(_web_pending_rows=serialize_pending(items), _should_exit=False,
        is_paused=lambda: True, _on_pending_send=Mock(), _on_pending_edit=Mock(),
        _on_pending_ignore=Mock(), root=Mock())
    def sent(key, *_):
        row = next(r for r in w._web_pending_rows if r["key"] == key)
        row["send_status"] = "queued"
    w._on_pending_send.side_effect = sent
    w._on_pending_edit.side_effect = sent
    return w


def command(row, action="send", **kwargs):
    return dict(action=action, key=row["key"], revision=row["revision"], **kwargs)


def test_same_customer_messages_dispatch_by_key_not_name():
    w = window(item(), item("person::two", customer_message="第二条问题", ai_reply="第二条草稿"))
    WindowAdapter(w).dispatch(command(w._web_pending_rows[1]))
    w._on_pending_send.assert_called_once_with("person::two")


def test_edited_reply_uses_existing_edit_callback():
    w = window(item())
    WindowAdapter(w).dispatch(command(w._web_pending_rows[0], "edit", text=" 修改后的完整回复 "))
    w._on_pending_edit.assert_called_once_with("person::one", "修改后的完整回复")
    w._on_pending_send.assert_not_called()


@pytest.mark.parametrize("text", [None, "", " \n ", "字" * 10001], ids=["null", "empty", "blank", "too-long"])
def test_empty_or_invalid_edits_do_not_dispatch(text):
    w = window(item())
    with pytest.raises(ValueError):
        WindowAdapter(w).dispatch(command(w._web_pending_rows[0], "edit", text=text))
    w._on_pending_edit.assert_not_called()


def test_refreshed_draft_invalidates_old_snapshot():
    original = item()
    w = window(original)
    old = command(w._web_pending_rows[0])
    original.ai_reply = "新草稿"
    w._web_pending_rows = serialize_pending([original])
    with pytest.raises(ValueError, match="已更新"):
        WindowAdapter(w).dispatch(old)
    w._on_pending_send.assert_not_called()


def test_queued_item_cannot_be_sent_again_but_retains_original_ignore_action():
    w = window(item(send_status="queued"))
    for action in ("send", "edit"):
        with pytest.raises(ValueError, match="发送队列"):
            WindowAdapter(w).dispatch(command(w._web_pending_rows[0], action))
    w._on_pending_send.assert_not_called()
    WindowAdapter(w).dispatch(command(w._web_pending_rows[0], "ignore"))
    w._on_pending_ignore.assert_called_once_with("person::one")


def test_unknown_result_uses_existing_confirmation_path():
    w = window(item(send_status="unknown"))
    WindowAdapter(w).dispatch(command(w._web_pending_rows[0]))
    w.root.lift.assert_called_once()
    w._on_pending_send.assert_called_once()


def test_blocked_callback_is_not_reported_as_sent():
    w = window(item())
    w._on_pending_send.side_effect = None
    w._web_banner = {"text": "没有有效草稿"}
    with pytest.raises(ValueError, match="没有有效草稿"):
        WindowAdapter(w).dispatch(command(w._web_pending_rows[0]))


def test_model_setup_warning_clears_when_saved_configuration_allows_start():
    w = window()
    w._start_guard_banner = True
    w._start_allowed = Mock(return_value=(False, "缺少模型接口"))
    w._web_banner = {"text": "还没配模型接口", "level": "error"}

    def clear_banner(text):
        w._start_guard_banner = False
        w._web_banner = {"text": text, "level": "info"}

    w.set_banner = Mock(side_effect=clear_banner)
    adapter = WindowAdapter(w)
    assert adapter.snapshot()["banner"]["text"] == "还没配模型接口"
    w.set_banner.assert_not_called()

    w._start_allowed.return_value = (True, "")
    updated = adapter.snapshot()
    assert updated["banner"]["text"] == ""
    assert updated["paused"] is True

    w._web_banner = {"text": "企业微信窗口未找到", "level": "warn"}
    assert adapter.snapshot()["banner"]["text"] == "企业微信窗口未找到"
    w.set_banner.assert_called_once_with("")


def test_removed_item_cannot_fall_back_to_customer_lookup():
    w = window(item())
    old = command(w._web_pending_rows[0])
    w._web_pending_rows = []
    with pytest.raises(ValueError, match="已被处理"):
        WindowAdapter(w).dispatch(old)
    w._on_pending_send.assert_not_called()


@pytest.fixture
def server(tmp_path):
    (tmp_path / "index.html").write_text("<title>test</title>")
    calls = []
    server = WorkbenchServer(lambda: {"items": [], "connected": True},
        lambda payload: calls.append((threading.get_ident(), payload)) or "queued", assets=tmp_path)
    yield server, calls
    server.close()


def request(server, path="/api/state", payload=None, **headers):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"Authorization": "Bearer " + server.token, "Origin": server.origin, **headers}
    with urlopen(Request(server.origin + path, data=data, headers=headers), timeout=3) as response:
        return json.load(response)


def test_api_requires_token_and_same_origin(server):
    bridge, _ = server
    assert request(bridge)["items"] == []
    for headers in ({"Authorization": ""}, {"Origin": "https://other.example"}, {"Host": "other.example"}):
        with pytest.raises(HTTPError) as error:
            request(bridge, **headers)
        assert error.value.code == 403


def test_commands_wait_for_main_thread_and_retry_is_deduplicated(server):
    bridge, calls = server
    payload = {"action": "send", "key": "one", "requestId": "request-123"}
    for _ in range(2):
        request(bridge, "/api/command", payload)
    assert calls == []
    bridge.tick()
    assert len(calls) == 1
    assert calls[0][0] == threading.get_ident()
    assert request(bridge)["operations"]["request-123"]["status"] == "done"
    request(bridge, "/api/command", payload)
    bridge.tick()
    assert len(calls) == 1


def test_static_paths_cannot_escape_asset_directory(server):
    bridge, _ = server
    with pytest.raises(HTTPError) as error:
        request(bridge, "/%2e%2e/gui/web_workbench.py")
    assert error.value.code == 404


def test_invalid_command_does_not_break_server(server):
    bridge, calls = server
    with pytest.raises(HTTPError) as error:
        request(bridge, "/api/command", {"action": "send", "requestId": []})
    assert error.value.code == 400
    assert request(bridge)["connected"]
    assert calls == []
