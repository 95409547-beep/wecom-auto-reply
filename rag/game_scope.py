"""Select game-specific evidence using the current message and conversation."""

import re

PROJECT_MARK = re.compile(r"适用项目[：:]\s*([^。\n]+)")
KNOWN_GAMES = ("天仙月", "仙语奇缘魔改版", "西游神传", "镇魂兵团")
ASK_GAME = "你玩的是哪款游戏呀？有版本或区服的话也一起发我。"
ASK_GAME_VARIANTS = (
    ASK_GAME,
    "先确认下你玩的是哪款游戏？版本和区服也一起告诉我哈。",
    "你说的是哪款游戏呀？有版本或区服的话，发我一起核对下。",
)


def retrieval_question(question: str, history=None) -> str:
    """Expand a short follow-up while leaving the current game in charge."""
    if not history or len(question) > 24:
        return question
    short_followup = question.rstrip("？?。！! ").endswith("呢")
    if not short_followup and (len(question) > 12 or any(game in question for game in KNOWN_GAMES)):
        return question
    for turn in reversed(history):
        previous = turn.get("text", "")
        if turn.get("role") == "customer" and previous != question:
            for game in KNOWN_GAMES:
                previous = previous.replace(game, "")
            return question + "\n此前相关问题：" + previous[:300]
    return question


def scope_chunks(question: str, chunks: list[str], history=None) -> tuple[list[str], bool]:
    tagged = [(text, PROJECT_MARK.search(text)) for text in chunks]
    projects = {match[1].strip() for _, match in tagged if match}
    specific = projects - {"通用接待"}
    specific.update(name for name in KNOWN_GAMES if any(name in text for text in chunks))
    if not specific:
        return chunks, False
    names = set(KNOWN_GAMES) | specific

    def mentioned(text):
        return {name for name in names if name in text}

    selected = mentioned(question)
    if not selected:
        for turn in reversed(history or []):
            if turn.get("role") == "customer":
                selected = mentioned(turn.get("text", ""))
                if selected:
                    break
    if len(selected) != 1:
        return [], True
    project = next(iter(selected))
    return [text for text, match in tagged
            if (match and match[1].strip() in (project, "通用接待"))
            or (not match and mentioned(text) == {project})
            or text.startswith("[当前时间]")], False
