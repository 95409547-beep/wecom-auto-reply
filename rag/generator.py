"""Generate customer reply using retrieved knowledge and DeepSeek API.

Supports multi-turn conversation context via sliding window injection.
Includes prompt injection defense (filters system-instruction patterns).
"""

import logging
import asyncio
import random
import re
from typing import Optional

from rag.llm_client import chat

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个专业的销售客服助手。你的回答必须严格遵守以下规则：

1. **只使用提供的知识片段来回答客户问题。** 如果知识片段中没有相关信息，或者客户问的话题知识片段完全没有涉及，你必须回复"需要人工处理"。不得编造、推测或补充任何知识片段中没有的信息。
2. 知识不足时的唯一正确回复是"需要人工处理"这6个字。
   - 禁止回复"我没有相关信息"、"我不太清楚"、"建议您咨询"、"或许可以"等变通说法
   - 禁止回复"请问您需要什么帮助"、"您好请问有什么可以帮您"、"请问您主要想解决什么问题"等泛泛问候
   - 禁止回复"很高兴为您服务"、"我是XX客服"等自我介绍
   - 价格/优惠/折扣等敏感信息同样回复"需要人工处理"，不得编造不同说辞
   - 知识不足时唯一正确回复就是"需要人工处理"
3. 当知识片段覆盖了客户问题时，回复要简洁、专业、友好，像真人销售在跟客户对话。
4. 不要透露你是AI或机器人。
5. 不要使用"根据知识库"、"根据提供的信息"等暴露AI身份的表述。
6. **不要重复自己。** 如果对话记录里你已经回答过客户这个问题，必须换一种说法：
   换句式、换个开头、调整详略（这次可以更短，也可以更具体）。
   绝对不要逐字复用你上一轮的回复 —— 真人不会两次说一模一样的话。
7. 语气自然口语化，像在微信上跟客户聊天，不要像念说明书。
   可以带 emoji，但**最多一个**，别堆。
   下面是店主平时说话的样子，照着这个口吻写（只学措辞，事实仍以知识片段为准）：
{tone_samples}
   不要每句话都用"我们"开头，不要用"尊敬的客户"这类书面语。
8. 知识片段里如果有 [当前时间]，那是真实的系统时间，可以放心引用；
   客户问“现在几点/今天几号”就按它回答。
9. **客户重复问同一个问题时，绝不能复读。** 看他问第几遍了：第一遍给完整说法，
   第二遍更短更随意（“刚说过哈，还是X”），第三遍可以带点人味（“还是老样子～”）。
   宁可短，也不要一模一样。
10. **用词必须确定。** 禁止使用"大概"、"可能"、"也许"、"应该是"、"估计"、
   "差不多"这类表示不确定的副词 —— 即使只是随口一问（比如"你大概哪天过来"）
   也不要用。价格、时间、数量一律说确定的数。

{conversation_history}

可用的知识片段：
{context}

