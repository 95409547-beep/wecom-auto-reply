"""Read reviewed game FAQ files through Tencent ima's official OpenAPI."""

from dataclasses import dataclass
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit

import httpx

from pipeline.game_faq import FILE_SUFFIX, TITLE_SUFFIX, parse_game_faq

_ORIGIN = "https://ima.qq.com"
_MAX_FILE_BYTES = 2 * 1024 * 1024
_REPLY_RULE = (
    "\n\n客服正文通常写 1–2 句，只回答当前游戏和当前问题。"
    "保留会影响操作的版本、渠道、区服等条件。换说法时保留原来的步骤和数字。"
    "游戏不明且对话没有线索时，只问玩家是哪款游戏；其他资料不足时按人工处理规则执行。\n"
)


@dataclass(frozen=True)
class FaqDocument:
    name: str
    content: bytes
    count: int


def knowledge_base_id(value: str) -> str:
    value = value.strip()
    if value.startswith(_ORIGIN + "/"):
        value = parse_qs(urlsplit(value).query).get("knowledgeBaseId", [""])[0]
    if not re.fullmatch(r"[0-9]{1,24}", value):
        raise ValueError("请输入 ima 知识库页面链接或库 ID。")
    return value


def credentials(client_id: str = "", api_key: str = "") -> tuple[str, str]:
    directory = Path.home() / ".config" / "ima"

    def read(explicit, env_name, filename):
        value = explicit.strip() or os.environ.get(env_name, "").strip()
        if value:
            return value
        try:
            return (directory / filename).read_text(encoding="utf-8-sig").strip()
        except FileNotFoundError:
            return ""

    client_id = read(client_id, "IMA_OPENAPI_CLIENTID", "client_id")
    api_key = read(api_key, "IMA_OPENAPI_APIKEY", "api_key")
    if not client_id or not api_key:
        raise ValueError("请填写 ima 的 Client ID 和 API Key。模型 API Key 用于生成回复。")
    if any(not value.isascii() or any(c.isspace() for c in value) for value in (client_id, api_key)):
        raise ValueError("ima 凭证格式不正确，请重新复制。")
    return client_id, api_key


