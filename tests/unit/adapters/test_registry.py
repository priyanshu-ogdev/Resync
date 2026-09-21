from pathlib import Path

from resync.adapters.go import GoAdapter
from resync.adapters.kotlin import KotlinAdapter
from resync.adapters.python import PythonAdapter
from resync.adapters.registry import get_adapter, get_adapters
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


def test_registry_returns_kotlin_adapter_when_gradle_file_exists(tmp_path: Path) -> None:
    (tmp_path / "build.gradle.kts").write_text("")
    adapter = get_adapter(tmp_path)
    assert isinstance(adapter, KotlinAdapter)


def test_registry_returns_go_adapter_when_go_mod_exists(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module example.com/pkg\n\ngo 1.21\n")
    adapter = get_adapter(tmp_path)
    assert isinstance(adapter, GoAdapter)


def test_registry_defaults_to_python_adapter(tmp_path: Path) -> None:
    adapter = get_adapter(tmp_path)
    assert isinstance(adapter, PythonAdapter)


def test_registry_polyglot_returns_multiple_adapters(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "requirements.txt").write_text("fastapi>=0.100.0\n")
    adapters = get_adapters(tmp_path)
    adapter_types = [type(a) for a in adapters]
    assert TypeScriptAdapter in adapter_types
    assert PythonAdapter in adapter_types
