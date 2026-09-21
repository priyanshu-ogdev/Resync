"""Adapter auto-discovery registry — three-tier plugin engine.

**Tier 1 — pip entry-points** (highest priority, zero Resync code change required):
    Any pip package may expose adapters by registering under the ``resync.adapters`` group::

        # In resync-adapter-ruby/pyproject.toml
        [project.entry-points."resync.adapters"]
        ruby = "resync_adapter_ruby:RubyAdapter"

    Resync discovers these automatically via ``importlib.metadata.entry_points`` at startup.
    Entry-point adapters override built-in ones with the same ``name``, enabling drop-in overrides.

**Tier 2 — Built-in directory scan**:
    Walks ``resync/adapters/*/adapter.py``, imports each, reads ``METADATA`` and ``ADAPTER_CLASS``
    at module level.  Built-in adapters (Python, Rust, TypeScript, Kotlin, Go, Java, C/C++) follow
    the exact same contract third-party adapters follow.

**Tier 3 — PATH capability gating**:
    Each adapter's ``METADATA.required_tools`` list is checked via ``shutil.which()``.  Adapters
    whose required tools are absent are silently skipped rather than raising at runtime.

Adding a new language requires **only** creating a new ``adapters/<lang>/adapter.py`` with a
``METADATA: AdapterMetadata`` constant and ``ADAPTER_CLASS = YourAdapter``.  No changes to this
file are needed.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
import shutil
from pathlib import Path

from resync.adapters.base import AdapterMetadata, LanguageAdapter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal cache — avoid re-scanning on every call
# ---------------------------------------------------------------------------

_ADAPTER_CACHE: list[tuple[AdapterMetadata, type]] | None = None


def _discover_all_adapters() -> list[tuple[AdapterMetadata, type]]:
    """Discover all available adapters via entry-points and built-in directory scan.

    Returns a list of (metadata, adapter_class) pairs, deduplicated by adapter name.
    Entry-point adapters take priority over built-in ones with the same name.
    """
    global _ADAPTER_CACHE
    if _ADAPTER_CACHE is not None:
        return _ADAPTER_CACHE

    found: dict[str, tuple[AdapterMetadata, type]] = {}

    # ------------------------------------------------------------------
    # Tier 1: pip entry-points  (resync.adapters group)
    # ------------------------------------------------------------------
    try:
        for ep in importlib.metadata.entry_points(group="resync.adapters"):
            try:
                cls = ep.load()
                meta: AdapterMetadata | None = getattr(cls, "METADATA", None)
                if meta is None:
                    # Check module-level METADATA (preferred pattern)
                    mod = importlib.import_module(cls.__module__)
                    meta = getattr(mod, "METADATA", None)
                if meta is not None:
                    found[meta.name] = (meta, cls)
                    logger.debug("Registered entry-point adapter: %s (from %s)", meta.name, ep.value)
            except Exception as exc:
                logger.warning("Failed to load entry-point adapter %r: %s", ep.name, exc)
    except Exception as exc:
        logger.debug("entry_points discovery failed (non-fatal): %s", exc)

    # ------------------------------------------------------------------
    # Tier 2: Built-in adapter directory scan
    # ------------------------------------------------------------------
    adapters_root = Path(__file__).parent
    for adapter_file in sorted(adapters_root.glob("*/adapter.py")):
        lang = adapter_file.parent.name
        if lang.startswith("_"):
            continue
        if lang in found:
            # Entry-point adapter already registered for this name — skip built-in
            continue
        try:
            module = importlib.import_module(f"resync.adapters.{lang}.adapter")
            cls = getattr(module, "ADAPTER_CLASS", None)
            meta = getattr(module, "METADATA", None)
            if cls is not None and meta is not None:
                found[lang] = (meta, cls)
                logger.debug("Registered built-in adapter: %s", lang)
            else:
                logger.debug("Skipping adapters/%s/adapter.py — missing METADATA or ADAPTER_CLASS", lang)
        except Exception as exc:
            logger.warning("Failed to import built-in adapter %r: %s", lang, exc)

    _ADAPTER_CACHE = list(found.values())
    return _ADAPTER_CACHE


def _clear_cache() -> None:
    """Reset the adapter discovery cache. Exposed for testing."""
    global _ADAPTER_CACHE
    _ADAPTER_CACHE = None


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


def _repo_has_signal(repo_root: Path, meta: AdapterMetadata) -> bool:
    """Return True if the repo contains at least one manifest signal for this adapter."""
    exclude = set(meta.exclude_dirs)

    # Fast path: check exact filenames at root
    for filename in meta.manifest_files:
        if (repo_root / filename).exists():
            return True

    # Check immediate subdirs (scan once, not once per manifest filename)
    try:
        subdirs = [sub for sub in repo_root.iterdir() if sub.is_dir() and sub.name not in exclude]
    except OSError:
        subdirs = []

    for filename in meta.manifest_files:
        for sub in subdirs:
            if (sub / filename).exists():
                return True

    # Slower path: recursive glob (only when manifest_files produced no hit)
    if meta.manifest_globs:
        for pattern in meta.manifest_globs:
            for match in repo_root.glob(pattern):
                # Relativize first — using match.parts directly would compare against absolute path
                # components, causing false exclusions when the repo root path itself contains a
                # segment that matches an exclude dir (e.g. D:/build/myrepo → 'build' in parts).
                try:
                    rel_parts = match.relative_to(repo_root).parts
                except ValueError:
                    continue
                if not any(part in exclude for part in rel_parts):
                    return True

    return False


def _tools_available(meta: AdapterMetadata) -> bool:
    """Return True if all required_tools are resolvable via shutil.which()."""
    missing = [t for t in meta.required_tools if not shutil.which(t)]
    if missing:
        logger.debug(
            "Adapter %r skipped — required tool(s) not on PATH: %s",
            meta.name,
            ", ".join(missing),
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_adapters(repo_root: Path) -> list[LanguageAdapter]:
    """Return all LanguageAdapters that match ``repo_root``, sorted by priority (highest first).

    An adapter is included when:
    1. The repo contains at least one manifest file / glob signal for that adapter.
    2. All ``required_tools`` entries are found on PATH.

    Supports polyglot repos (TypeScript frontend + Python backend → both adapters returned).
    """
    results: list[tuple[int, LanguageAdapter]] = []
    for meta, cls in _discover_all_adapters():
        if _repo_has_signal(repo_root, meta) and _tools_available(meta):
            try:
                instance = cls()
                results.append((meta.priority, instance))
            except Exception as exc:
                logger.warning("Failed to instantiate adapter %r: %s", meta.name, exc)

    # Fallback: if nothing matched, use PythonAdapter (matches prior behaviour)
    if not results:
        logger.debug("No adapter matched repo_root=%s — falling back to PythonAdapter", repo_root)
        from resync.adapters.python.adapter import PythonAdapter

        return [PythonAdapter()]

    results.sort(key=lambda t: t[0], reverse=True)
    return [adapter for _, adapter in results]


def get_adapter(repo_root: Path) -> LanguageAdapter:
    """Return the highest-priority LanguageAdapter for ``repo_root``.

    Defaults to PythonAdapter if no adapter matches.
    """
    return get_adapters(repo_root)[0]


def list_supported_languages() -> list[AdapterMetadata]:
    """Return metadata for all discovered adapters (built-in + third-party entry-points).

    Used by ``resync info`` and ``resync doctor`` to display the language support table,
    including which optional tools are available on the current system.
    """
    return [meta for meta, _ in _discover_all_adapters()]