class ImaKnowledge:
    def __init__(self, http: httpx.Client, client_id: str, api_key: str):
        self.http = http
        self.headers = {"ima-openapi-clientid": client_id, "ima-openapi-apikey": api_key}

    def _request(self, endpoint: str, **body) -> dict:
        try:
            response = self.http.post(f"{_ORIGIN}/openapi/wiki/v1/{endpoint}",
                                      json=body, headers=self.headers, follow_redirects=False)
            response.raise_for_status()
            result = response.json()
        except httpx.HTTPStatusError as exc:
            raise ValueError(f"ima 接口返回 HTTP {exc.response.status_code}，请检查凭证和访问权限。") from None
        except (httpx.HTTPError, ValueError):
            raise ValueError("无法连接 ima 接口，或返回内容格式有误。") from None
        if not isinstance(result, dict):
            raise ValueError("ima 返回的数据格式有误。")
        if result.get("code") != 0:
            message = str(result.get("msg") or "请求失败")[:200]
            for credential in self.headers.values():
                message = message.replace(credential, "〔已隐藏〕")
            raise ValueError(f"ima 接口拒绝请求：{message}")
        if not isinstance(result.get("data"), dict):
            raise ValueError("ima 返回的数据格式有误。")
        return result["data"]

    def inventory(self, wiki_id: str) -> tuple[str, list[dict]]:
        data = self._request("get_knowledge_base", ids=[wiki_id])
        infos = data.get("infos") or {}
        if not isinstance(infos, dict):
            raise ValueError("ima 返回的知识库信息格式有误。")
        info = infos.get(wiki_id) or {}
        title = str(info.get("name") or "").strip()
        if not title:
            raise ValueError("当前 ima 账号无法读取这个知识库，请检查库链接和成员权限。")

        files = []
        cursor = ""
        seen = {cursor}
        for _ in range(30):
            data = self._request("get_knowledge_list", knowledge_base_id=wiki_id,
                                 cursor=cursor, limit=50)
            entries = data.get("knowledge_list") or []
            if not isinstance(entries, list) or not isinstance(data.get("is_end"), bool):
                raise ValueError("ima 返回的条目列表格式有误。")
            files.extend(item for item in entries if isinstance(item, dict) and item.get("media_id"))
            if data["is_end"]:
                return title, files
            cursor = data.get("next_cursor")
            if not isinstance(cursor, str) or cursor in seen:
                raise ValueError("ima 内容列表未能完整读取，请重试。")
            seen.add(cursor)
        raise ValueError("ima 条目列表过大，请使用单独的客服资料库。")

    @staticmethod
    def faq_entries(items: list[dict]) -> dict[str, str]:
        files = {}
        for item in items:
            title = str(item.get("title") or "").strip()
            if title.endswith(FILE_SUFFIX.removesuffix(".txt")):
                title += ".txt"
            if not title.endswith(FILE_SUFFIX):
                continue
            project = title.removesuffix(FILE_SUFFIX).strip()
            if not project or not re.fullmatch(r"[\w .－—-]{1,60}", project):
                raise ValueError("ima 中有无法识别的游戏问答文件名。")
            if title in files:
                raise ValueError(f"ima 里有同名文件「{title}」，请保留一个正式版本。")
            files[title] = str(item["media_id"])
        return files

    def read_faqs(self, files: dict[str, str]) -> list[FaqDocument]:
        documents = []
        for name, media_id in files.items():
            media = self._request("get_media_info", media_id=media_id)
            link = media.get("url_info") or {}
            url = str(link.get("url") or "")
            try:
                parsed = urlsplit(url)
                host = parsed.hostname or ""
                is_tencent = host == "ima.qq.com" or host.endswith((".ima.qq.com", ".myqcloud.com"))
                safe = parsed.scheme == "https" and not parsed.netloc.count("@") and parsed.port in (None, 443) and is_tencent
            except ValueError:
                safe = False
            if not safe:
                raise ValueError(f"ima 未提供可读取的官方文件链接：{name}")
            private_headers = {*self.headers, "cookie", "host"}
            headers = {k: v for k, v in (link.get("headers") or {}).items()
                       if k.lower() not in private_headers}
            try:
                with self.http.stream("GET", url, headers=headers, follow_redirects=False) as response:
                    response.raise_for_status()
                    content = bytearray()
                    for block in response.iter_bytes():
                        content.extend(block)
                        if len(content) > _MAX_FILE_BYTES:
                            raise ValueError(f"问答文件超过 2 MB，请按游戏拆分：{name}")
                text = content.decode("utf-8-sig")
            except (httpx.HTTPError, UnicodeDecodeError):
                raise ValueError(f"读取 ima 文件失败或文件不是 UTF-8 文本：{name}") from None
            project = name.removesuffix(FILE_SUFFIX)
            if text.strip().splitlines()[:1] != [project + TITLE_SUFFIX]:
                raise ValueError(f"文件名与首行的游戏名不一致：{name}")
            chunks = parse_game_faq(text)
            documents.append(FaqDocument(name, bytes(content), len(chunks)))
        return documents


def sync_to_archive(wiki_id: str, title: str, documents: list[FaqDocument], qdrant) -> dict:
    """Publish to a separate archive; importing never selects it for active replies."""
    from pipeline.upload import import_files
    from rag import archives, prompt_store

    if not documents:
        raise ValueError("ima 里还没有可同步的「游戏名 客服问答.txt」文件。")
    marker = f"ima:{wiki_id}"
    archive = next((entry for entry in archives.all_archives() if entry.get("note") == marker), None)
    if archive is None:
        system = prompt_store.get("system")
        archive = archives.create(f"ima · {title}"[:80], note=marker)
        archives.copy_dirs(archives.active_id(), archive["id"], kinds=("prompts",))
        prompt_dir = archives.prompts_dir(archive["id"])
        prompt_dir.mkdir(parents=True, exist_ok=True)
        (prompt_dir / "system.md").write_text(system.rstrip() + _REPLY_RULE, encoding="utf-8")

    destination = archives.upload_dir(archive["id"])
    old_files = {file.name for file in destination.glob("ima - *.txt")}
    next_files = {"ima - " + document.name for document in documents}
    if missing := old_files - next_files:
        raise ValueError("ima 中缺少之前同步过的问答文件，请核对后重试：" +
                         "、".join(name.removeprefix("ima - ") for name in sorted(missing)))
    with TemporaryDirectory(prefix="wecom-ima-") as temp:
        paths = []
        for document in documents:
            path = Path(temp) / ("ima - " + document.name)
            path.write_bytes(document.content)
            paths.append(path)
        result = import_files(paths, qdrant, archive_id=archive["id"])
    return {"archive": archive["id"], "name": archive["name"], "importResult": result}
