from pathlib import Path

from resync.adapters.base import LanguageAdapter
from resync.adapters.python import PythonAdapter
from resync.adapters.rust import RustAdapter
from resync.adapters.typescript import TypeScriptAdapter


def get_adapter(repo_root: Path) -> LanguageAdapter:
    """
    Inspects the given repository root and returns the appropriate LanguageAdapter.
    Defaults to PythonAdapter if no other known manifest is found.
    """
    if (repo_root / "package.json").exists():
        return TypeScriptAdapter()
    
    if (repo_root / "Cargo.toml").exists():
        return RustAdapter()
    
    # Default to Python (pyproject.toml or generic)
    return PythonAdapter()
