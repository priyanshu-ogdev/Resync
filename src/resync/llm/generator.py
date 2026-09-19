"""Phase 6: drafts a semantic-tier patch using the local model, over `llama-server`'s OpenAI-compatible
`/v1/chat/completions` endpoint — the "generator" half of ADR 0002's Summary/Control/Code-inspired
generator/critic split (`verification/critic.py` is the other half).

This is the path taken when `patch/taxonomy.classify()` returns `PatchStrategy.SEMANTIC` — a change
`ast_grep_runner.py` cannot express mechanically (MERGE, SPLIT, RETURN_SHAPE_CHANGE, BEHAVIOR_CHANGE, or a
low-confidence RENAME/REORDER). The model drafts a rewrite of the specific call site; it never gets to
decide whether that draft is trustworthy — that judgment is `Critic.review()`'s job, deliberately kept
separate, per ADR 0002's whole reason for the two-pass split existing at all.

Request/response shape verified against llama-server's real, current documentation before writing this
(mvysny.github.io/llama-server-endpoints, docs.clore.ai/guides/language-models/llamacpp-server) — standard
OpenAI chat-completions request/response fields (`messages`, `choices[0].message.content`), not a
llama.cpp-specific extension.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

_DEFAULT_TIMEOUT_SECONDS = 120.0

_SYSTEM_PROMPT = """You are a precise code-migration assistant. You will be given:
- A description of a known API change (old symbol/parameter -> new symbol/parameter, or a behavior change).
- A single source file's contents that needs updating for this change.

Rewrite ONLY what the change requires. Do not reformat unrelated code, rename unrelated variables, or "fix"
unrelated issues. Output ONLY the complete corrected file contents — no explanation, no markdown code fences.
If you cannot confidently determine the correct rewrite, output the single line: UNABLE_TO_DRAFT
"""


class GeneratorError(RuntimeError):
    """The model could not be reached, or returned a response this module could not parse into a draft.
    Never conflated with `UNABLE_TO_DRAFT` (a legitimate model response, per the prompt above, meaning the
    model itself declined to guess) — that's returned as a normal `GeneratedPatch`, not raised.
    """


@dataclass
class GeneratedPatch:
    content: str
    """The model's proposed full replacement file content. `content == "UNABLE_TO_DRAFT"` verbatim is a
    real, valid, honest outcome — the caller must check for it explicitly rather than assume any non-error
    response is a usable draft."""
    raw_response: str
    """The full, unparsed model response — kept for the critic's/a human reviewer's inspection, not just
    the extracted content, since exactly what the model said (including any hedging it added despite the
    prompt) can matter to that review."""


def draft_patch(
    change_description: str,
    file_contents: str,
    base_url: str,
    *,
    model: str = "default",
    temperature: float = 0.1,
    client: httpx.Client | None = None,
) -> GeneratedPatch:
    """`temperature` defaults low deliberately: this is migration-rewriting, not creative generation — the
    model should reproduce the file with a minimal, deterministic-as-possible change, not explore phrasing.
    `model` defaults to `"default"` since llama-server ignores the field entirely when serving a single
    model (confirmed against its real `/v1/models` behavior — it always serves whatever was loaded via
    `-m`), so this is a no-op placeholder for compatibility with the OpenAI request shape, not a real
    selector.
    """
    owns_client = client is None
    http_client = client or httpx.Client(timeout=_DEFAULT_TIMEOUT_SECONDS)
    try:
        try:
            response = http_client.post(
                f"{base_url}/v1/chat/completions",
                json={
                    "model": model,
                    "temperature": temperature,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": f"Known change:\n{change_description}\n\nFile contents:\n{file_contents}",
                        },
                    ],
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise GeneratorError(f"could not reach the local model at {base_url}: {exc}") from exc

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise GeneratorError(
                f"model response did not match the expected OpenAI chat-completions shape: {exc}"
            ) from exc

        return GeneratedPatch(content=content.strip(), raw_response=response.text)
    finally:
        if owns_client:
            http_client.close()
