from pathlib import Path

from resync.adapters.python import PythonAdapter
from resync.adapters.registry import get_adapter
from resync.adapters.rust import RustAdapter
from resync.adapters.typescript import TypeScriptAdapter


def test_registry_returns_typescript_adapter_when_package_json_exists(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}")
    adapter = get_adapter(tmp_path)
    assert isinstance(adapter, TypeScriptAdapter)

def test_registry_returns_rust_adapter_when_cargo_toml_exists(tmp_path: Path) -> None:
    (tmp_path / "Cargo.toml").write_text("")
    adapter = get_adapter(tmp_path)
    assert isinstance(adapter, RustAdapter)

def test_registry_defaults_to_python_adapter(tmp_path: Path) -> None:
    adapter = get_adapter(tmp_path)
    assert isinstance(adapter, PythonAdapter)
