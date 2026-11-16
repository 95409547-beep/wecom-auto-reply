# rag/llm_client.py
"""OpenAI 兼容的 LLM 接口封装 —— 不绑定 DeepSeek。

支持任意 OpenAI 兼容端点（DeepSeek 官方 / OpenRouter / 通义兼容模式 / Kimi /
硅基流动 / 自建网关…），三项都可配：

    LLM_API_KEY    密钥
    LLM_BASE_URL   接口地址（填到 /v1 为止，不含 /chat/completions）
    LLM_MODEL      模型名 —— **必须可配**：各家模型名不一样，
                   写死 "deepseek-chat" 的话换个地址就会 400

向后兼容：没设 ``LLM_*`` 时回落到旧的 ``DEEPSEEK_API_KEY`` / ``DEEPSEEK_BASE_URL``，
模型名回落到 ``deepseek-chat`` —— 老配置不改也能继续跑。

设置面板用到的接口：
    PRESETS            预设列表（下拉框）
    describe_config()  一行配置摘要（不泄露密钥）
    async ping()       连通性测试，把真实错误原因带回来
    async list_models() 拉取当前接口提供的模型 ID
"""

import os
import asyncio
import logging
from typing import Optional, Tuple

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

logger = logging.getLogger(__name__)

MAX_RETRIES = 2
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"

# 预设：(显示名, base_url, 默认模型)。设置面板按接口返回的列表选模型。
PRESETS = [
    ("DeepSeek 官方", "https://api.deepseek.com/v1", "deepseek-chat"),
    ("OpenRouter", "https://openrouter.ai/api/v1", "deepseek/deepseek-chat"),
    ("通义千问（兼容模式）", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    ("Kimi（月之暗面）", "https://api.moonshot.cn/v1", "moonshot-v1-8k"),
    ("硅基流动", "https://api.siliconflow.cn/v1", "deepseek-ai/DeepSeek-V3"),
    ("自定义接口", "", ""),
]

_client: Optional[AsyncOpenAI] = None
_client_sig: Optional[Tuple[str, str]] = None


def _raw_key() -> str:
    return (os.environ.get("LLM_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY") or "").strip()


def _is_placeholder(value: str) -> bool:
    """密钥是不是 .env.example 里的示例值（``sk-your-deepseek-key``）？

    懒导入，避免启动期模块互相牵。
    """
    try:
        from config.settings_store import looks_like_placeholder
        return looks_like_placeholder(value)
    except Exception:
        low = (value or "").strip().lower()
        return (not low) or ("your" in low) or low.startswith("placeholder")


def resolve_config() -> Tuple[str, str, str]:
    """返回 (api_key, base_url, model)。优先 LLM_*，回落 DEEPSEEK_*。

    ★ **示例占位符一律当作"没填"**：第一次启动时 .env 是 .env.example 复制来的，
    里面 ``DEEPSEEK_API_KEY=sk-your-deepseek-key`` 看着像密钥，拿它去调接口只会拿 401。
    当成没填 → 界面上密钥框留空、点「开始」会被拦下（提示去「设置」填真 Key）。
    """
    key = _raw_key()
    if _is_placeholder(key):
        key = ""
    base = (os.environ.get("LLM_BASE_URL")
            or os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL)
    model = os.environ.get("LLM_MODEL") or DEFAULT_MODEL
    return key.strip(), base.strip(), model.strip()


def describe_config() -> str:
    """给人看的一行配置摘要（不泄露密钥）。"""
    key, base, model = resolve_config()
    tail = f"…{key[-4:]}" if len(key) > 8 else ("已设置" if key else "未设置")
    return f"模型={model}  地址={base}  密钥={tail}"


def get_client() -> AsyncOpenAI:
    global _client, _client_sig
    key, base, _ = resolve_config()
    if not key:
        raise RuntimeError(
            "还没填 LLM 接口密钥。请点界面上的「设置」填入，"
            "或手工在 .env 里加一行 LLM_API_KEY=你的密钥"
        )
    sig = (key, base)
    if _client is None or _client_sig != sig:
        # 密钥/地址变了必须重建 client，否则改完设置还在用旧连接
        _client = AsyncOpenAI(api_key=key, base_url=base, timeout=60.0)
        _client_sig = sig
    return _client


def reset_client():
    """丢弃缓存的 client（设置保存后调用，配合 load_dotenv(override=True)）。"""
    global _client, _client_sig
    _client = None
    _client_sig = None


async def list_models(base_url: str, api_key: str) -> list[str]:
    """Fetch IDs with the draft credentials, independently of the active client."""
    if _is_placeholder(api_key):
        raise ValueError("请填写有效的接口密钥。")
    try:
        async with AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=12.0,
                               max_retries=0) as client:
            page = await client.models.list()
    except APITimeoutError:
        raise RuntimeError("拉取超时，请检查网络后重试。") from None
    except APIConnectionError:
        raise RuntimeError("无法连接接口，请检查接口地址和网络。") from None
    except APIStatusError as exc:
        status = exc.status_code
        if status in (401, 403):
            detail = "密钥无效，或没有查看模型列表的权限。"
        elif status in (404, 405, 501):
            detail = "找不到模型列表，请检查接口地址和服务商是否支持 /models。"
        elif status == 429:
            detail = "请求过于频繁，请稍后重试。"
        else:
            detail = f"接口返回 HTTP {status}，请稍后重试。"
        raise RuntimeError(detail) from None
    except Exception:
        raise RuntimeError("未能获取有效的模型列表，请检查接口地址。") from None

    ids = {
        model.id.strip() for model in (getattr(page, "data", None) or [])
        if isinstance(getattr(model, "id", None), str) and model.id.strip()
    }
    if not ids:
        raise RuntimeError("接口没有返回可选模型，请检查账号的模型权限。")
    return sorted(ids)


