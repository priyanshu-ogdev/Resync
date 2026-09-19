"""Unit tests for llm/generator.py's draft_patch, against httpx.MockTransport (no real model needed — see
that module's docstring)."""

from __future__ import annotations

import httpx
import pytest

from resync.llm.generator import GeneratorError, draft_patch


def test_successful_draft_extracts_content_from_the_real_openai_response_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "  fixed code here  "}}]})

    result = draft_patch(
        "x -> y", "old code", "http://fake", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert result.content == "fixed code here"  # stripped


def test_low_temperature_and_prompt_content_are_sent_to_the_real_endpoint() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    draft_patch(
        "use_auth_token -> token",
        "def f(): pass",
        "http://fake",
        temperature=0.1,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert captured["body"]["temperature"] == 0.1
    assert "use_auth_token -> token" in captured["body"]["messages"][1]["content"]
    assert "def f(): pass" in captured["body"]["messages"][1]["content"]


def test_unreachable_model_raises_generator_error_not_a_raw_httpx_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(GeneratorError, match="could not reach"):
        draft_patch("x -> y", "old code", "http://fake", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_malformed_response_shape_raises_generator_error_not_a_raw_keyerror() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    with pytest.raises(GeneratorError, match="expected OpenAI chat-completions shape"):
        draft_patch("x -> y", "old code", "http://fake", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_unable_to_draft_is_returned_as_a_normal_result_not_raised() -> None:
    """A legitimate model response declining to guess must not be treated as an error — the caller (the
    critic, or a human) needs to see it, not have it swallowed into an exception."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "UNABLE_TO_DRAFT"}}]})

    result = draft_patch(
        "x -> y", "old code", "http://fake", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert result.content == "UNABLE_TO_DRAFT"
