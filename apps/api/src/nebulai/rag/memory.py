from typing import Any


def build_session_summary(existing_summary: str | None, messages: list[dict[str, Any]], max_chars: int = 1200) -> str:
    turns = [
        f"{message['role']}: {_compact_text(str(message['content']))}"
        for message in messages[-12:]
        if message.get("role") in {"user", "assistant"}
    ]
    prefix = f"既有摘要：{_compact_text(existing_summary)}\n" if existing_summary else ""
    summary = prefix + "最近对话：\n" + "\n".join(turns)
    return summary[-max_chars:]


def _compact_text(value: str | None, max_chars: int = 280) -> str:
    text = " ".join((value or "").split())
    return text[:max_chars]
