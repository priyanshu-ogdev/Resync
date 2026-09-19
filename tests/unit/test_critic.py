"""Unit tests for verification/critic.py's LlamaServerCritic."""

from __future__ import annotations

import httpx
import pytest

from resync.llm.generator import GeneratedPatch
from resync.verification.critic import LlamaServerCritic, VerificationContext


def _context() -> VerificationContext:
    return VerificationContext(old_source="old", new_source="new", knowledge_record_summary="x -> y")


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_approval_with_real_concerns_is_accepted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "CONCERNS: checked A, checked B\nVERDICT: APPROVE\nREASON:"}}]},
        )

    critic = LlamaServerCritic("http://fake", client=_client(handler))
    verdict = critic.review(GeneratedPatch(content="fixed", raw_response=""), _context())
    assert verdict.approved is True
    assert verdict.concerns_considered == ["checked A", "checked B"]


def test_approval_with_no_concerns_is_rejected_as_a_rubber_stamp() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "VERDICT: APPROVE\nREASON:"}}]})

    critic = LlamaServerCritic("http://fake", client=_client(handler))
    verdict = critic.review(GeneratedPatch(content="fixed", raw_response=""), _context())
    assert verdict.approved is False
    assert "rubber-stamp" in verdict.rejection_reason


def test_explicit_reject_is_honored_with_its_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "CONCERNS: checked call sites\nVERDICT: REJECT\nREASON: misses one call site"
                        }
                    }
                ]
            },
        )

    critic = LlamaServerCritic("http://fake", client=_client(handler))
    verdict = critic.review(GeneratedPatch(content="fixed", raw_response=""), _context())
    assert verdict.approved is False
    assert verdict.rejection_reason == "misses one call site"


def test_unparseable_response_is_rejected_not_guessed_at() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "I think this looks fine!"}}]})

    critic = LlamaServerCritic("http://fake", client=_client(handler))
    verdict = critic.review(GeneratedPatch(content="fixed", raw_response=""), _context())
    assert verdict.approved is False


def test_unreachable_model_fails_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    critic = LlamaServerCritic("http://fake", client=_client(handler))
    verdict = critic.review(GeneratedPatch(content="fixed", raw_response=""), _context())
    assert verdict.approved is False


def test_unable_to_draft_short_circuits_without_calling_the_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call the model for an UNABLE_TO_DRAFT patch")

    critic = LlamaServerCritic("http://fake", client=_client(handler))
    verdict = critic.review(GeneratedPatch(content="UNABLE_TO_DRAFT", raw_response=""), _context())
    assert verdict.approved is False


def test_patch_without_content_attribute_raises_type_error() -> None:
    critic = LlamaServerCritic("http://fake")
    with pytest.raises(TypeError, match="content"):
        critic.review(object(), _context())
