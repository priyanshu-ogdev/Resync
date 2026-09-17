"""Per docs/testing-strategy.md: table-driven, covering every branch, not just the obvious case."""

from resync.knowledge.router import RetrievalRoute, route


def test_fully_qualified_symbol_routes_to_exact_lookup() -> None:
    assert route("peft.PeftModel.from_pretrained") == RetrievalRoute.EXACT_SYMBOL_LOOKUP
    assert route("transformers.PreTrainedModel.from_pretrained") == RetrievalRoute.EXACT_SYMBOL_LOOKUP


def test_free_text_question_routes_to_hybrid_search() -> None:
    assert route("why was use_auth_token deprecated?") == RetrievalRoute.HYBRID_SEARCH
    assert route("how do I migrate from PeftConfig to the new API") == RetrievalRoute.HYBRID_SEARCH


def test_single_word_is_not_treated_as_a_qualified_symbol() -> None:
    # A bare word has no dots, so it isn't a fully-qualified symbol even though it has no spaces either —
    # this is the boundary case a less careful pattern would get wrong.
    assert route("transformers") == RetrievalRoute.HYBRID_SEARCH


def test_whitespace_is_stripped_before_matching() -> None:
    assert route("  peft.PeftModel.from_pretrained  ") == RetrievalRoute.EXACT_SYMBOL_LOOKUP
