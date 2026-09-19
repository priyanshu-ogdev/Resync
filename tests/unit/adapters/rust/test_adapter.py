from pathlib import Path

from resync.adapters.rust.adapter import RustAdapter


def test_parse_manifest(tmp_path: Path) -> None:
    cargo_toml = tmp_path / "Cargo.toml"
    cargo_toml.write_text(
        """
[package]
name = "demo"
version = "0.1.0"

[dependencies]
tokio = "1.0"
serde = { version = "1.0", features = ["derive"] }

[dev-dependencies]
rstest = "0.18.0"
        """
    )

    adapter = RustAdapter()
    deps = adapter.parse_manifest(tmp_path)

    assert len(deps) == 3
    assert deps[0].name == "tokio"
    assert deps[0].version == "1.0"
    assert deps[1].name == "serde"
    assert deps[1].version == "1.0"
    assert deps[2].name == "rstest"
    assert deps[2].version == "0.18.0"


def test_parse_manifest_missing(tmp_path: Path) -> None:
    adapter = RustAdapter()
    deps = adapter.parse_manifest(tmp_path)
    assert len(deps) == 0
