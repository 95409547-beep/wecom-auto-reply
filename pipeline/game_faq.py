"""Read the project FAQ text format shared with ima."""

from rag.kb_tools import make_faq

TITLE_SUFFIX = "｜客服知识库"
FILE_SUFFIX = " 客服问答.txt"


def parse_game_faq(text: str) -> list[str] | None:
    lines = text.strip().splitlines()
    if not lines or not lines[0].endswith(TITLE_SUFFIX):
        return None
    project = lines[0].removesuffix(TITLE_SUFFIX).strip()
    body = [line.strip() for line in lines[1:] if line.strip()]
    if not project or not body or len(body) % 2:
        raise ValueError("游戏问答文件需要逐对填写「问：」和「答：」")

    chunks = []
    questions = set()
    for question_line, answer_line in zip(body[::2], body[1::2]):
        question = question_line.removeprefix("问：").strip()
        answer = answer_line.removeprefix("答：").strip()
        if (not question_line.startswith("问：") or not answer_line.startswith("答：")
                or not question or not answer or question in questions):
            raise ValueError(f"{project}的问答为空、重复或缺少「问：」「答：」")
        questions.add(question)
        chunks.append(make_faq(question, f"{answer}\n适用项目：{project}。"))
    return chunks
