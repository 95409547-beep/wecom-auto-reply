import json

import httpx
import pytest

from pipeline.upload import parse_records
from rag.ima_kb import ImaKnowledge


def test_current_api_library_identifiers_and_names_are_selectable():
    from rag.ima_kb import knowledge_base_id
    def service(request):
        assert request.url.path.endswith("/search_knowledge_base")
        return httpx.Response(200, json={"code": 0, "data": {
            "info_list": [{"kb_id": "ima_kb_ab12CD34", "kb_name": "游戏客服",
                           "member_count": "2", "role_type": "查看者"}],
            "is_end": True,
        }})
    with httpx.Client(transport=httpx.MockTransport(service)) as http:
        bases = ImaKnowledge(http, "test-client", "test-key").bases()
    assert knowledge_base_id(bases[0]["id"]) == "ima_kb_ab12CD34"
    assert bases[0]["name"] == "游戏客服" and bases[0]["members"] == "2"


def test_ima_faq_download_is_indexed_by_question_and_keeps_credentials_at_ima(tmp_path):
    document = "天仙月｜客服知识库\n\n问：怎么用礼包码？\n答：设置里打开 CDK 兑换。\n"
    calls = []

    def service(request):
        calls.append(request)
        return (
            httpx.Response(200, content=document.encode())
            if request.method == "GET"
            else httpx.Response(200, json={"code": 0, "data": {"url_info": {
                "url": "https://fixture.cos.ap-guangzhou.myqcloud.com/file.txt",
                "headers": {"Authorization": "Bearer file-token", "ima-openapi-apikey": "discard-me"},
            }}})
        )

    with httpx.Client(transport=httpx.MockTransport(service)) as http:
        ima = ImaKnowledge(http, "client-id", "wiki-key")
        files = ima.faq_entries([{"title": "天仙月 客服问答", "media_id": "345"}])
        result, = ima.read_faqs(files)
    assert json.loads(calls[0].content) == {"media_id": "345"}
    assert calls[0].headers["ima-openapi-apikey"] == "wiki-key"
    assert calls[1].headers["Authorization"] == "Bearer file-token"
    assert "ima-openapi-apikey" not in calls[1].headers
    exported = tmp_path / result.name
    exported.write_bytes(result.content)
    assert result.count == 1
    assert parse_records(exported)[1] == [
        "客户问题: 怎么用礼包码？\n销售回答: 设置里打开 CDK 兑换。\n适用项目：天仙月。"
    ]


def test_ima_rejects_non_tencent_download_links():
    def service(request):
        assert request.url.host == "ima.qq.com"
        return httpx.Response(200, json={"code": 0, "data": {
            "url_info": {"url": "https://example.org/external.txt", "headers": {}},
        }})

    with httpx.Client(transport=httpx.MockTransport(service)) as http:
        with pytest.raises(ValueError, match="官方文件链接"):
            ImaKnowledge(http, "client-id", "wiki-key").read_faqs({"天仙月 客服问答.txt": "345"})
