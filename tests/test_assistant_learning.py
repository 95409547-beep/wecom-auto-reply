import json
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from qdrant_client import QdrantClient

from tests.test_web_services import services


@pytest.fixture
def library(services, monkeypatch):
    from pipeline import embedder
    from rag.retriever import ensure_collection
    model = Mock()
    model.encode.return_value = np.ones(512, dtype=np.float32) / np.sqrt(512)
    monkeypatch.setattr(embedder, "get_model", lambda: model)
    client = QdrantClient(":memory:")
    services.qdrant = client
    ensure_collection(client)
    yield services
    client.close()


def test_confirmed_reply_is_published_once_and_tracks_deleted_entry(library):
    from rag import archives, reply_learning
    from rag.kb_tools import count
    archive = archives.active_id()
    row = reply_learning.prepare(
        "天仙月礼包码在哪里兑换？", "天仙月打开设置，进入兑换 CDK。",
        archive=archive, cfg=library.cfg, direct=True,
    )
    assert count(library.qdrant) == 0
    assert reply_learning.status(archive, row["question"], row["answer"])["label"] == "待确认学习"
    payload = {"archive": archive, "id": row["id"], "keys": ["reply"]}
    receipt = library.command("reply.commit", payload)["review"]
    assert receipt["status"] == "learned" and len(receipt["entries"]) == 1
    library.command("reply.commit", payload)
    assert count(library.qdrant) == 1
    state = reply_learning.status(archive, row["question"], row["answer"], library.qdrant)
    assert state["label"] == "已加入资料库"
    library.qdrant.delete(collection_name="knowledge_base", points_selector=receipt["entries"])
    assert "变更或删除" in reply_learning.status(
        archive, row["question"], row["answer"], library.qdrant,
    )["label"]


def test_disabled_learning_and_archive_switch_never_publish_to_another_library(library):
    from rag import archives, reply_learning
    archive = archives.active_id()
    row = reply_learning.prepare("问题", "人工确认的回答",
                                archive=archive, cfg={"kb": {"learn": {"enabled": False}}}, direct=True)
    assert row["status"] == "disabled"
    other = archives.create("第二款游戏")
    archives.set_active(other["id"])
    with pytest.raises(ValueError, match="档案已切换"):
        library.command("reply.commit", {"archive": archive, "id": row["id"], "keys": ["reply"]})
    assert not reply_learning.reviews(other["id"])


def test_assistant_preview_requires_application_and_rejects_stale_prompt(services):
    prompts = services.read("prompts", {})
    welcome = next(p for p in prompts["prompts"] if p["key"] == "welcome")
    request = {"action": "prompt.save", "arguments": {
        "key": "welcome", "revision": welcome["revision"], "text": "在的，您说。",
    }}
    plan = services.assistant.tool("propose_change", request)["change"]
    assert services.read("prompts", {})["prompts"] == prompts["prompts"]
    services.assistant.apply(plan["id"])
    saved = next(p for p in services.read("prompts", {})["prompts"] if p["key"] == "welcome")
    assert saved["text"] == "在的，您说。"
    services.assistant.apply(plan["id"])
    request["arguments"]["revision"] = saved["revision"]
    request["arguments"]["text"] = "您好，请讲。"
    stale = services.assistant.tool("propose_change", request)["change"]
    services.command("prompt.save", {"archive": prompts["archive"], "key": "welcome",
                                   "revision": saved["revision"], "text": "在呢。"})
    with pytest.raises(ValueError, match="其他窗口"):
        services.assistant.apply(stale["id"])


def test_assistant_tools_redact_keys_and_preserve_approved_settings(services):
    read = services.assistant.tool("inspect", {"resource": "settings"})
    assert "local-test-key" not in json.dumps(read)
    with pytest.raises(ValueError, match="密钥与接口地址"):
        services.assistant.tool("propose_change", {
            "action": "settings.save", "arguments": {"values": {"llm_api_key": "new-key"}},
        })
    plan = services.assistant.tool("propose_change", {
        "action": "settings.save", "arguments": {"values": {"llm_model": "new-model"}},
    })["change"]
    services.assistant.apply(plan["id"])
    from config import settings_store
    assert settings_store.read_current_settings()["llm_api_key"] == "local-test-key"
    assert settings_store.read_current_settings()["llm_model"] == "new-model"