请根据以上信息回复客户的问题。记住：知识不足时只能回复"需要人工处理"。。"""

# Patterns to filter from customer messages (prompt injection defense)
_INJECTION_PATTERNS = [
    r'(?i)你是一个\S*',
    r'(?i)请忽略\S*',
    r'(?i)忽略上面的\S*',
    r'(?i)新的指令\S*',
    r'(?i)ignore\s+(all\s+)?(previous|above)\s+instructions',
    r'(?i)system\s*:\s*',
]


def _sanitize_message(text: str) -> str:
    """Remove prompt-injection patterns from customer messages."""
    for pattern in _INJECTION_PATTERNS:
        text = re.sub(pattern, '[filtered]', text)
    return text.strip()


def _format_history(history: list[dict]) -> str:
    """Format conversation history for prompt injection.

    Args:
        history: List of {"role": "customer"|"assistant", "text": "..."} dicts.

    Returns:
        Formatted string, or empty string if no history.
    """
    if not history:
        return ""
    lines = ["最近的对话记录："]
    for turn in history[-3:]:  # sliding window: last 3 turns only
        role = "客户" if turn.get("role") == "customer" else "客服"
        text = turn.get("text", "")
        # Sanitize customer messages to prevent prompt injection via history
        if turn.get("role") == "customer":
            text = _sanitize_message(text)
        lines.append(f"{role}: {text}")
    return "\n".join(lines)


def build_prompt(
    question: str,
    context_chunks: list[str],
    history: Optional[list[dict]] = None,
    style: Optional[str] = None,
) -> list[dict]:
    """Build LLM chat messages with optional conversation history.

    Args:
        question: Current (sanitized) customer message.
        context_chunks: Retrieved knowledge chunks.
        history: Prior conversation turns (from ContextStore.get_recent).
        style: Optional per-reply style hint (wording only, not facts).

    Returns:
        List of message dicts for LLM chat completion.
    """
    safe_question = _sanitize_message(question)
    context = "\n\n---\n\n".join(context_chunks)
    conv_history = _format_history(history or [])
    from rag.prompt_store import get as get_prompt
    from rag.smalltalk import build_tone_block
    from rag.learn import append_to_system
    system = get_prompt("system").format(
        tone_samples=build_tone_block(),
        conversation_history=conv_history,
        context=context,
    )
    # 学到的口吻/改稿习惯追加在尾部：不动用户编辑的提示词文件，也看得见学了什么
    system = append_to_system(system)
    if style:
        system += (f"\n\n本次答复的风格要求（只影响措辞，不得改变任何事实）：{style}")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": safe_question},
    ]


# 每次生成随机挑一条风格提示 —— 让同一问题的回答在句式上不雷同。
# 实测：只调 temperature 完全无效（0.3/0.8/0.95 下第二次回答都逐字照抄
# 对话历史里自己的上一句话）；加"不要重复自己"规则后每次都换说法，
# 再叠加风格提示后明显更像真人在聊天。
STYLE_NUDGES = [
    "直接给结论，再补充必要条件",
    "用自然的微信口语说明，避免照抄之前的开头",
    "有操作步骤时按实际操作顺序讲；寒暄用简短的一句话",
    "从客户关心的操作或结果说起，换一种自然的句式",
    "简明友好，按问题的重点调整信息顺序和详略",
]


# ── 采样温度 ────────────────────────────────────────────────────────
# 线上用偏高的值（更像真人在聊天）；**跑评测时要固定成 0** ——
# 否则同一套题两次跑出不同结果，尺子就不准了（实测同一句话三次三种结果）。
TEMPERATURE = {"reply": 0.8, "hold": 0.9, "smalltalk": 0.95}

# 风格提示平时随机挑（同一问题换着说法）；评测时固定，让结果可复现。
# ★ 光固定温度不够：风格提示也是随机的，它会影响模型怎么措辞、
#   甚至影响它"要不要转人工"的判断 —— 实测同一题两次结果不同就是这个原因。
STYLE_OVERRIDE = None


def set_temperature(reply: float = None, hold: float = None,
                    smalltalk: float = None) -> None:
    """临时改采样温度（评测用；不传的保持原值）。"""
    for key, val in (("reply", reply), ("hold", hold),
                     ("smalltalk", smalltalk)):
        if val is not None:
            TEMPERATURE[key] = float(val)


def set_style(style: str = None) -> None:
    """固定风格提示（评测用）；传 None 恢复随机。"""
    global STYLE_OVERRIDE
    STYLE_OVERRIDE = style


def _wording_key(text: str) -> str:
    """Ignore punctuation and whitespace when checking a repeated reply."""
    return re.sub(r"[\W_]+", "", text.casefold())


async def _generate_with_variation(
    messages: list[dict],
    channel: str,
    max_tokens: int,
    history: Optional[list[dict]] = None,
) -> str:
    style = STYLE_OVERRIDE or random.choice(STYLE_NUDGES)
    instruction = f"本次措辞风格：{style}。保持游戏、条件、数字和处理结果一致。"
    styled = [dict(messages[0], content=messages[0]["content"] + "\n\n" + instruction),
              *messages[1:]]
    options = {"temperature": TEMPERATURE[channel], "max_tokens": max_tokens}
    reply = (await chat(styled, **options) or "").strip()
    key = _wording_key(reply)
    if STYLE_OVERRIDE or not key or "需要人工处理" in key or "需要帮您确认" in key:
        return reply

    recent = {_wording_key(turn.get("text") or "")
              for turn in (history or [])[-3:] if turn.get("role") == "assistant"}
    if key not in recent:
        return reply
    alternate = random.choice([hint for hint in STYLE_NUDGES if hint != style])
    rewrite = (
        f"上一种句式与该玩家近期收到的回复重复。请按「{alternate}」重答，"
        "改变开头和句式。只使用原问题和知识片段，保留适用条件与数字。"
    )
    retry = [dict(messages[0], content=messages[0]["content"] + "\n\n" + rewrite),
             *messages[1:]]
    try:
        alternative = (await chat(retry, **options) or "").strip()
    except Exception:
        logger.debug("回复换句式失败，沿用首个草稿", exc_info=True)
        alternative = ""
    revised_key = _wording_key(alternative)
    if ("需要人工处理" in revised_key or "需要帮您确认" in revised_key
            or (revised_key and revised_key not in recent
                and set(re.findall(r"\d+(?:\.\d+)?", alternative))
                == set(re.findall(r"\d+(?:\.\d+)?", reply)))):
        return alternative
    if channel != "reply":
        return reply
    openings = ("我再说一下，", "再给你确认一下，", "我换个说法哈，", "我再说明一下，")
    variants = [opening + reply for opening in openings
                if _wording_key(opening + reply) not in recent]
    return random.choice(variants)


async def generate_reply(
    question: str,
    context_chunks: list[str],
    history: Optional[list[dict]] = None,
) -> str:
    """Generate a reply using DeepSeek with knowledge context and history."""
    from rag.game_scope import ASK_GAME_VARIANTS, scope_chunks
    context_chunks, needs_game = scope_chunks(question, context_chunks, history)
    if needs_game:
        return random.choice(ASK_GAME_VARIANTS)
    messages = build_prompt(question, context_chunks, history=history)
    if any("适用项目：" in chunk for chunk in context_chunks):
        messages[0]["content"] += (
            "\n\n客服正文通常写 1–2 句，直接回答当前问题。"
            "保留实际操作步骤和版本、区服、渠道等必要条件。"
        )
    return await _generate_with_variation(messages, "reply", 512, history)


# ── 转人工时发给客户的"稍等"占位语 ─────────────────────────────────

HOLD_SYSTEM_PROMPT = """客户问了一句话，你需要先礼貌地告诉客户"我去确认一下，稍等"。

