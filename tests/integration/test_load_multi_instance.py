from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from resync.server.app import build_server


@pytest.fixture
def pinned_repo(tmp_path: Path) -> Path:
    (tmp_path / "resync.toml").write_text('[[pin]]\npackage = "fastapi"\nmax_version = "0.100.0"\nreason = "frozen"\n')
    return tmp_path


def test_stateless_server_handles_high_concurrency_without_bleeding(pinned_repo: Path) -> None:
    """
    Phase 8 exit criteria: Prove the stateless core can handle high query concurrency
    without bleeding state or breaking down.

    We simulate 100 concurrent agent sessions blasting the server with queries simultaneously.
    """
    server = build_server(pinned_repo)

    concurrency_level = 100

    async def simulate_agent_query(agent_id: int) -> bool:
        try:
            # We use the pinned package to avoid network calls, isolating the test to pure server throughput
            result = await server.call_tool("verify_package", {"package": "fastapi", "ecosystem": "pypi"})
            if result.is_error:
                return False
            payload = "".join(getattr(block, "text", "") for block in result.content)
            return "pinned" in payload.lower()
        except Exception:
            return False

    async def runner() -> tuple[list[bool], float]:
        start_time = time.monotonic()
        results = await asyncio.gather(*(simulate_agent_query(i) for i in range(concurrency_level)))
        duration = time.monotonic() - start_time
        return results, duration

    results, duration = asyncio.run(runner())

    # Assert all requests succeeded and returned the correct stateless answer
    assert all(results), "Not all concurrent requests succeeded"
    assert len(results) == concurrency_level

    # Throughput sanity check (should be well under 1 second for 100 local pinned calls)
    assert duration < 5.0, f"Throughput too low, took {duration}s for {concurrency_level} requests"