def test_tool_calls_from_chat_finish_without_locking_the_page_worker(services, monkeypatch):
    from rag import llm_client
    call = SimpleNamespace(id="inspect-call", function=SimpleNamespace(
        name="inspect", arguments=json.dumps({"resource": "settings"}),
    ))
    first = Mock(content=None, tool_calls=[call])
    first.model_dump.return_value = {"role": "assistant", "tool_calls": [
        {"id": "inspect-call", "type": "function", "function": {
            "name": "inspect", "arguments": call.function.arguments,
        }},
    ]}
    second = Mock(content="当前模型为 test-model。", tool_calls=[])
    second.model_dump.return_value = {"role": "assistant", "content": second.content}
    replies = iter((first, second))

    async def create(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=next(replies))])

    monkeypatch.setattr(llm_client, "get_client", lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    ))
    result = services.command("assistant.chat", {"text": "当前使用什么模型？"})
    assert result["reply"] == second.content
    assert not result["changes"]


def test_game_switch_overrides_history_and_ambiguous_question_asks_for_game():
    from rag.game_scope import scope_chunks
    x = "客户问题: 礼包在哪兑\n销售回答: 设置\n适用项目：天仙月。"
    y = "客户问题: 礼包在哪兑\n销售回答: 奖励\n适用项目：仙语奇缘魔改版。"
    history = [{"role": "customer", "text": "我玩天仙月"}]
    assert scope_chunks("仙语奇缘魔改版呢", [x, y], history) == ([y], False)
    assert scope_chunks("在哪兑", [x, y], history) == ([x], False)
    assert scope_chunks("在哪兑", [x, y]) == ([], True)
    assert scope_chunks("这个怎么操作", ["普通业务资料"]) == (["普通业务资料"], False)


def test_learning_tone_does_not_claim_knowledge_publication(library, monkeypatch):
    from rag import archives, learn, reply_learning
    from rag.kb_tools import count
    monkeypatch.setattr(learn, "propose", lambda *args, **kwargs: {
        "ok": True, "rules": [], "tone": {"key": "t", "text": "在的，你说～"},
        "facts": [], "customer_question": "在吗", "human": "在的，你说～", "draft": "您好",
    })
    archive = archives.active_id()
    row = reply_learning.prepare("在吗", "在的，你说～", "您好",
                                 archive=archive, cfg=library.cfg)
    reply_learning.commit(archive, row["id"], ["t"], library.cfg, library.qdrant)
    assert count(library.qdrant) == 0
    assert reply_learning.status(archive, row["question"], row["answer"], library.qdrant)["label"] == "已学习语气，问答未入库"
    saved = reply_learning.commit(archive, row["id"], ["t", "reply"], library.cfg, library.qdrant)
    assert count(library.qdrant) == 1
    assert saved["result"]["tones"] == 1 and saved["result"]["facts"] == 1
    assert set(saved["selected"]) == {"t", "reply"}


def test_failed_publication_stays_reviewable(library, monkeypatch):
    from rag import archives, kb_tools, reply_learning
    monkeypatch.setattr(kb_tools, "add_entry", Mock(side_effect=RuntimeError("模拟索引失败")))
    archive = archives.active_id()
    row = reply_learning.prepare("天仙月礼包码在哪兑换", "在设置里的兑换 CDK。",
                                 archive=archive, cfg=library.cfg, direct=True)
    saved = reply_learning.commit(archive, row["id"], ["reply"], library.cfg, library.qdrant)
    assert saved["status"] == "ready" and saved["result"]["fact_errors"]
    assert saved["entries"] == []


def test_assistant_undo_restores_prompt_without_overwriting_later_edits(services):
    welcome = next(p for p in services.read("prompts", {})["prompts"] if p["key"] == "welcome")
    plan = services.assistant.tool("propose_change", {"action": "prompt.save", "arguments": {
        "key": "welcome", "text": "在的哈", "revision": welcome["revision"],
    }})["change"]
    services.assistant.apply(plan["id"])
    services.assistant.undo(plan["id"])
    assert next(p for p in services.read("prompts", {})["prompts"] if p["key"] == "welcome")["text"] == welcome["text"]


def test_undo_duplicate_add_cannot_delete_existing_knowledge(library):
    from rag import kb_tools
    before = kb_tools.add_entry(library.qdrant, "天仙月礼包码在哪兑", "设置里兑换", source="原始资料")
    plan = library.assistant.tool("propose_change", {"action": "kb.add", "arguments": {
        "question": "天仙月礼包码在哪兑", "answer": "设置里兑换",
    }})["change"]
    result = library.assistant.apply(plan["id"])
    assert result["undoable"] is False
    with pytest.raises(ValueError, match="沿用已有"):
        library.assistant.undo(plan["id"])
    assert kb_tools.get_entry(library.qdrant, before["id"])["source"] == "原始资料"
