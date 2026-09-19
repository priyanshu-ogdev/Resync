import json
from pathlib import Path

from resync.adapters.typescript.adapter import TypeScriptAdapter


def test_parse_manifest(tmp_path: Path) -> None:
    package_json = tmp_path / "package.json"
    package_json.write_text(
        json.dumps(
            {
                "dependencies": {"react": "^18.0.0"},
                "devDependencies": {"typescript": "^5.0.0"},
            }
        )
    )

    adapter = TypeScriptAdapter()
    deps = adapter.parse_manifest(tmp_path)

    assert len(deps) == 2
    assert deps[0].name == "react"
    assert deps[0].version == "^18.0.0"
    assert deps[1].name == "typescript"
    assert deps[1].version == "^5.0.0"


def test_parse_manifest_missing(tmp_path: Path) -> None:
    adapter = TypeScriptAdapter()
    deps = adapter.parse_manifest(tmp_path)
    assert len(deps) == 0
