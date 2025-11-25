import importlib
import os

import pytest

from utils import common_utils


class DummyMessage:
    def __init__(self, content: str):
        self.content = content


@pytest.mark.parametrize(
    "text,expected",
    [
        ("9876543210", True),
        ("432198", True),
        ("Yes", True),
        ("Random sentence", False),
    ],
)
def test_looks_like_verification_data(text, expected):
    assert common_utils._looks_like_verification_data(text) is expected


def test_is_general_platform_query_detects_platform_question():
    assert common_utils._is_general_platform_query("What is Karmayogi platform") is True
    assert common_utils._is_general_platform_query("Tell me about weather") is False


def test_load_llm_urls_reads_env(monkeypatch):
    monkeypatch.setenv(
        "LOCAL_LLM_URLS",
        " http://localhost:9000/v1/chat , https://api.example.com/v1/chat , not-a-url ",
    )
    importlib.reload(common_utils)
    urls = common_utils.load_llm_urls()
    assert urls == [
        "http://localhost:9000/v1/chat",
        "https://api.example.com/v1/chat",
    ]


def test_load_llm_urls_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_URLS", raising=False)
    importlib.reload(common_utils)
    urls = common_utils.load_llm_urls()
    assert urls == ["http://localhost:11435/v1/chat/completions"]


@pytest.mark.asyncio
async def test_rephrase_query_skips_general_and_verification_data():
    general = await common_utils.rephrase_query_with_history("What is Karma Points", [])
    assert general == "What is Karma Points"

    otp = await common_utils.rephrase_query_with_history("1234", [])
    assert otp == "1234"


@pytest.mark.asyncio
async def test_rephrase_query_handles_workflow_interruptions():
    chat_history = [
        DummyMessage("Please enter the OTP sent to your mobile"),
        DummyMessage("Awaiting verification"),
    ]
    query = "What is Karmayogi Bharat?"
    result = await common_utils.rephrase_query_with_history(query, chat_history)
    assert result == query
