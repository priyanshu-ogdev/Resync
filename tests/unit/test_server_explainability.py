"""Unit tests for server explainability, decomposed trust breakdown, options, and new MCP tools."""

from __future__ import annotations

from pathlib import Path

import httpx

from resync.knowledge.schema import KnowledgeRecord, RecordSource, RuleType
from resync.server.patch_verification import PatchVerificationOutcome, verify_patch_equivalence
from resync.server.tools import (
    VerificationOutcome,
    _build_trust_breakdown,
    _format_markdown_card,
    _make_package_options,
    _make_symbol_options,
    clear_package_cache,
    explain_change,
    get_compatibility_report,
    verify_package,
)


def test_make_package_options_generates_remediation_actions() -> None:
    ok_opts = _make_package_options("requests", VerificationOutcome.OK, "2.31.0")
    assert any(o["action"] == "Sync" for o in ok_opts)

    advisory_opts = _make_package_options("vulnerable-pkg", VerificationOutcome.ADVISORY_FLAGGED)
    actions = {o["action"] for o in advisory_opts}
    assert {"Shift", "Pin", "Exception"}.issubset(actions)


def test_make_symbol_options_generates_remediation_actions() -> None:
    opts = _make_symbol_options("transformers.pipeline", VerificationOutcome.SYMBOL_DEPRECATED, "token")
    actions = {o["action"] for o in opts}
    assert {"Sync", "Shift", "Pin", "Exception"}.issubset(actions)
    sync_opt = next(o for o in opts if o["action"] == "Sync")
    assert "token" in sync_opt["description"]


def test_build_trust_breakdown_structure() -> None:
    tb_ok = _build_trust_breakdown(VerificationOutcome.OK)
    assert tb_ok["overall"] == 1.0
    assert tb_ok["rule_match"] == 1.0
    assert tb_ok["test_suite"] == 1.0
    assert tb_ok["differential_equivalence"] == 1.0
    assert tb_ok["source_citation"] == 1.0
    assert tb_ok["verdict"] == "Safe / Clean"

    record = KnowledgeRecord(
        package="testpkg",
        ecosystem="pypi",
        old_symbol="testpkg.foo",
        new_symbol="testpkg.bar",
        from_version="1.0.0",
        to_version="2.0.0",
        rule_type=RuleType.RENAME,
        source=RecordSource.CHANGELOG_EXTRACT,
        confidence=0.95,
    )
    tb_rec = _build_trust_breakdown(VerificationOutcome.SYMBOL_DEPRECATED, [record])
    assert 0.0 <= tb_rec["overall"] <= 1.0
    assert "verdict" in tb_rec


def test_format_markdown_card_rendering() -> None:
    md = _format_markdown_card(
        title="Package: requests",
        outcome=VerificationOutcome.OK,
        detail="Package verified on PyPI",
        explanation="Safe dependency with 0 advisories.",
        options=[{"action": "Sync", "title": "Add", "description": "Add package", "command": "uv add requests"}],
        trust_breakdown={
            "overall": 1.0,
            "verdict": "Safe",
            "rule_match": 1.0,
            "test_suite": 1.0,
            "differential_equivalence": 1.0,
            "source_citation": 1.0,
        },
    )
    assert "### 🟢 `VERIFIED` Package: requests" in md
    assert "**Trust Score**: `1.00 / 1.00`" in md
    assert "**[Sync]** **Add**" in md


def test_verify_package_enriches_result(tmp_path: Path) -> None:
    clear_package_cache()
    mock_transport = httpx.MockTransport(
        lambda request: (
            httpx.Response(200, json={"info": {"version": "2.31.0"}})
            if "pypi.org" in str(request.url)
            else httpx.Response(200, json={"vulns": []})
        )
    )
    client = httpx.Client(transport=mock_transport)
    result = verify_package("requests", "pypi", tmp_path, client=client)
    assert result.outcome == VerificationOutcome.OK
    assert result.explanation is not None
    assert len(result.options) > 0
    assert result.trust_breakdown is not None
    assert result.markdown_display is not None
    assert "🟢 `VERIFIED`" in result.markdown_display


def test_explain_change_and_compatibility_report(tmp_path: Path) -> None:
    clear_package_cache()
    mock_transport = httpx.MockTransport(
        lambda request: (
            httpx.Response(200, json={"info": {"version": "1.0.0"}})
            if "pypi.org" in str(request.url)
            else httpx.Response(200, json={"vulns": []})
        )
    )
    client = httpx.Client(transport=mock_transport)
    # Patch httpx.Client default
    orig_client = httpx.Client

    def _client_factory(*args: object, **kwargs: object) -> httpx.Client:
        return client

    httpx.Client = _client_factory  # type: ignore[misc]
    try:
        data = explain_change("requests", tmp_path)
        assert data["target"] == "requests"
        assert data["kind"] == "package"
        assert "explanation" in data
        assert "trust_breakdown" in data
        assert "options" in data

        report = get_compatibility_report(["requests"], tmp_path)
        assert report["summary"]["total"] == 1
        assert "markdown_display" in report
    finally:
        httpx.Client = orig_client  # type: ignore[misc]
        clear_package_cache()


def test_verify_patch_equivalence_enriches_result(tmp_path: Path) -> None:
    old_source = "foo(x=1)"
    new_source = "def syntax_error("
    res = verify_patch_equivalence("any.func", old_source, new_source, "1.0.0", tmp_path)
    assert res.outcome == PatchVerificationOutcome.INVALID_SYNTAX
    assert res.explanation is not None
    assert res.diff_preview is not None
    assert res.trust_breakdown is not None
    assert res.markdown_display is not None
    assert "🔴 `SYNTAX ERROR`" in res.markdown_display
