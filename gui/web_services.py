"""Presentation adapters for the Web pages, reusing existing stores and pipelines."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
import tempfile
import threading
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path


def revision(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class WebServices:
    def __init__(self, cfg, qdrant=None):
        self.cfg = cfg
        self.qdrant = qdrant
        self.lock = threading.RLock()
        self.plans = {}
        from rag.assistant import Assistant
        self.assistant = Assistant(self)

    def _client(self):
        if self.qdrant is None:
            raise ValueError("资料库连接尚未准备好，请等待主程序完成启动。")
        return self.qdrant

    def read(self, name, params):
        with self.lock:
            return self._read(name, params)

    def _read(self, name, params):
        from rag import archives
        if name == "learning":
            from rag.reply_learning import reviews
            from rag.reply_learning import status
            rows = reviews(archives.active_id())
            for row in rows:
                row["receipt"] = status(
                    archives.active_id(), row["question"], row["answer"], self.qdrant, review=row,
                )
            return {"archive": archives.active_id(), "reviews": rows}
        if name == "assistant":
            from rag.assistant import TOOLS
            from app_paths import app_dir
            runtime = app_dir() / "_internal/python/python.exe"
            if not runtime.is_file():
                import sys
                runtime = Path(sys.executable)
            return {"archive": archives.active_id(), "tools": TOOLS,
                    "mcp": {"command": str(runtime),
                            "args": [str(app_dir() / "scripts/assistant_mcp.py")]}}
        if name == "ima":
            from rag.ima_kb import read_settings
            return read_settings()
        if name == "settings":
            from config import settings_store as store
            from rag.llm_client import PRESETS, DEFAULT_BASE_URL, DEFAULT_MODEL
            values = store.read_current_settings()
            saved = {key: bool(values.get(key)) for key in ("llm_api_key", "wecom_kf_secret")}
            for key in saved:
                values[key] = ""
            if saved["llm_api_key"]:
                values["llm_base_url"] = values["llm_base_url"] or DEFAULT_BASE_URL
                values["llm_model"] = values["llm_model"] or DEFAULT_MODEL
            return {"values": values, "savedSecrets": saved, "presets": PRESETS,
                    "channels": store.software_options()}
        if name == "dashboard":
            from stats import aggregate as agg
            start = date.fromisoformat(params.get("start") or date.today().isoformat())
            end = date.fromisoformat(params.get("end") or date.today().isoformat())
            if end < start or (end - start).days > 366:
                raise ValueError("请选择不超过一年的有效日期范围。")
            demo = params.get("example") == "1"
            root = agg.ROOT / "data" / "demo_stats" if demo else None
            st = agg.aggregate(start, end, root=root)
            result = {k: v for k, v in st.__dict__.items() if k not in ("start", "end", "buckets", "by_path", "by_source", "by_hour")}
            result.update(start=str(start), end=str(end), buckets=[asdict(b) for b in st.buckets],
                          by_path=dict(st.by_path), by_source=dict(st.by_source), by_hour=dict(st.by_hour),
                          solve_rate=st.solve_rate, example=demo)
            logs = agg.read_reply_log((root or agg.ROOT) / "logs" / "auto_replies.jsonl")
            result["export_rows"] = [{**r, "ts": str(r["ts"]), "path": agg.classify_path(r)}
                for r in logs if start <= r["ts"].date() <= end]
            return result
        active = archives.active_id()
        archive_list = archives.all_archives()
        common = {"archive": active, "archives": archive_list}
        if name == "unanswered":
            from rag import unanswered
            return {**common, "rows": unanswered.top(None), "total": unanswered.total(), "todo": unanswered.todo_count()}
        if name == "knowledge":
            from rag import kb_tools
            from pipeline.upload import list_uploaded
            client = self._client()
            page = max(0, int(params.get("page", 0)))
            keyword = str(params.get("query", ""))[:200]
            collection = archives.active_collection()
            if keyword:
                rows, total = kb_tools.search_entries(client, collection, keyword, offset=page*50, limit=50)
            else:
                total = kb_tools.count(client, collection)
                page = min(page, max(0, (total-1)//50))
                rows = kb_tools.list_entries(client, collection, offset=page*50, limit=50)
            for row in rows:
                row["revision"] = revision(row["text"])
            return {**common, "rows": rows, "total": total, "page": page, "files": list_uploaded()}
        if name == "prompts":
            from rag import prompt_store as ps
            return {**common, "prompts": [{"key": key, "label": entry[1], "required": entry[2],
                "text": ps.get(key), "revision": revision(ps.get(key))} for key, entry in ps.PROMPTS.items()],
                "safety": ps.SAFETY_RULES}
        if name == "learned":
            from rag import learn_store as ls
            from rag.learn import learned_block
            rows = [{**r, "kind": ls.STYLE_RULES, "text": r.get("rule", ""), "label": "语气规则"} for r in ls.style_rules()]
            rows += [{**r, "kind": ls.TONE_SAMPLES, "label": "口吻样本"} for r in ls.tone_samples()]
            return {**common, "rows": rows, "facts": ls.facts("pending"),
                    "factHistory": ls.facts("accepted") + ls.facts("rejected"), "counts": ls.counts(),
                    "enabled": ls.enabled(self.cfg), "preview": learned_block(self.cfg)}
        if name == "probe":
            return common
        raise ValueError("页面不存在")

    def preview_reply(self, payload):
        from rag import kb_tools
        from rag.generator import generate_reply
        question = str(payload.get("question", "")).strip()
        if not question or len(question) > 6000:
            raise ValueError("请输入要测试的问题，最多 6000 字。")
        history = payload.get("history") or []
        if not isinstance(history, list) or len(history) > 12:
            raise ValueError("最多提供 12 条上下文消息。")
        if any(not isinstance(h, dict) or h.get("role") not in ("customer", "assistant")
               or not isinstance(h.get("text"), str) or len(h["text"]) > 6000 for h in history):
            raise ValueError("上下文格式无效。")
        from rag.game_scope import retrieval_question
        hits = kb_tools.probe(self._client(), retrieval_question(question, history), top_k=12)
        reply = asyncio.run(generate_reply(question, [h["text"] for h in hits], history=history))
        return {"reply": reply, "hits": hits, "message": "已生成测试回复"}

    def _settings_values(self, payload):
        from config import settings_store as store
        current = store.read_current_settings()
        incoming = payload.get("values", {})
        if not isinstance(incoming, dict):
            raise ValueError("设置格式无效")
        values = {key: str(incoming.get(key, current[key])).strip() for key in current}
        from rag.llm_client import DEFAULT_BASE_URL
        old_base = (current["llm_base_url"] or DEFAULT_BASE_URL).rstrip("/")
        for key in ("llm_api_key", "wecom_kf_secret"):
            if not values[key] and not payload.get("clearSecrets", {}).get(key):
                if key == "llm_api_key" and values["llm_base_url"].rstrip("/") != old_base:
                    continue  # Never forward a saved key to a newly entered provider.
                values[key] = current[key]
        return values

    def command(self, action, payload):
        if action == "assistant.chat":
            return self.assistant.chat(payload.get("text", ""), payload.get("conversation", ""))
        with self.lock:
            return self._command(action, payload)

    def _command(self, action, p):
        if action == "assistant.tool":
            return self.assistant.tool(str(p.get("tool", "")), p.get("arguments", {}))
        if action == "assistant.apply":
            return self.assistant.apply(str(p.get("id", "")))
        if action == "assistant.undo":
            return self.assistant.undo(str(p.get("id", "")))
        if action == "assistant.cancel":
            plan = self.assistant.changes.get(p.get("id"))
            if plan and plan["status"] == "pending":
                plan["status"] = "cancelled"
            return {"message": "已取消变更"}
        if action.startswith("settings."):
            from config import settings_store as store
            from rag import llm_client
            v = self._settings_values(p)
            if action == "settings.models":
                try:
                    models = asyncio.run(llm_client.list_models(v["llm_base_url"], v["llm_api_key"]))
                except RuntimeError as error:
                    # list_models already converts provider errors to safe, useful UI copy.
                    raise ValueError(str(error)) from None
                return {"models": models, "message": f"已读取 {len(models)} 个模型"}
            if action == "settings.test":
                ok, detail = asyncio.run(llm_client.ping(settings=(v["llm_api_key"], v["llm_base_url"], v["llm_model"])))
                if not ok:
                    raise ValueError(detail)
                return {"message": "连接成功，所选模型可以正常回复。"}
            if action == "settings.wecom_test":
                from gateway.wecom_kf import WeComKFClient
                if not v["wecom_corp_id"] or not v["wecom_kf_secret"]:
                    raise ValueError("请填写企业 ID 与客服 Secret。")
                client = WeComKFClient(corp_id=v["wecom_corp_id"], secret=v["wecom_kf_secret"], open_kfid=v["wecom_open_kfid"], state_path="data/state/wecom_kf.json")
                ok, detail = client.selftest()
                if not ok:
                    raise ValueError(detail)
                return {"message": detail or "企业微信连接成功"}
            if action == "settings.save":
                if v["llm_api_key"] and not v["llm_model"]:
                    raise ValueError("请先拉取模型并选择一个模型。")
                if not v["llm_api_key"] and not p.get("allowEmptyKey"):
                    raise ValueError("密钥为空，请确认是否保存无模型配置。")
                allowed = [sid for sid, _, available, _ in store.software_options() if available]
                if v["software"] not in allowed:
                    raise ValueError("请选择可用的接入通道。")
                result = store.save_settings(v)
                from dotenv import load_dotenv
                load_dotenv(store.ENV_PATH, override=True)
                llm_client.reset_client()
                return {**result, "message": "设置已保存。" + ("接入通道变更需要重启。" if result["software_changed"] else "模型设置已立即生效。")}
            raise ValueError("不支持的设置操作")

        from rag import archives, kb_tools, kb_history, prompt_store as ps, learn_store as ls
        if p.get("archive") != archives.active_id():
            raise ValueError("当前资料库档案已切换，请刷新页面后重试。")
        collection = archives.active_collection()
        if action in ("reply.prepare", "reply.commit", "reply.decline"):
            from rag import reply_learning
            if action == "reply.prepare":
                from gui.main_window import load_reply_history
                record = next((r for r in load_reply_history(limit=5000)
                               if r.record_id == p.get("record")), None)
                if record is None or record.archive != archives.active_id():
                    raise ValueError("找不到这条已发送记录，旧记录可以在资料库里手动新增问答。")
                row = reply_learning.prepare(
                    record.question, record.reply, record.draft, archive=record.archive,
                    cfg={**self.cfg, "kb": {**self.cfg.get("kb", {}),
                         "learn": {**self.cfg.get("kb", {}).get("learn", {}), "enabled": True}}},
                    direct=record.source != "human_edit",
                )
            elif action == "reply.commit":
                row = reply_learning.commit(archives.active_id(), str(p.get("id", "")),
                                             p.get("keys", []), self.cfg, self._client())
            else:
                row = reply_learning.get(archives.active_id(), str(p.get("id", "")))
                if row is None:
                    raise ValueError("学习记录不存在。")
                row = reply_learning.save(archives.active_id(), {**row, "status": "declined"})
            return {"review": row, "message": "学习内容已更新"}
        if action == "probe.preview":
            return self.preview_reply(p)
        if action == "review.import":
            rows = p.get("items")
            if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
                raise ValueError("请选择包含 1–1000 条复核资料的 JSON 文件。")
            for row in rows:
                if not isinstance(row, dict) or any(not isinstance(row.get(k), str)
                        for k in ("game", "question", "claim", "reason", "needed", "source_lines")):
                    raise ValueError("复核文件字段不完整，请使用导出的正式复核文件。")
                if any(len(value) > 5000 for value in row.values() if isinstance(value, str)):
                    raise ValueError("单条复核资料过长，请按问题拆分。")
            for row in rows:
                ls.add_fact(
                    row["game"] + "：" + row["question"], row["game"] + "：" + row["claim"],
                    cfg={**self.cfg, "kb": {"learn": {"max_items": 500}}},
                    source="历史聊天复核",
                    review={key: row[key] for key in ("reason", "needed", "source_lines")},
                )
            return {"message": f"已导入 {len(rows)} 条复核资料，确认后可采纳入库"}
        if action == "kb.ima_save":
            from rag.ima_kb import save_settings
            return {**save_settings(p), "message": "ima 配置已保存"}
        if action == "kb.ima_saved_sync":
            from rag.ima_kb import sync_saved
            return sync_saved(self._client())
        if action in ("unanswered.done", "unanswered.clear"):
            from rag import unanswered
            if action.endswith("clear"):
                unanswered.clear()
            else:
                unanswered.mark_done(str(p.get("question", "")))
            return {"message": "转人工问题统计已更新"}
        if action.startswith("archive."):
            target = str(p.get("id", ""))
            if action == "archive.switch":
                if not archives.set_active(target):
                    raise ValueError("资料库档案不存在")
                ps.ensure_files()
            elif action in ("archive.create", "archive.copy"):
                name = str(p.get("name", "")).strip()
                if not name or len(name) > 80:
                    raise ValueError("请输入 1–80 字的档案名称。")
                src = archives.active_id()
                entry = archives.create(name)
                archives.copy_dirs(src, entry["id"], kinds=("uploads", "prompts", "learned") if action.endswith("copy") else ("prompts", "learned"))
                if action.endswith("copy"):
                    kb_tools.copy_collection(self._client(), collection, entry["collection"])
            elif action == "archive.rename":
                if not str(p.get("name", "")).strip() or not archives.rename(target, p["name"]):
                    raise ValueError("无法重命名档案")
            elif action == "archive.delete":
                if target == archives.active_id() or archives.is_first(target):
                    raise ValueError("不能删除正在使用或默认资料库，请先切换到其他档案。")
                if not archives.get(target):
                    raise ValueError("资料库档案不存在")
                client = self._client()
                target_collection = archives.collection_of(target)
                if client.collection_exists(target_collection):
                    client.delete_collection(target_collection)
                if not archives.delete(target):
                    raise ValueError("档案未删除")
            else:
                raise ValueError("不支持的档案操作")
            return {"message": "资料库档案已更新"}
        if action in ("prompt.save", "prompt.reset"):
            key = p.get("key")
            if key not in ps.PROMPTS:
                raise ValueError("提示词不存在")
            if p.get("revision") != revision(ps.get(key)):
                raise ValueError("提示词已被其他窗口修改，请重新读取后保存。")
            if action.endswith("reset"):
                ps.reset(key)
            else:
                ok, reason = ps.set_prompt(key, str(p.get("text", "")))
                if not ok:
                    raise ValueError(reason)
            return {"message": "提示词已保存，立即生效"}
        if action == "learn.toggle":
            from config.settings_store import load_config, save_config
            cfg = load_config()
            cfg.setdefault("kb", {}).setdefault("learn", {})["enabled"] = bool(p.get("enabled"))
            save_config(cfg)
            self.cfg.setdefault("kb", {}).setdefault("learn", {})["enabled"] = bool(p.get("enabled"))
            return {"message": "学习设置已更新"}
        if action in ("learn.delete", "learn.block"):
            if p.get("kind") not in (ls.STYLE_RULES, ls.TONE_SAMPLES):
                raise ValueError("学习记录类型无效")
            operation = ls.drop_and_block if action.endswith("block") else ls.delete_item
            if not operation(p["kind"], p.get("id")):
                raise ValueError("这条记录已不存在")
            return {"message": "学习记录已更新"}
        if action in ("fact.accept", "fact.reject"):
            fact = next((f for f in ls.facts("pending") if f["id"] == p.get("id")), None)
            if not fact:
                raise ValueError("这条事实已处理")
            if action.endswith("accept"):
                question = str(p.get("question", fact.get("question", ""))).strip()
                answer = str(p.get("answer", fact.get("claim", ""))).strip()
                if not question or not answer or len(question) > 2000 or len(answer) > 10000:
                    raise ValueError("请填写完整问题和已核实的答案。")
                result = kb_tools.add_entry(self._client(), question, answer, source="人工改稿学到", collection=collection)
                kb_history.record(result["id"], "", "人工改稿学到", reason="学到的说法入库")
            ls.set_fact_status(fact["id"], "accepted" if action.endswith("accept") else "rejected",
                               entry_id=result["id"] if action.endswith("accept") else "",
                               published={"question": question, "answer": answer}
                               if action.endswith("accept") else None)
            return {"message": "已采纳并加入资料库" if action.endswith("accept") else "已拒绝这条事实"}
        if action == "probe.run":
            from rag.guard import high_threshold
            question = str(p.get("question", "")).strip()
            if not question:
                raise ValueError("请输入要测试的问题")
            threshold = high_threshold(self.cfg)
            hits = kb_tools.probe(self._client(), question, top_k=5, collection=collection)
            return {"hits": [{**h, "verdict": kb_tools.verdict(h["score"], threshold)} for h in hits], "threshold": threshold, "message": "检索完成"}
        if action in ("kb.add", "kb.edit", "kb.delete", "kb.undo"):
            client = self._client()
            if action != "kb.add":
                old = kb_tools.get_entry(client, p.get("id"), collection)
                if not old or p.get("revision") != revision(old["text"]):
                    raise ValueError("这条资料已变更，请刷新后再操作。")
            if action == "kb.add":
                result = kb_tools.add_entry(client, str(p.get("question", "")), str(p.get("answer", "")), collection=collection)
                if p.get("unanswered"):
                    from rag import unanswered
                    unanswered.mark_done(p["unanswered"])
            elif action == "kb.edit":
                from pipeline.embedder import chunk_id
                text = kb_tools.make_faq(p.get("question", ""), p.get("answer", "")) if old["faq"] else str(p.get("answer", ""))
                if not text.strip():
                    raise ValueError("资料内容不能为空")
                kb_history.record(str(chunk_id(text)), old["text"], old["source"], keep=kb_history.keep_versions(self.cfg))
                result = kb_tools.update_entry(client, old["id"], text, collection)
            elif action == "kb.undo":
                if not kb_history.versions(old["id"]):
                    raise ValueError("这条资料没有可撤销的历史版本。")
                result = kb_history.undo(client, old["id"], collection)
            else:
                kb_history.record(old["id"], old["text"], old["source"], reason="删除")
                if not kb_tools.delete_entry(client, old["id"], collection):
                    raise ValueError("删除失败")
                result = {}
            return {"entry": result, "message": "资料已更新"}
        if action == "kb.rebuild":
            from pipeline.upload import source_files, import_files
            from rag.retriever import ensure_collection
            files = source_files()
            if not files:
                raise ValueError("没有可重建的源文件，请先上传资料。")
            client = self._client()
            client.delete_collection(collection)
            ensure_collection(client, collection)
            result = import_files([str(f) for f in files], client, collection)
            return {"message": f"重建完成：{len(result['ok'])} 个文件，{result['chunks']} 块", "importResult": result}
        if action in ("kb.ima_test", "kb.ima_sync", "kb.ima_bases"):
            import httpx
            from rag.ima_kb import ImaKnowledge, credentials, knowledge_base_id, sync_to_archive

            client_id, api_key = credentials(str(p.get("clientId", "")), str(p.get("apiKey", "")))
            with httpx.Client(timeout=12) as http:
                ima = ImaKnowledge(http, client_id, api_key)
                if action == "kb.ima_bases":
                    return {"bases": ima.bases(str(p.get("query", ""))),
                            "message": "已读取可访问的 ima 知识库"}
                wiki_id = knowledge_base_id(str(p.get("wiki", "")))
                title, items = ima.inventory(wiki_id)
                if action == "kb.ima_test":
                    return {"title": title, "total": len(items),
                            "files": list(ima.faq_entries(items)),
                            "message": f"已连接 ima「{title}」"}
                documents = ima.read_faqs(ima.faq_entries(items))
            synced = sync_to_archive(wiki_id, title, documents, self._client())
            result = synced["importResult"]
            synced["message"] = (f"已写入「{synced['name']}」，成功 {len(result['ok'])} 份，"
                                 f"失败 {len(result['failed'])} 份，共 {result['chunks']} 条")
            return synced
        if action in ("kb.import", "ingest.plan"):
            files = p.get("files", [])
            if not isinstance(files, list) or not 1 <= len(files) <= 20:
                raise ValueError("请选择 1–20 个文件")
            if action == "ingest.plan" and len(files) != 1:
                raise ValueError("AI 整理一次只处理一个文件")
            with tempfile.TemporaryDirectory(prefix="wecom-upload-") as tmp:
                paths = []
                for upload in files:
                    name = str(upload.get("name", "")).replace("\\", "/").split("/")[-1]
                    if not name or Path(name).suffix.lower() not in (".txt", ".md", ".csv", ".xlsx", ".xlsm", ".xls", ".docx") or ":" in name:
                        raise ValueError("不支持的文件类型")
                    data = base64.b64decode(upload.get("data", ""), validate=True)
                    if len(data) > 20 * 1024 * 1024:
                        raise ValueError("单个文件不能超过 20 MB")
                    path = Path(tmp) / name
                    path.write_bytes(data)
                    paths.append(str(path))
                if action == "kb.import":
                    from pipeline.upload import import_files
                    result = import_files(paths, self._client(), collection)
                    return {"importResult": result, "message": f"导入完成：成功 {len(result['ok'])} 个，失败 {len(result['failed'])} 个，共 {result['chunks']} 块"}
                from rag.llm_ingest import chunks_from_file
                chunks = chunks_from_file(paths[0], limit=100000)
                if not chunks:
                    raise ValueError("文件中没有可整理的文字")
                plan_id = secrets.token_urlsafe(16)
                self.plans.clear()
                self.plans[plan_id] = {"chunks": chunks[:100], "archive": archives.active_id(), "source": Path(paths[0]).name}
                return {"planId": plan_id, "total": len(chunks), "planned": min(100, len(chunks)), "message": "文件已读取，请确认整理范围"}
        if action.startswith("ingest."):
            plan = self.plans.get(p.get("planId"))
            if not plan or plan["archive"] != archives.active_id():
                raise ValueError("整理预览已失效，请重新选择文件。")
            if action == "ingest.run":
                from rag.llm_ingest import build_entries
                plan["entries"] = asyncio.run(build_entries(plan["chunks"]))
                return {"entries": plan["entries"], "message": "整理完成，请核对原文并选择要写入的问答"}
            if action == "ingest.commit":
                from pipeline.embedder import embed_and_store
                from rag.llm_ingest import to_faq
                rows = p.get("entries", [])
                if not rows or len(rows) > 2000:
                    raise ValueError("请选择要写入的条目")
                validated = []
                for row in rows:
                    index = row.get("index")
                    if not isinstance(index, int) or not 0 <= index < len(plan.get("entries", [])):
                        raise ValueError("条目不属于当前预览")
                    if not row.get("question", "").strip() or not row.get("answer", "").strip():
                        raise ValueError("选中条目的问题和答案不能为空")
                    validated.append(to_faq(row))
                count = embed_and_store(validated, self._client(), collection, source=plan["source"], extra={"origin": "AI整理"})
                del self.plans[p["planId"]]
                return {"message": f"已写入 {count} 条问答"}
        raise ValueError("不支持的操作")
