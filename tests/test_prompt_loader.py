import pytest

from utils.prompt_loader import PromptConfigError, get_prompt


def test_get_prompt_renders_classifier_instruction_with_context():
    history_snippet = "Recent history placeholder"

    prompt = get_prompt(
        "custom_agent_router",
        "classifier_instruction",
        history_context=history_snippet,
    )

    assert history_snippet in prompt
    assert "USER_PROFILE_INFO" in prompt


def test_get_prompt_missing_key_raises_error():
    with pytest.raises(PromptConfigError):
        get_prompt("custom_agent_router", "does_not_exist")


def test_get_prompt_missing_file_raises_error():
    with pytest.raises(PromptConfigError):
        get_prompt("nonexistent_prompt_file", "any_key")
