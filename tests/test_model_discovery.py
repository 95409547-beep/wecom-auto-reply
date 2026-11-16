import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from gui.settings_dialog import SettingsDialog
from rag import llm_client


def simulate_provider(monkeypatch, handler):
    openai = llm_client.AsyncOpenAI

    def client(**options):
        transport = httpx.MockTransport(handler)
        return openai(**options, http_client=httpx.AsyncClient(transport=transport))

    monkeypatch.setattr(llm_client, "AsyncOpenAI", client)


def test_fetch_uses_draft_key_and_provider_url_without_a_chat_request(monkeypatch):
    def handler(request):
        assert request.method == "GET"
        assert str(request.url) == "https://provider.invalid/compatible/v1/models"
        assert request.headers["Authorization"] == "Bearer draft-key"
        return httpx.Response(200, json={"object": "list", "data": [
            {"id": "provider/beta"}, {"id": "provider/alpha"}, {"id": "provider/beta"}, {"id": ""},
        ]})

    simulate_provider(monkeypatch, handler)
    assert asyncio.run(llm_client.list_models(
        "https://provider.invalid/compatible/v1", "draft-key")) == ["provider/alpha", "provider/beta"]


@pytest.mark.parametrize("status, body, expected", [
    (401, {"error": "draft-key reflected by provider"}, "密钥无效"),
    (404, {"error": "not found"}, "/models"),
    (200, {"object": "list", "data": []}, "没有返回可选模型"),
])
def test_fetch_reports_safe_actionable_errors(monkeypatch, status, body, expected):
    simulate_provider(monkeypatch, lambda _request: httpx.Response(status, json=body))
    with pytest.raises(RuntimeError, match=expected) as error:
        asyncio.run(llm_client.list_models("https://provider.invalid/v1", "draft-key"))
    assert "draft-key" not in str(error.value)


def test_dialog_replaces_stale_model_and_discards_results_for_old_credentials(monkeypatch):
    credentials = {"llm_base_url": "https://first.invalid/v1", "llm_api_key": "draft-key"}
    model = Mock()
    model.get.return_value = "old-model"
    results = []
    dialog = SimpleNamespace(
        _get=credentials.__getitem__, _entries={"llm_model": model},
        _model_status=Mock(), _sync_model_actions=Mock(),
        _run_llm_action=lambda fn, _progress, on_result: results.append((fn, on_result)),
    )

    async def list_models(address, api_key):
        assert (address, api_key) == ("https://first.invalid/v1", "draft-key")
        return ["model-a", "model-b"]

    monkeypatch.setattr(llm_client, "list_models", list_models)
    SettingsDialog._fetch_models(dialog)
    request, apply = results.pop()
    apply(*asyncio.run(request()))
    model.configure.assert_called_once_with(values=["model-a", "model-b"])
    model.set.assert_called_once_with("")

    model.reset_mock()
    SettingsDialog._fetch_models(dialog)
    request, apply = results.pop()
    credentials["llm_api_key"] = "new-key"
    apply(*asyncio.run(request()))
    model.configure.assert_not_called()
