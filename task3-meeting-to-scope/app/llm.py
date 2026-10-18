from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

from app.config import MODEL_NAME, anthropic_api_key, redact


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


def complete(system: str, user: str, *, max_tokens: int = 4000, model: str | None = None) -> LLMResult:
    key = anthropic_api_key()
    if not key:
        raise LLMError("ANTHROPIC_API_KEY is not set")
    import anthropic

    used = model or MODEL_NAME
    client = anthropic.Anthropic(api_key=key)
    thinking: dict[str, str]
    if "sonnet-5-5" in used or "sonnet-5.5" in used:
        thinking = {"type": "between_tools"}
    else:
        thinking = {"type": "disabled"}
    started = time.perf_counter()
    try:
        message = client.messages.create(
            model=used,
            max_tokens=max_tokens,
            thinking=thinking,
            output_config={"effort": "low"},
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except Exception as exc:
        raise LLMError(redact(f"{type(exc).__name__}: {exc}")) from exc
    parts: list[str] = []
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    text = "\n".join(parts).strip()
    if not text:
        raise LLMError("empty model response")
    usage = getattr(message, "usage", None)
    return LLMResult(
        text=text,
        model=used,
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0) if usage else 0,
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0) if usage else 0,
    )


def parse_json(text: str) -> Any:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        cleaned = fence.group(1).strip()
    start_obj = cleaned.find("{")
    start_arr = cleaned.find("[")
    if start_obj < 0 and start_arr < 0:
        raise LLMError("model response did not contain JSON")
    if start_arr >= 0 and (start_obj < 0 or start_arr < start_obj):
        start = start_arr
        end = cleaned.rfind("]")
    else:
        start = start_obj
        end = cleaned.rfind("}")
    if end <= start:
        raise LLMError("model response contained incomplete JSON")
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"model JSON could not be parsed: {exc}") from exc