async def chat(messages: list[dict], temperature: float = 0.7,
               max_tokens: int = 1024, model: str = None) -> str:
    """发一轮 chat completion。

    Returns:
        回复文本。
    Raises:
        RuntimeError: 重试用尽，或遇到不可重试的 4xx。
    """
    client = get_client()
    _, _, cfg_model = resolve_config()
    use_model = model or cfg_model
    last_error = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = await client.chat.completions.create(
                model=use_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            last_error = e
            status = getattr(e, 'status_code', None)
            if status is not None and 400 <= status < 500 and status != 429:
                logger.error(f"LLM 接口不可重试错误 {status}（模型={use_model}）: {e}")
                raise RuntimeError(f"LLM API error {status}（模型={use_model}）: {e}") from e
            logger.warning(
                f"LLM 尝试 {attempt + 1}/{MAX_RETRIES + 1} 失败（模型={use_model}）: {e}"
            )
            if attempt < MAX_RETRIES:
                await asyncio.sleep(1.0 * (attempt + 1))

    raise RuntimeError(
        f"LLM 接口连续 {MAX_RETRIES + 1} 次失败（模型={use_model}）: {last_error}"
    )


async def ping(timeout: float = 25.0, *,
               settings: Optional[Tuple[str, str, str]] = None) -> Tuple[bool, str]:
    """连通性测试 → (是否通, 人话说明)。设置面板的「测试连接」按钮用它。

    用户填完地址/密钥/模型名当场就知道对不对，不用等客户来消息才发现。
    """
    key, base, model = settings if settings is not None else resolve_config()
    if _is_placeholder(key):
        raw = key if settings is not None else _raw_key()
        if raw:
            # 最常见的一种：第一次启动时 .env 是 .env.example 复制来的，
            # 里面那个示例值看着像密钥，用户以为已经配好了
            return False, "现在填的是示例里的占位符，请换成你自己的 API Key。"
        return False, "还没填密钥"

    async def request():
        messages = [{"role": "user", "content": "请只回复两个字：收到"}]
        if settings is None:
            return await chat(messages, temperature=0.0, max_tokens=16)
        async with AsyncOpenAI(api_key=key, base_url=base, timeout=timeout,
                               max_retries=0) as client:
            response = await client.chat.completions.create(
                model=model, messages=messages, temperature=0.0, max_tokens=16)
            return response.choices[0].message.content or ""

    try:
        text = await asyncio.wait_for(request(), timeout=timeout)
    except (asyncio.TimeoutError, APITimeoutError):
        return False, f"超时（{timeout:.0f} 秒没回应）—— 检查网络或代理"
    except Exception as e:
        msg = str(e)
        hint = ""
        low = msg.lower()
        if "401" in msg or "invalid_api_key" in low or "unauthorized" in low:
            hint = "（密钥不对）"
        elif "404" in msg or ("model" in low and "not" in low):
            hint = f"（模型名 '{model}' 可能不对，换一个再试）"
        elif "connection" in low or "getaddrinfo" in low or "ssl" in low:
            hint = "（地址不通：检查 base_url，注意要填到 /v1 为止）"
        if settings is not None:
            status = getattr(e, "status_code", None)
            return False, f"测试失败{f'（HTTP {status}）' if status else ''}{hint or '，请检查接口配置。'}"
        return False, f"失败：{msg[:200]}{hint}"
    if not text.strip():
        return False, "通了但返回空内容（模型名或服务端异常）"
    return True, f"通了：模型 {model} 回复 {text.strip()[:20]!r}"
