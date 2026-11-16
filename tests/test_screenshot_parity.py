# tests/test_screenshot_parity.py
"""截图版补齐：图片/语音不再静默丢掉、发完确认真的发出去了。

为什么截图版也要做这两件：
* API 版是"字段被过滤掉"，截图版是**图片气泡 OCR 读不出字** → 代码走到
  ``OCR空`` 就 continue。客户发张器材照片，一个字都收不到，日志还只写"OCR空"。
* "点输入框→粘贴→回车"**没有任何回执**：剪贴板没设上、回车没生效，
  代码照样当成功，客户那边一直干等。
"""

import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _main_src():
    return (ROOT / "main.py").read_text(encoding="utf-8")


# ── ① 截图模式：读不出字的气泡 → 当图片/语音处理 ──────────────────────

def test_nontext_helper_acks_and_escalates():
    """回一句 + 转人工（一条），不再是静默跳过。"""
    import main as main_mod

    class _Q:
        def __init__(self):
            self.sent = []
            self.pending = []

        def put(self, item):
            self.sent.append(item)

        def push(self, customer, msg, *a, **kw):
            self.pending.append({"customer": customer, "msg": msg, **kw})

    q = _Q()
    ack = main_mod._screenshot_nontext(q, q, "客户A@微信", bubble_count=2)
    assert ack, "必须有应答文案（否则客户还是收不到话）"
    assert q.sent == [("send", "客户A@微信", ack)]
    assert len(q.pending) == 1
    assert "图片" in q.pending[0]["msg"] and "查看" in q.pending[0]["msg"]
    # 截图模式分不清图片还是语音 → 按人合并成一条，key_hint 稳定
    assert q.pending[0]["key_hint"] == "nontext"


def test_nontext_pending_collapses_per_customer():
    """读不出内容，多条也没法区分 → 一个人只留一条待看。"""
    from rag.human_fallback import PendingQueue
    import tempfile
    q = PendingQueue(persist_path=str(Path(tempfile.mkdtemp()) / "pq.json"))
    for _ in range(3):
        q.push("客户A@微信", "（客户发来图片/语音/文件，请打开会话查看）", "",
               0.0, "非文本消息", key_hint="nontext")
    assert len(q.get_all()) == 1


def test_both_paths_handle_empty_ocr_as_nontext():
    """红点路径和兜底路径都要处理（两处都踩过）。"""
    s = _main_src()
    # 1 处函数定义 + 4 处调用（每条路径各两个分支：读不出字 / 读出来太短）
    assert s.count("_screenshot_nontext(send_queue, pending_queue") == 5, \
        "两条扫描路径都要接上"
    assert 'log.info("OCR空")' not in s, "旧的静默跳过必须删掉"
    assert 'log.info(f"兜底y={y} OCR空")' not in s


def test_nontext_handling_happens_before_customer_check():
    """读不出字就没人能判『是不是客户』 —— 处理要在那之前，不然又被拦掉。"""
    s = _main_src()
    i_nontext = s.index("if not bubble_texts:")
    i_cust = s.index("detector.is_customer(", i_nontext)
    assert i_nontext < i_cust


def test_already_seen_bubbles_are_not_treated_as_nontext():
    """读出来了、只是都回过了 → 跳过，不能误判成图片又回一句。"""
    s = _main_src()
    i_len = s.index("if not bubble_texts:")
    i_fresh = s.index("fresh = detector.unseen_texts(", i_len)
    assert i_len < i_fresh, "先判『一个字都没读出来』，再判『都回过了』"


# ── ⑤ 截图模式：发完确认 ──────────────────────────────────────────────

@pytest.mark.parametrize(
    "scenario, expected",
    [
        ("new_matching_reply", True),
        ("new_matching_reply_with_new_customer_message", True),
        ("old_matching_reply", None),
        ("new_unrelated_reply", None),
        ("only_new_customer_message", None),
        ("ocr_unreadable", None),
        ("no_before_capture", None),
        ("no_after_capture", None),
    ],
)
def test_verify_only_confirms_new_matching_outgoing_bubble(monkeypatch, scenario, expected):
    from unittest.mock import Mock
    from PIL import Image, ImageDraw
    import main as main_mod
    from wxbot.detector import MessageDetector

    def screenshot(outgoing=None, incoming=False):
        img = Image.new("RGB", (400, 600), "white")
        draw = ImageDraw.Draw(img)
        if outgoing is not None:
            draw.rectangle((230, 190, 370, 220), fill=(193, 219, 250))
            draw.rectangle((250, 201, 250 + outgoing, 211), fill="black")
        if incoming:
            draw.rectangle((17, 320, 140, 345), fill=(230, 230, 230))
        return img

    before = screenshot(outgoing=4, incoming=True)
    after = screenshot(outgoing=16, incoming=scenario.endswith("customer_message"))
    recognized = "答案 123"
    if scenario == "old_matching_reply":
        after = before.copy()
    elif scenario == "new_unrelated_reply":
        recognized = "其他内容"
    elif scenario == "only_new_customer_message":
        after = screenshot(outgoing=4, incoming=False)
    elif scenario == "ocr_unreadable":
        recognized = ""
    elif scenario == "no_before_capture":
        before = None
    elif scenario == "no_after_capture":
        after = None
    detector = MessageDetector({})
    monkeypatch.setattr(detector, "extract_text", Mock(return_value=recognized))
    monkeypatch.setattr(main_mod.time, "sleep", Mock())
    scanner = Mock()
    scanner.capture_chat_area.return_value = after

    assert main_mod._verify_screenshot_sent(
        scanner, detector, "答案123", before=before
    ) is expected
