from __future__ import annotations

from pathlib import Path

from app.config import PROMPT_VERSION, PROMPTS_DIR


def load_prompt(name: str, version: str | None = None) -> tuple[str, str]:
    used = version or PROMPT_VERSION
    path = PROMPTS_DIR / used / f"{name}.txt"
    if not path.is_file():
        raise FileNotFoundError(f"Missing prompt file {path}")
    return used, path.read_text(encoding="utf-8").strip()


def list_prompt_files(version: str | None = None) -> list[Path]:
    used = version or PROMPT_VERSION
    folder = PROMPTS_DIR / used
    return sorted(folder.glob("*.txt"))
