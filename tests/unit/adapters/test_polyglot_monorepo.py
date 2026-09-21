from __future__ import annotations

from pathlib import Path

from resync.adapters.c_cpp.adapter import CCppAdapter
from resync.adapters.go.adapter import GoAdapter
from resync.adapters.java.adapter import JavaAdapter
from resync.adapters.python.adapter import PythonAdapter
from resync.adapters.rust.adapter import RustAdapter
from resync.adapters.typescript.adapter import TypeScriptAdapter


def test_python_monorepo_pep735_and_nested_requirements(tmp_path: Path) -> None:
    root_pyproject = tmp_path / "pyproject.toml"
    root_pyproject.write_text(
        """
[project]
name = "root-project"
version = "0.1.0"
dependencies = [
    "requests>=2.28.0",
    "pydantic>=2.0.0",
]

[dependency-groups]
test = [
    "pytest>=8.0.0",
]
docs = [
    "sphinx>=7.0.0",
]
""",
        encoding="utf-8",
    )

    worker_dir = tmp_path / "services" / "worker"
    worker_dir.mkdir(parents=True)
    worker_req = worker_dir / "requirements.txt"
    worker_req.write_text(
        """
celery==5.3.6
redis==5.0.1
""",
        encoding="utf-8",
    )

    adapter = PythonAdapter()
    deps = adapter.parse_manifest(tmp_path)
    dep_dict = {d.name: d.version for d in deps}

    assert "requests" in dep_dict
    assert "pydantic" in dep_dict
    assert "pytest" in dep_dict
    assert "sphinx" in dep_dict
    assert "celery" in dep_dict
    assert "redis" in dep_dict


def test_typescript_monorepo_workspaces(tmp_path: Path) -> None:
    root_pkg = tmp_path / "package.json"
    root_pkg.write_text(
        """
{
  "name": "monorepo-root",
  "devDependencies": {
    "typescript": "^5.0.0",
    "prettier": "^3.0.0"
  }
}
""",
        encoding="utf-8",
    )

    web_dir = tmp_path / "apps" / "web"
    web_dir.mkdir(parents=True)
    web_pkg = web_dir / "package.json"
    web_pkg.write_text(
        """
{
  "name": "@mono/web",
  "dependencies": {
    "react": "^18.2.0",
    "next": "^14.0.0"
  }
}
""",
        encoding="utf-8",
    )

    ui_dir = tmp_path / "packages" / "ui"
    ui_dir.mkdir(parents=True)
    ui_pkg = ui_dir / "package.json"
    ui_pkg.write_text(
        """
{
  "name": "@mono/ui",
  "dependencies": {
    "tailwindcss": "^3.4.0"
  },
  "peerDependencies": {
    "react": ">=18.0.0"
  }
}
""",
        encoding="utf-8",
    )

    adapter = TypeScriptAdapter()
    deps = adapter.parse_manifest(tmp_path)
    dep_dict = {d.name: d.version for d in deps}

    assert "typescript" in dep_dict
    assert "prettier" in dep_dict
    assert "react" in dep_dict
    assert "next" in dep_dict
    assert "tailwindcss" in dep_dict


def test_rust_workspace_manifests(tmp_path: Path) -> None:
    root_cargo = tmp_path / "Cargo.toml"
    root_cargo.write_text(
        """
[workspace]
members = ["crates/*"]

[workspace.dependencies]
serde = "1.0"
tokio = { version = "1.30", features = ["full"] }
""",
        encoding="utf-8",
    )

    core_dir = tmp_path / "crates" / "core"
    core_dir.mkdir(parents=True)
    core_cargo = core_dir / "Cargo.toml"
    core_cargo.write_text(
        """
[package]
name = "core"
version = "0.1.0"

[dependencies]
serde = { workspace = true }
anyhow = "1.0"
""",
        encoding="utf-8",
    )

    adapter = RustAdapter()
    deps = adapter.parse_manifest(tmp_path)
    dep_dict = {d.name: d.version for d in deps}

    assert "serde" in dep_dict
    assert "tokio" in dep_dict
    assert "anyhow" in dep_dict


def test_go_multi_module_manifests(tmp_path: Path) -> None:
    root_mod = tmp_path / "go.mod"
    root_mod.write_text(
        """
module example.com/root

go 1.21

require (
    github.com/gin-gonic/gin v1.9.1
)
""",
        encoding="utf-8",
    )

    tools_dir = tmp_path / "tools" / "migrator"
    tools_dir.mkdir(parents=True)
    tools_mod = tools_dir / "go.mod"
    tools_mod.write_text(
        """
module example.com/root/tools/migrator

go 1.21

require (
    github.com/golang-migrate/migrate/v4 v4.16.2
)
""",
        encoding="utf-8",
    )

    adapter = GoAdapter()
    deps = adapter.parse_manifest(tmp_path)
    dep_dict = {d.name: d.version for d in deps}

    assert "github.com/gin-gonic/gin" in dep_dict
    assert dep_dict["github.com/gin-gonic/gin"] == "v1.9.1"
    assert "github.com/golang-migrate/migrate/v4" in dep_dict
    assert dep_dict["github.com/golang-migrate/migrate/v4"] == "v4.16.2"


def test_java_multi_module_manifests(tmp_path: Path) -> None:
    root_pom = tmp_path / "pom.xml"
    root_pom.write_text(
        """
<project>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
      <version>3.1.0</version>
    </dependency>
  </dependencies>
</project>
""",
        encoding="utf-8",
    )

    sub_dir = tmp_path / "service-a"
    sub_dir.mkdir(parents=True)
    sub_pom = sub_dir / "pom.xml"
    sub_pom.write_text(
        """
<project>
  <dependencies>
    <dependency>
      <groupId>com.google.guava</groupId>
      <artifactId>guava</artifactId>
      <version>32.1.2-jre</version>
    </dependency>
  </dependencies>
</project>
""",
        encoding="utf-8",
    )

    adapter = JavaAdapter()
    deps = adapter.parse_manifest(tmp_path)
    dep_dict = {d.name: d.version for d in deps}

    assert "org.springframework.boot:spring-boot-starter-web" in dep_dict
    assert "com.google.guava:guava" in dep_dict


def test_c_cpp_multi_manifests(tmp_path: Path) -> None:
    root_conan = tmp_path / "conanfile.txt"
    root_conan.write_text(
        """
[requires]
boost/1.81.0
fmt/9.1.0
""",
        encoding="utf-8",
    )

    sub_dir = tmp_path / "subproject"
    sub_dir.mkdir(parents=True)
    sub_vcpkg = sub_dir / "vcpkg.json"
    sub_vcpkg.write_text(
        """
{
  "dependencies": [
    { "name": "nlohmann-json" }
  ]
}
""",
        encoding="utf-8",
    )

    adapter = CCppAdapter()
    deps = adapter.parse_manifest(tmp_path)
    dep_dict = {d.name: d.version for d in deps}

    assert "boost" in dep_dict
    assert dep_dict["boost"] == "1.81.0"
    assert "fmt" in dep_dict
    assert "nlohmann-json" in dep_dict
