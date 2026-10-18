from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.llm import LLMResult, complete, parse_json
from app.prompts import load_prompt


@dataclass
class StepRecord:
    agent: str
    step: str
    prompt_version: str
    model_input: dict[str, Any]
    model_output: Any
    validation: dict[str, Any]


def run_prompt(name: str, user: str, *, max_tokens: int = 4000) -> tuple[str, Any, LLMResult]:
    version, system = load_prompt(name)
    result = complete(system, user, max_tokens=max_tokens)
    return version, parse_json(result.text), result
