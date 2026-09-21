from pathlib import Path

from resync.adapters.kotlin.adapter import KotlinAdapter, _parse_gradle, _parse_version_catalog


def test_parse_version_catalog() -> None:
    toml_content = """
    [versions]
    coreKtx = "1.12.0"
    room = "2.6.1"

    [libraries]
    androidx-core-ktx = { group = "androidx.core", name = "core-ktx", version.ref = "coreKtx" }
    androidx-room-runtime = { module = "androidx.room:room-runtime", version.ref = "room" }
    lottie = { module = "com.airbnb.android:lottie", version = "6.7.1" }
    bare-string = "com.google.code.gson:gson:2.10.1"
    """
    deps = _parse_version_catalog(toml_content)
    dep_dict = {d.name: d.version for d in deps}

    assert dep_dict["androidx.core:core-ktx"] == "1.12.0"
    assert dep_dict["androidx.room:room-runtime"] == "2.6.1"
    assert dep_dict["com.airbnb.android:lottie"] == "6.7.1"
    assert dep_dict["com.google.code.gson:gson"] == "2.10.1"


def test_parse_gradle_android_configurations_and_vars() -> None:
    gradle_content = """
    val roomVersion = "2.6.1"
    dependencies {
        implementation("androidx.core:core-splashscreen:1.0.1")
        ksp("androidx.room:room-compiler:$roomVersion")
        androidTestImplementation("androidx.test.espresso:espresso-core:3.5.1")
        coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.0.4")
    }
    """
    deps = _parse_gradle(gradle_content)
    dep_dict = {d.name: d.version for d in deps}

    assert dep_dict["androidx.core:core-splashscreen"] == "1.0.1"
    assert dep_dict["androidx.room:room-compiler"] == "2.6.1"
    assert dep_dict["androidx.test.espresso:espresso-core"] == "3.5.1"
    assert dep_dict["com.android.tools:desugar_jdk_libs"] == "2.0.4"


def test_kotlin_adapter_multi_module_parse_manifest(tmp_path: Path) -> None:
    gradle_dir = tmp_path / "gradle"
    gradle_dir.mkdir()
    (gradle_dir / "libs.versions.toml").write_text(
        '[versions]\nktx = "1.12.0"\n'
        '[libraries]\ncore-ktx = { group = "androidx.core", name = "core-ktx", version.ref = "ktx" }\n',
        encoding="utf-8",
    )
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "build.gradle.kts").write_text(
        'dependencies { implementation("com.airbnb.android:lottie:6.7.1") }\n',
        encoding="utf-8",
    )

    adapter = KotlinAdapter()
    deps = adapter.parse_manifest(tmp_path)
    dep_dict = {d.name: d.version for d in deps}

    assert "androidx.core:core-ktx" in dep_dict
    assert dep_dict["androidx.core:core-ktx"] == "1.12.0"
    assert "com.airbnb.android:lottie" in dep_dict
    assert dep_dict["com.airbnb.android:lottie"] == "6.7.1"
