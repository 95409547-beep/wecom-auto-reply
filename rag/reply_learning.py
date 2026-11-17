"""Persistent, archive-specific learning reviews for successfully sent replies."""

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from threading import RLock

from rag import archives, learn_store

_lock = RLock()


def reply_key(question: str, answer: str) -> str:
    return hashlib.sha256(json.dumps(
        [question or "", answer or ""], ensure_ascii=False,
    ).encode()).hexdigest()[:24]


def _path(archive: str):
    return archives.learned_dir(archive) / "reply_reviews.json"


def reviews(archive: str) -> list[dict]:
    # Writers publish by atomic replace, so UI snapshots can read without
    # waiting for an embedding operation or language-model analysis.
    path = _path(archive)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.values())


def get(archive: str, key: str) -> dict | None:
    return next((row for row in reviews(archive) if row["id"] == key), None)


def save(archive: str, row: dict) -> dict:
    with _lock:
        rows = {r["id"]: r for r in reviews(archive)}
        row = {**row, "updated": datetime.now().isoformat(timespec="seconds")}
        rows[row["id"]] = row
        path = _path(archive)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        return deepcopy(row)


def prepare(question: str, answer: str, draft: str = "", *, archive: str,
            cfg: dict, direct: bool = False) -> dict:
    from rag.learn import propose

    key = reply_key(question, answer)
    previous = get(archive, key)
    if previous and previous["status"] in ("ready", "learned"):
        return previous
    row = {"id": key, "archive": archive, "question": question, "answer": answer,
           "draft": draft, "status": "analyzing", "entries": [], "result": {}}
    save(archive, row)
    if not learn_store.enabled(cfg):
        return save(archive, {**row, "status": "disabled", "reason": "学习功能已关闭"})
    try:
        proposal = {"ok": True, "customer_question": question, "human": answer,
                    "draft": draft, "rules": [], "tone": None, "facts": []}
        if not direct:
            proposal = propose(question, draft, answer, cfg=cfg,
                               base=archives.learned_dir(archive))
        # A complete Q&A is selectable even when the edit changed only the tone.
        # Nothing is published until the operator checks it and confirms.
        proposal.update(ok=True, facts=[
            {"key": "reply", "question": question, "claim": answer},
        ] if question.strip() else [])
        return save(archive, {**row, "status": "ready", "proposal": proposal})
    except Exception:
        save(archive, {**row, "status": "error", "reason": "分析失败，可重新分析或手动补充问答"})
        raise


def commit(archive: str, key: str, keys: list[str], cfg: dict, qdrant) -> dict:
    from rag import kb_tools
    from rag.learn import commit as commit_proposal

    with _lock:
        row = get(archive, key)
        if not row:
            raise ValueError("学习记录不存在，请刷新后重试。")
        if row["status"] not in ("ready", "learned"):
            raise ValueError("请先完成回复分析。")
        if not keys:
            raise ValueError("请勾选要学习的内容。")
        proposal = row["proposal"]
        valid = {r["key"] for r in proposal.get("rules", [])}
        valid.update(f["key"] for f in proposal.get("facts", []))
        if proposal.get("tone"):
            valid.add(proposal["tone"]["key"])
        if not set(keys) <= valid:
            raise ValueError("选择的学习内容已经失效。")
        previous_keys = set(row.get("selected", []))
        remaining = set(keys) - previous_keys
        if not remaining:
            return row
        result = commit_proposal(
            proposal, remaining, cfg=cfg, base=archives.learned_dir(archive),
            qdrant=qdrant, collection=archives.collection_of(archive),
        )
        entries = list(row.get("entries", []))
        if result["facts"] and "reply" in remaining:
            from pipeline.embedder import chunk_id
            entry_id = chunk_id(kb_tools.make_faq(row["question"], row["answer"]))
            if kb_tools.get_entry(qdrant, entry_id, archives.collection_of(archive)):
                entries = list(dict.fromkeys([*entries, entry_id]))
        committed = remaining - ({"reply"} if result["fact_errors"] else set())
        previous_result = row.get("result", {})
        for field in ("rules", "tones", "facts"):
            result[field] += previous_result.get(field, 0)
        return save(archive, {
            **row, "status": "ready" if result["fact_errors"] else "learned",
            "result": result, "entries": entries, "selected": sorted(previous_keys | committed),
        })


def status(archive: str, question: str, answer: str, qdrant=None, *, review=None) -> dict:
    row = review if review is not None else get(archive, reply_key(question, answer))
    if not row:
        return {"status": "unrecorded", "label": "尚无学习记录", "entries": []}
    labels = {"ready": "待确认学习", "analyzing": "正在分析", "disabled": "学习已关闭",
              "declined": "本次未学习", "error": "分析失败", "learned": "已学习"}
    if row["status"] == "learned":
        if row.get("entries"):
            from rag.kb_tools import get_entry
            present = [entry for entry in row["entries"]
                       if qdrant is not None and get_entry(qdrant, entry, archives.collection_of(archive))]
            label = "已加入资料库" if present else "入库条目已变更或删除"
        else:
            label = "已学习语气，问答未入库"
    else:
        label = labels.get(row["status"], "尚无学习记录")
    return {"status": row["status"], "label": label, "entries": row.get("entries", []),
            "review": row["id"], "result": row.get("result", {})}
