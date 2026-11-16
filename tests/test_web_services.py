"""New UI must use the existing stores, protect drafts and keep secrets local."""
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from gui.web_services import WebServices, revision
from gui.web_workbench import WorkbenchServer
from tests.test_web_workbench import request


@pytest.fixture
def services(tmp_path, monkeypatch):
    from rag import archives, prompt_store, learn_store
    from pipeline import upload
    from config import settings_store
    from stats import aggregate
    for mod, attr in [(archives, "HERE"), (upload, "HERE"), (aggregate, "ROOT")]:
        monkeypatch.setattr(mod, attr, tmp_path)
    monkeypatch.setattr(prompt_store, "PROMPTS_DIR", None)
    monkeypatch.setattr(learn_store, "LEARN_DIR", None)
    monkeypatch.setattr(upload, "UPLOAD_DIR", None)
    monkeypatch.setattr(settings_store, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(settings_store, "CONFIG_PATH", tmp_path / "config.json")
    (tmp_path / "config.json").write_text(json.dumps({"channel": "screenshot", "profile": "wecom"}))
    (tmp_path / ".env").write_text("LLM_API_KEY=local-test-key\nLLM_BASE_URL=https://example.com/v1\nLLM_MODEL=test-model\nWECOM_KF_SECRET=local-kf-secret\n")
    archives.reset_cache()
    service = WebServices({"kb": {"learn": {"enabled": True}}}, Mock())
    yield service
    archives.reset_cache()


def test_read_resources_are_json_and_do_not_expose_keys(services):
    for name in ("settings", "dashboard", "prompts", "learned", "probe"):
        body = json.dumps(services.read(name, {}))
        assert "local-test-key" not in body and "local-kf-secret" not in body
    saved = services.read("settings", {})
    assert saved["savedSecrets"] == {"llm_api_key": True, "wecom_kf_secret": True}


def test_blank_key_preserves_current_key_but_never_sends_it_to_new_provider(services):
    p = {"values": services.read("settings", {})["values"]}
    assert services._settings_values(p)["llm_api_key"] == "local-test-key"
    p["values"]["llm_base_url"] = "https://different.example/v1"
    assert services._settings_values(p)["llm_api_key"] == ""
    assert services._settings_values(p)["wecom_kf_secret"] == "local-kf-secret"


def test_explicit_secret_clear_and_settings_save_stay_redacted(services, monkeypatch):
    from config import settings_store as store
    from rag import llm_client
    import dotenv
    monkeypatch.setattr(llm_client, "reset_client", Mock())
    monkeypatch.setattr(dotenv, "load_dotenv", Mock())
    p = {"values": services.read("settings", {})["values"], "clearSecrets": {"llm_api_key": True}, "allowEmptyKey": True}
    out = services.command("settings.save", p)
    assert store.read_current_settings()["llm_api_key"] == ""
    assert "local-kf-secret" not in json.dumps(out)
    assert not out["software_changed"]


def test_prompt_save_validates_placeholder_and_revision(services):
    data = services.read("prompts", {})
    system = next(p for p in data["prompts"] if p["key"] == "system")
    p = dict(archive=data["archive"],key="system",revision=system["revision"],text="missing placeholder")
    with pytest.raises(ValueError): services.command("prompt.save", p)
    p["text"] = "已核对资料：{context}"
    services.command("prompt.save", p)
    with pytest.raises(ValueError, match="其他窗口修改"): services.command("prompt.save", p)


def test_archive_switch_rejects_stale_editor(services):
    from rag import archives
    original = archives.active_id()
    services.command("archive.create", {"archive": original, "name": "测试资料"})
    other = next(a for a in archives.all_archives() if a["id"] != original)
    services.command("archive.switch", {"archive": original, "id": other["id"]})
    with pytest.raises(ValueError, match="已切换"):
        services.command("kb.add", {"archive": original,"question":"q","answer":"a"})
    services.qdrant.upsert.assert_not_called()


def test_knowledge_revision_comes_from_full_stored_text(services):
    services.qdrant.count.return_value = SimpleNamespace(count=1)
    services.qdrant.scroll.return_value = ([SimpleNamespace(id="one", payload={"text":"客户问题：q\n销售回答：a","source":"FAQ.md"})],None)
    data = services.read("knowledge", {})
    json.dumps(data)
    assert data["rows"][0]["revision"] == revision(data["rows"][0]["text"])
    assert data["page"] == 0 and data["total"] == 1


def test_stale_kb_revision_prevents_mutation(services):
    services.qdrant.retrieve.return_value = [SimpleNamespace(id="one",payload={"text":"new content","source":"FAQ.md"})]
    with pytest.raises(ValueError, match="已变更"):
        services.command("kb.delete", {"archive":"photo","id":"one","revision":revision("old content")})
    services.qdrant.delete.assert_not_called()


def test_model_test_uses_unsaved_fields_without_writing_config(services, monkeypatch, tmp_path):
    from rag import llm_client
    calls = []
    async def ping(**kwargs): calls.append(kwargs); return True,"ok"
    monkeypatch.setattr(llm_client,"ping",ping)
    before = (tmp_path/".env").read_bytes()
    values = services.read("settings",{})["values"]
    values["llm_model"]="another-model"
    services.command("settings.test",{"values":values})
    assert calls[0]["settings"] == ("local-test-key","https://example.com/v1","another-model")
    assert (tmp_path/".env").read_bytes() == before


def test_ingest_plan_requires_review_before_writing(services, monkeypatch):
    import base64
    from rag import llm_ingest
    from pipeline import embedder
    store = Mock(return_value=1)
    monkeypatch.setattr(embedder,"embed_and_store",store)
    async def build(chunks): return [dict(chunk=chunks[0],question="Q",answer="A",ok=True,problems=[])]
    monkeypatch.setattr(llm_ingest,"build_entries",build)
    plan = services.command("ingest.plan",{"archive":"photo","files":[{"name":"facts.txt","data":base64.b64encode("业务资料".encode()).decode()}]})
    p = {"archive":"photo","planId":plan["planId"]}
    result = services.command("ingest.run",p)
    store.assert_not_called()
    row = {**result["entries"][0],"index":0,"answer":"用户核对后的答案"}
    services.command("ingest.commit",{**p,"entries":[row]})
    assert "用户核对后的答案" in store.call_args.args[0][0]
    with pytest.raises(ValueError,match="已失效"): services.command("ingest.commit",{**p,"entries":[row]})
    assert store.call_count == 1


def test_page_work_runs_in_worker_and_full_results_are_separately_authorized(tmp_path):
    calls=[]
    finished=threading.Event()
    def dispatch(p):
        calls.append(threading.get_ident());finished.set()
        return {"message":"saved","entries":[{"answer":"reviewed"}]}
    server=WorkbenchServer(lambda:{"items":[]},dispatch,assets=tmp_path,resources=lambda n,p:{"name":n})
    try:
        assert request(server,"/api/resource?name=prompts")=={"name":"prompts"}
        request(server,"/api/command",{"action":"page.ingest.run","requestId":"test-page-command"})
        server.tick();assert finished.wait(3)
        server.worker.shutdown(wait=True)
        assert calls == [server.worker._threads.copy().pop().ident]
        assert calls[0] != threading.get_ident()
        assert "result" not in request(server)["operations"]["test-page-command"]
        assert request(server,"/api/result?id=test-page-command")["result"]["entries"][0]["answer"]=="reviewed"
        from urllib.error import HTTPError
        for path in ("/api/resource?name=settings","/api/result?id=test-page-command"):
            with pytest.raises(HTTPError) as error: request(server,path,Authorization="")
            assert error.value.code==403
    finally: server.close()


def test_runtime_paths_follow_exe_not_temporary_extraction(monkeypatch,tmp_path):
    import sys
    from app_paths import app_dir
    monkeypatch.setattr(sys,"frozen",True,raising=False)
    monkeypatch.setattr(sys,"executable",str(tmp_path/"启动.exe"))
    assert app_dir()==tmp_path


def test_unanswered_management_preserves_original_statistics(services,monkeypatch,tmp_path):
    from rag import unanswered
    monkeypatch.setattr(unanswered,"PATH",tmp_path/"unanswered.json")
    unanswered.record("未覆盖的问题","retrieval_low_confidence")
    data=services.read("unanswered",{})
    assert data["total"]==1 and data["todo"]==1
    services.command("unanswered.done",{"archive":"photo","question":"未覆盖的问题"})
    assert services.read("unanswered",{})["todo"]==0
    services.command("unanswered.clear",{"archive":"photo"})
    assert services.read("unanswered",{})["rows"]==[]
