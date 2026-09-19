"""Integration coverage for knowledge/extract_api_diff.extract() against real PyPI package versions —
replaces an earlier version of this test file written against a since-removed `griffe.load_git`-based
implementation (see extract_api_diff.py's own module docstring for the full account of why that
implementation was replaced: it needed a git checkout of the *calling process's cwd*, an assumption this
test file previously worked around with a throwaway clone rather than reflecting that `extract()` itself no
longer needs git at all).

Skips (importorskip), rather than mocking griffe, when griffe isn't installed — per this project's own
"don't fake what wasn't actually run" stance. A mocked-out griffe would only prove this module calls
griffe's API the way we assume it works, not that it actually does.

Real network required (real `pip download` against real PyPI) — marked `@pytest.mark.network`, per
docs/testing-strategy.md's convention for tests that need it.
"""

from __future__ import annotations

import shutil

import pytest

griffe = pytest.importorskip("griffe")

from resync.adapters.python.extract_api_diff import extract  # noqa: E402
from resync.knowledge.schema import RuleType  # noqa: E402

pytestmark = pytest.mark.network


def test_extract_against_the_same_version_twice_finds_nothing() -> None:
    """Diffing a real package against itself is the simplest possible "no breaking changes" case — proves
    extract()'s full pipeline (pip download, extraction, griffe.load x2, find_breaking_changes, and this
    module's own correlation/reorder logic) runs end-to-end without erroring, before asserting anything
    about real breaking-change content in the next test."""
    if shutil.which("pip") is None:
        pytest.skip("pip not on PATH")
    records = extract(package="six", old_ref="1.16.0", new_ref="1.16.0", from_version="1.16.0", to_version="1.16.0")
    assert records == []


def test_extract_against_a_real_known_breaking_change_pair() -> None:
    """peft 0.10.0 -> 0.12.0 is a real, live-confirmed case (found while building this module, not a
    synthetic fixture): `peft.utils.integrations.gather_params_ctx`'s `module` parameter was renamed to
    `fwd_module`. `--no-deps` means this needs no `torch` (or any of peft's other real declared
    dependencies) installed anywhere — see extract_api_diff.py's module docstring for the full, corrected
    account of why that's true and an earlier version of this docstring's claim about it was wrong."""
    if shutil.which("pip") is None:
        pytest.skip("pip not on PATH")
    records = extract(package="peft", old_ref="0.10.0", new_ref="0.12.0", from_version="0.10.0", to_version="0.12.0")

    assert len(records) > 0
    renames = [r for r in records if r.rule_type == RuleType.RENAME]
    matching = [
        r
        for r in renames
        if r.old_symbol.endswith("gather_params_ctx") and r.parameter == "module" and r.new_parameter == "fwd_module"
    ]
    assert matching, f"expected the known module->fwd_module rename; got renames: {renames}"

    behavior_changes = [r for r in records if r.rule_type == RuleType.BEHAVIOR_CHANGE]
    assert behavior_changes, (
        "expected at least one BEHAVIOR_CHANGE record — this is the exact case the _DIRECT_RULE_TYPE "
        "key-format bug silently zeroed out entirely; a regression here would mean that bug is back"
    )


def test_extract_never_touches_torch() -> None:
    """`peft` genuinely declares `torch>=1.13.0` as a real, required dependency (confirmed against PyPI's
    own metadata) — this test exists specifically to catch a regression back to an implementation that
    performs a full `pip install`/`griffe.load_pypi` (which would pull torch in), by asserting `torch` is
    never importable in this process after calling extract() against peft."""
    if shutil.which("pip") is None:
        pytest.skip("pip not on PATH")
    import sys

    assert "torch" not in sys.modules, "torch was already imported before this test ran — test is unreliable"
    extract(package="peft", old_ref="0.10.0", new_ref="0.12.0", from_version="0.10.0", to_version="0.12.0")
    assert "torch" not in sys.modules
