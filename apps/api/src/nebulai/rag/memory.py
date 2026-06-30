import asyncio
import json
import urllib.request
from typing import Any

from nebulai.core.config import settings


def build_session_summary(existing_summary: str | None, messages: list[dict[str, Any]], max_chars: int = 1200) -> str:
    turns = [
        f"{message['role']}: {_compact_text(str(message['content']))}"
        for message in messages[-12:]
        if message.get("role") in {"user", "assistant"}
    ]
    prefix = f"既有摘要：{_compact_text(existing_summary)}\n" if existing_summary else ""
    summary = prefix + "最近对话：\n" + "\n".join(turns)
    return summary[-max_chars:]


async def build_session_summary_with_llm(
    existing_summary: str | None,
    messages: list[dict[str, Any]],
    max_chars: int = 1200,
) -> str:
    fallback = build_session_summary(existing_summary, messages, max_chars=max_chars)
    if not _remote_llm_enabled():
        return fallback

    try:
        summary = await asyncio.to_thread(_remote_summary, existing_summary, messages, max_chars)
    except Exception:
        return fallback
    return summary[-max_chars:] if summary else fallback


def _compact_text(value: str | None, max_chars: int = 280) -> str:
    text = " ".join((value or "").split())
    return text[:max_chars]


def _remote_llm_enabled() -> bool:
    return settings.llm_provider in {"openai", "openai-compatible"} and bool(settings.effective_llm_api_key)


def _remote_summary(existing_summary: str | None, messages: list[dict[str, Any]], max_chars: int) -> str:
    transcript = "\n".join(
        f"{message.get('role')}: {_compact_text(str(message.get('content')), max_chars=900)}"
        for message in messages[-16:]
        if message.get("role") in {"user", "assistant"}
    )
    payload = {
        "model": settings.llm_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是会话记忆摘要器。只基于对话内容输出中文摘要，不要编造。"
                    "保留：用户目标、已确认事实、关键约束、待办、最近问题。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"既有摘要：\n{existing_summary or '无'}\n\n"
                    f"最近对话：\n{transcript}\n\n"
                    f"请输出不超过 {max_chars} 个字符的结构化摘要。"
                ),
            },
        ],
        "stream": False,
        "temperature": 0,
    }
    request = urllib.request.Request(
        url=f"{settings.llm_base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.effective_llm_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=settings.llm_timeout_seconds) as response:
        body = json.loads(response.read().decode("utf-8"))
    return str(body["choices"][0]["message"]["content"]).strip()