规则：
1. **必须提到客户问的具体内容**，把客户问的东西换个说法说出来。
   例如客户问"礼包还没到账"，就回"我帮你查一下礼包发放情况，稍等哈"。
   如果游戏归属不清，可以先问游戏名和区服。
2. 只表达"我去确认、请稍等"，**不要给出针对客户这一单的任何结论**
   （能否补发、多久到账、是否解封、获得多少福利）。
3. **例外：如果客户消息里附了资料片段，且片段里写明了通用政策**
   并且项目、渠道和适用时间都已核实，可以引用一句；资料范围不明确时只表达正在核实。
   引用时必须**只重复片段里明说的内容**，并且**仍要落到"我帮您确认"**上，
   不许把通用政策说成对这一单的保证。
4. 一句话，不超过 40 个字，语气自然口语化，像微信聊天。
5. 禁止使用"大概""可能""也许""应该是""请咨询"这类不确定的词。
6. 不要用"您好，请问"这类套话开场，也不要自称 AI 或客服机器人。

只输出这一句话，不要加引号、不要解释。"""


async def generate_hold_reply(question: str, chunks: list = None) -> str:
    """生成一句带客户问题内容的礼貌占位语（如"帮您问下适合滑雪的机器"）。

    `chunks`（可选）：检索到的资料片段。**只在资料里确实有相关通用政策时才传**
    （调用方按检索分判断），例如资料写着"24 小时发货"，占位语就可以是
    「我们的发货时效是 24 小时内，您这单我帮您确认下具体进度～」——
    让客户不至于只听到"稍等"，同时**不许**推演成对客户这一单的承诺。

    由调用方兜底：失败时退回 rag.responder.HOLD_REPLIES 里的固定话术。
    """
    from rag.prompt_store import get as get_prompt
    user = _sanitize_message(question)
    if chunks:
        # 片段塞进 user 消息而不是靠 format 占位符：hold.md 是**用户可编辑**的，
        # 加占位符会让用户在正文里打花括号就崩（prompt_store 的已知坑）。
        user = (
            f"客户问：{question}\n\n"
            "我手上有的资料片段：\n"
            + "\n---\n".join(str(c)[:400] for c in chunks[:3])
            + "\n\n（如果片段里写明了**通用政策**（比如发货时效、退货规则），"
              "可以在占位语里提一句；但**绝对不能说客户这一单的具体时间或结果**。）"
        )
    messages = [
        {"role": "system", "content": get_prompt("hold")},
        {"role": "user", "content": user},
    ]
    return await _generate_with_variation(messages, "hold", 80)


async def generate_smalltalk_reply(text: str, history: list = None,
                                   timeout: float = 20.0) -> str:
    """非业务消息的闲聊回复 —— 店员视角，短、口语、可带一个 emoji。

    与 generate_reply 的区别：**不喂知识片段**（闲聊不需要也不该引事实），
    提示词里明确禁止提价格/库存/政策。
    """
    from rag.prompt_store import get as get_prompt, parse_tone_samples
    from rag.smalltalk import build_tone_block
    from rag.learn import append_to_system
    sys_prompt = get_prompt("smalltalk").format(
        tone_samples=build_tone_block(parse_tone_samples()))
    sys_prompt = append_to_system(sys_prompt)
    msgs = [{"role": "system", "content": sys_prompt}]
    hist = _format_history(history or [])
    if hist:
        msgs.append({"role": "system", "content": hist})
    msgs.append({"role": "user", "content": _sanitize_message(text)})
    reply = await asyncio.wait_for(
        _generate_with_variation(msgs, "smalltalk", 160, history),
        timeout=timeout)
    return (reply or "").strip().strip('"').strip("'")
