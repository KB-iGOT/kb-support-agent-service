"""Centralized prompt loading and rendering utilities."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Any, Dict

import yaml

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class PromptConfigError(RuntimeError):
    """Raised when prompt configuration is missing or invalid."""


@lru_cache(maxsize=None)
def _load_prompt_file(prompt_name: str) -> Dict[str, str]:
    """Load and cache a prompt YAML file."""
    prompt_path = PROMPTS_DIR / f"{prompt_name}.yaml"
    if not prompt_path.exists():
        raise PromptConfigError(f"Prompt file not found: {prompt_path}")

    with prompt_path.open("r", encoding="utf-8") as file_obj:
        data = yaml.safe_load(file_obj) or {}

    if not isinstance(data, dict):
        raise PromptConfigError(f"Prompt file must contain a mapping: {prompt_path}")

    return data


def get_prompt(prompt_name: str, key: str, **context: Any) -> str:
    """Render a prompt by name/key with optional template context."""
    prompts = _load_prompt_file(prompt_name)

    if key not in prompts:
        raise PromptConfigError(f"Prompt key '{key}' not found in {prompt_name}.yaml")

    raw_prompt = prompts[key]
    if not isinstance(raw_prompt, str):
        raise PromptConfigError(
            f"Prompt '{key}' in {prompt_name}.yaml must be a string, got {type(raw_prompt)}"
        )

    template = Template(raw_prompt)
    return template.substitute(**context) if context else raw_prompt
