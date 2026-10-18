from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.config import MODEL_NAME, anthropic_api_key, redact
from app.db import log_llm_call


class BillingError(RuntimeError):
    """Anthropic account cannot run the request (credits/auth)."""


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


def is_billing_error(message: str) -> bool:
    lowered = message.lower()
    return any(
        phrase in lowered
        for phrase in (
            "credit balance is too low",
            "invalid api key",
            "authentication",
            "permission",
        )
    )


def _extract_text(response: Any) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()


def complete(
    conn,
    purpose: str,
    messages: list[dict],
    *,
    system: str | None = None,
    max_tokens: int = 800,
    model: str | None = None,
) -> LLMResult:
    key = anthropic_api_key()
    if not key:
        raise BillingError("ANTHROPIC_API_KEY is not set")

    import anthropic

    used_model = model or MODEL_NAME
    started = time.perf_counter()
    error = None
    input_tokens = 0
    output_tokens = 0
    try:
        client = anthropic.Anthropic(api_key=key)
        thinking: dict[str, str]
        if "sonnet-5-5" in used_model or "sonnet-5.5" in used_model:
            thinking = {"type": "between_tools"}
        else:
            thinking = {"type": "disabled"}
        kwargs: dict[str, Any] = {
            "model": used_model,
            "max_tokens": max_tokens,
            "thinking": thinking,
            "output_config": {"effort": "low"},
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        message = client.messages.create(**kwargs)
        usage = getattr(message, "usage", None)
        if usage is not None:
            input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
            output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        text = _extract_text(message)
        if not text:
            raise RuntimeError("empty model response")
        return LLMResult(
            text=text,
            model=used_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:
        error = redact(f"{type(exc).__name__}: {exc}")
        if is_billing_error(error):
            raise BillingError(
                "Anthropic credit balance is too low or the API key cannot be used."
            ) from exc
        raise RuntimeError(error) from exc
    finally:
        log_llm_call(
            conn,
            purpose,
            used_model,
            int((time.perf_counter() - started) * 1000),
            input_tokens,
            output_tokens,
            error,
        )
