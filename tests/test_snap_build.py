"""Exercise locked Snap build orchestration, audit failures and offline hashes."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import venv
import zipfile
from pathlib import Path
from types import ModuleType

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_helper(name: str) -> ModuleType:
    """Load packaging helpers independently of the app and the machine's GTK."""
    spec = importlib.util.spec_from_file_location(f"snap_{name}", ROOT / f"snap/local/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = load_helper("build")
CHECK = load_helper("check_runtime")
# Legacy recognition tests replace sys.modules['tempfile'] during collection.
# Bind a private real stdlib copy without changing their global module state.
_TEMPFILE_SPEC = importlib.util.spec_from_file_location(
    "snap_stdlib_tempfile", Path(os.__file__).with_name("tempfile.py")
)
_TEMPFILE = importlib.util.module_from_spec(_TEMPFILE_SPEC)
_TEMPFILE_SPEC.loader.exec_module(_TEMPFILE)
BUILD.tempfile = _TEMPFILE


def export_pin(name: str, version: str = "1.0", marker: str = "") -> str:
    """Make a syntactically hash-pinned requirement, optionally with a marker."""
    condition = f" ; {marker}" if marker else ""
    return f"{name}=={version}{condition} \\\n    --hash=sha256:{'a' * 64}\n"


def distribution(root: Path, name: str, version: str) -> Path:
    """Write real dist-info metadata for the standard-library audit."""
    site = root / f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
    info = site / f"{name}-{version}.dist-info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n")
    return site


def test_locked_versions_evaluates_markers_and_normalizes_names(tmp_path: Path) -> None:
    """The other interpreter's numpy pin must not overwrite the active one."""
    export = tmp_path / "runtime.txt"
    export.write_text(
        export_pin("Some_Package", "2.0")
        + export_pin("numpy", "2.4", 'python_version < "3.12"')
        + export_pin("numpy", "2.5", 'python_version >= "3.12"')
    )
    assert CHECK.locked_versions(export) == {
        "some-package": "2.0",
        "numpy": "2.5" if sys.version_info >= (3, 12) else "2.4",
    }


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("# empty export\n", "No pinned requirements"),
        ("demo==1.0\n", "Missing SHA-256"),
        (export_pin("PyGObject"), "GI must come from"),
        (export_pin("demo") + export_pin("demo", "2.0"), "Multiple active pins"),
        (export_pin("demo", marker='python_version < "2"'), "No active requirements"),
    ],
)
def test_locked_versions_fails_closed(tmp_path: Path, text: str, message: str) -> None:
    """Reject exports that cannot define an unambiguous locked runtime."""
    export = tmp_path / "runtime.txt"
    export.write_text(text)
    with pytest.raises(RuntimeError, match=message):
        CHECK.locked_versions(export)


@pytest.mark.parametrize("change", ["missing", "extra", "version", "duplicate"])
def test_runtime_audit_rejects_drift(tmp_path: Path, change: str) -> None:
    """Reject missing, extra, duplicate and wrong-version runtime distributions."""
    distribution(tmp_path, "demo", "1.0")
    expected = {"demo": "1.0"}
    if change == "missing":
        expected["absent"] = "2.0"
    elif change == "extra":
        distribution(tmp_path, "setuptools", "84.0")
    elif change == "version":
        expected["demo"] = "2.0"
    else:
        distribution(tmp_path, "demo", "2.0")
    with pytest.raises(RuntimeError, match="Duplicate|differ from the lock"):
        CHECK.audit(tmp_path, expected)


def test_record_audits_payload_and_preserves_export_digests(tmp_path: Path) -> None:
    """Record audited runtime pins and the exact input export digests."""
    source = tmp_path / "source"
    (source / "requirements").mkdir(parents=True)
    (source / "requirements/runtime.txt").write_text(export_pin("demo"))
    (source / "requirements/installer-build.txt").write_text(
        export_pin("packaging", importlib.metadata.version("packaging"))
    )
    (source / "src/vocalinux").mkdir(parents=True)
    (source / "src/vocalinux/version.py").write_text('__version__ = "0.18.5"\n')
    root = tmp_path / "install"
    distribution(root, "demo", "1.0")
    distribution(root, "vocalinux", "0.18.5")
    CHECK.record(root, source)
    manifest = json.loads((root / CHECK.MANIFEST).read_text())
    assert manifest["packages"] == {"demo": "1.0", "vocalinux": "0.18.5"}
    assert manifest["python"] == list(sys.version_info[:2])
    for name, digest in manifest["exports"].items():
        assert digest == hashlib.sha256((source / "requirements" / name).read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (export_pin("packaging", "0.0"), "Build tool packaging"),
        ("# empty build export\n", "No pinned requirements"),
    ],
)
def test_record_rejects_unlocked_build_tools(tmp_path: Path, text: str, message: str) -> None:
    """Refuse incorrect build-tool versions or an empty toolchain export."""
    source = tmp_path / "source"
    (source / "requirements").mkdir(parents=True)
    (source / "requirements/installer-build.txt").write_text(text)
    with pytest.raises(RuntimeError, match=message):
        CHECK.record(tmp_path / "install", source)


@pytest.mark.parametrize("long_shebang", [False, True])
def test_launchers_are_relocatable_and_keep_locked_packages_first(
    tmp_path: Path, long_shebang: bool
) -> None:
    """Run relocated launchers against locked packages despite platform copies."""
    install = tmp_path / "install"
    binary = install / "bin"
    binary.mkdir(parents=True)
    tooling = tmp_path / "tooling"
    python = tooling / "bin/python3"
    header = (
        f"#!/bin/sh\n'''exec' {python} \"$0\" \"$@\"\n' '''\n" if long_shebang else f"#!{python}\n"
    )
    for name in ("vocalinux", "vocalinux-gui", "pwcpp"):
        path = binary / name
        path.write_text(header + "print('entry point')\n")
        path.chmod(0o755)
    (binary / "python3").symlink_to(sys.executable)
    site = distribution(install, "vocalinux", "0.18.5")
    package = site / "vocalinux"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "main.py").write_text("def main():\n    print('locked runtime')\n")
    # Simulate a platform with an incidental conflicting copy.
    platform = tmp_path / "platform/vocalinux"
    platform.mkdir(parents=True)
    (platform / "__init__.py").write_text("raise RuntimeError('wrong runtime')\n")
    BUILD.relocate_scripts(install, tooling)
    for name in ("vocalinux", "vocalinux-gui", "pwcpp"):
        text = (binary / name).read_text()
        assert text.startswith("#!/usr/bin/env python3\n")
        assert str(tooling) not in text
        assert os.access(binary / name, os.X_OK)
    result = subprocess.run(
        [str(binary / "vocalinux")],
        env={
            **os.environ,
            "PATH": f"{binary}{os.pathsep}{os.environ['PATH']}",
            "PYTHONPATH": str(platform.parent),
        },
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "locked runtime"


def test_build_orchestration_uses_hashes_and_separates_tooling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stub expensive builds, not the command construction or source protection."""
    source = tmp_path / "source"
    (source / "requirements").mkdir(parents=True)
    metadata = source / "pyproject.toml"
    metadata.write_text('[project]\ndependencies = ["PyGObject"]\n')
    for name in ("installer-build.txt", "runtime.txt"):
        (source / "requirements" / name).write_text(export_pin("demo"))
    install = tmp_path / "install"
    work = tmp_path / "work"
    environments = []
    calls = []

    def create(builder: venv.EnvBuilder, path: Path) -> None:
        (path / "bin").mkdir(parents=True, exist_ok=True)
        environments.append((path, builder.with_pip, builder.system_site_packages))

    def run(argv: list[str], cwd: Path, env: dict[str, str]) -> None:
        calls.append((argv, cwd, env.copy()))
        if str(source) == argv[-1]:
            for name in ("vocalinux", "vocalinux-gui"):
                (install / "bin" / name).write_text(f"#!{argv[0]}\n")

    monkeypatch.setattr(BUILD.venv.EnvBuilder, "create", create)
    monkeypatch.setattr(BUILD, "run", run)
    monkeypatch.setenv("PIP_INDEX_URL", "https://untrusted.invalid")
    monkeypatch.setenv("PYTHONPATH", "/unlocked-platform")
    monkeypatch.setenv("CMAKE_ARGS", "-DGGML_NATIVE=OFF")
    before = metadata.read_bytes()
    BUILD.build(source, install, work)
    assert metadata.read_bytes() == before
    assert len(calls) == 4
    tools, runtime, project, audit = [call[0] for call in calls]
    for argv in (tools, runtime):
        assert {
            "--isolated",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--require-hashes",
            "--no-deps",
        } <= set(argv)
    assert "--only-binary=:all:" in tools
    assert tools[-1] == str(source / "requirements/installer-build.txt")
    assert {"--no-build-isolation", "--ignore-installed", "--no-binary=pywhispercpp"} <= set(
        runtime
    )
    assert runtime[-1] == str(source / "requirements/runtime.txt")
    assert runtime[runtime.index("--prefix") + 1] == str(install)
    assert {"--no-deps", "--no-build-isolation", "--no-index"} <= set(project)
    assert project[-1] == str(source)
    assert "--record" in audit and str(install) in audit
    assert environments[0][1:] == (True, False)
    assert environments[1] == (install, False, False)
    assert not environments[0][0].exists()
    for _, cwd, env in calls:
        assert cwd == source
        assert "PIP_INDEX_URL" not in env and "PYTHONPATH" not in env
        assert env["PIP_CONFIG_FILE"] == os.devnull
        assert env["CMAKE_ARGS"] == "-DGGML_NATIVE=OFF"
        assert env["PATH"].split(os.pathsep)[0] == str(environments[0][0] / "bin")


def test_ci_builds_recipe_only_changes_and_checks_before_publication() -> None:
    """Require equivalent PR/release artifact gates before uploading the Snap."""
    ci = yaml.safe_load((ROOT / ".github/workflows/unified-pipeline.yml").read_text())
    jobs = ci["jobs"]
    changes = jobs["changes"]
    filters = yaml.safe_load(
        next(
            step["with"]["filters"]
            for step in changes["steps"]
            if "filters" in step.get("with", {})
        )
    )
    assert "snap/**" in filters["snap"]
    # A recipe- or smoke-script-only change must still run the tests guarding them.
    assert "snap/**" in filters["python"]
    assert changes["outputs"]["snap"] == "${{ steps.filter.outputs.snap }}"
    pr = jobs["snap-build-test"]
    assert "outputs.snap == 'true'" in pr["if"]
    assert "outputs.python == 'true'" in pr["if"]
    assert pr["permissions"] == {"contents": "read"}
    release = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    production = release["jobs"]["build-snap"]
    builders = []
    for job in (pr, production):
        steps = job["steps"]
        build = next(
            index
            for index, step in enumerate(steps)
            if step.get("uses", "").startswith("snapcore/action-build@")
        )
        smoke = next(
            index
            for index, step in enumerate(steps)
            if "snap/local/smoke-test.sh" in step.get("run", "")
        )
        upload = next(
            index
            for index, step in enumerate(steps)
            if step.get("uses", "").startswith("actions/upload-artifact@")
        )
        assert build < smoke < upload
        assert job["runs-on"] == "ubuntu-24.04"
        assert job["timeout-minutes"] >= 30
        assert "continue-on-error" not in job
        assert "continue-on-error" not in steps[smoke]
        assert "secrets." not in json.dumps(job)
        builders.append(steps[build]["uses"])
    assert builders[0] == builders[1]


@pytest.mark.timeout(30)
def test_runtime_pip_flags_reject_corrupt_artifact_offline(tmp_path: Path) -> None:
    """Exercise pip's real hash check with the same runtime install flags."""
    environment = tmp_path / "tooling"
    venv.EnvBuilder(with_pip=True).create(environment)
    wheel = tmp_path / "demo-1.0-py3-none-any.whl"
    real_zipfile = getattr(sys, "_vocalinux_real_zipfile", zipfile)
    with real_zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("demo.py", "VALUE = 1\n")
        archive.writestr(
            "demo-1.0.dist-info/METADATA", "Metadata-Version: 2.1\nName: demo\nVersion: 1.0\n"
        )
        archive.writestr(
            "demo-1.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr("demo-1.0.dist-info/RECORD", "")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    export = tmp_path / "runtime.txt"
    export.write_text(f"demo==1.0 --hash=sha256:{digest}\n")
    python = str(environment / "bin/python3")
    command = [
        python,
        "-m",
        "pip",
        "--isolated",
        "install",
        "--no-cache-dir",
        "--require-hashes",
        "--no-deps",
        "--no-build-isolation",
        "--no-binary=pywhispercpp",
        "--ignore-installed",
        "--no-compile",
        "--prefix",
        str(tmp_path / "install"),
        "--no-index",
        "--find-links",
        str(tmp_path),
        "-r",
        str(export),
    ]
    env = {**os.environ, "PIP_CONFIG_FILE": os.devnull}
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    CHECK.audit(tmp_path / "install", {"demo": "1.0"})
    with wheel.open("ab") as stream:
        stream.write(b"corrupted after the hash was pinned")
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "DO NOT MATCH THE HASHES" in result.stderr


@pytest.mark.timeout(60)
def test_full_python_payload_build_is_offline_and_keeps_project_metadata(tmp_path: Path) -> None:
    """Run the real build pipeline with tiny local wheels and a PEP 517 fixture."""
    import packaging

    source = tmp_path / "source"
    (source / "requirements").mkdir(parents=True)
    (source / "snap/local").mkdir(parents=True)
    shutil.copy2(ROOT / "snap/local/check_runtime.py", source / "snap/local/check_runtime.py")
    (source / "src/vocalinux").mkdir(parents=True)
    (source / "src/vocalinux/version.py").write_text('__version__ = "0.18.5"\n')
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    real_zipfile = getattr(sys, "_vocalinux_real_zipfile", zipfile)

    def wheel(name: str, version: str, files: dict[str, str]) -> Path:
        path = wheelhouse / f"{name}-{version}-py3-none-any.whl"
        with real_zipfile.ZipFile(path, "w") as archive:
            for filename, text in files.items():
                archive.writestr(filename, text)
            info = f"{name}-{version}.dist-info"
            archive.writestr(
                f"{info}/METADATA", f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
            )
            archive.writestr(
                f"{info}/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
            )
            archive.writestr(f"{info}/RECORD", "")
        return path

    # The build-only packaging library is real, but every byte is served by
    # the local wheelhouse. No test index, shared pip cache or network is used.
    library = Path(packaging.__file__).parent
    tools = wheel(
        "packaging",
        packaging.__version__,
        {
            f"packaging/{path.relative_to(library)}": path.read_text()
            for path in library.rglob("*.py")
        },
    )
    runtime = wheel("demo", "1.0", {"demo.py": "VALUE = 1\n"})
    app = wheel(
        "vocalinux",
        "0.18.5",
        {
            "vocalinux/__init__.py": "",
            "vocalinux/main.py": "def main():\n    print('fixture app')\n",
            "vocalinux-0.18.5.dist-info/entry_points.txt": "[console_scripts]\nvocalinux = vocalinux.main:main\n"
            "[gui_scripts]\nvocalinux-gui = vocalinux.main:main\n",
        },
    )
    for filename, name, version, artifact in (
        ("installer-build.txt", "packaging", packaging.__version__, tools),
        ("runtime.txt", "demo", "1.0", runtime),
    ):
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        (source / "requirements" / filename).write_text(
            f"--no-index\n--find-links {wheelhouse}\n{name}=={version} --hash=sha256:{digest}\n"
        )
    # An entirely stdlib backend lets the fixture build without downloading
    # setuptools. The real project uses the locked setuptools toolchain.
    metadata = source / "pyproject.toml"
    metadata.write_text(
        '[build-system]\nrequires = []\nbuild-backend = "backend"\nbackend-path = ["."]\n'
        '[project]\nname = "vocalinux"\nversion = "0.18.5"\ndependencies = ["PyGObject"]\n'
    )
    (source / "backend.py").write_text(
        "import shutil\nfrom pathlib import Path\n"
        "def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):\n"
        f"    source = Path({str(app)!r})\n"
        "    shutil.copy2(source, Path(wheel_directory) / source.name)\n"
        "    return source.name\n"
    )
    before = metadata.read_bytes()
    install = tmp_path / "install"
    BUILD.build(source, install, tmp_path / "work")
    assert metadata.read_bytes() == before
    CHECK.audit(install, {"demo": "1.0", "vocalinux": "0.18.5"})
    assert not list((tmp_path / "work").iterdir())
    assert not (install / "bin/pip").exists()
    result = subprocess.run(
        [str(install / "bin/python3"), str(install / "bin/vocalinux")],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "fixture app"


@pytest.mark.parametrize("existing", [False, True])
def test_artifact_smoke_refuses_user_install_and_checks_the_supplied_file(
    tmp_path: Path, existing: bool
) -> None:
    """Execute the real shell gate; fake only snapd/sudo, never touch a host app."""
    tools = tmp_path / "tools"
    tools.mkdir()
    log = tmp_path / "calls.jsonl"
    for name in ("snap", "sudo"):
        path = tools / name
        path.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "with open(os.environ['SNAP_TEST_LOG'], 'a') as stream:\n"
            "    stream.write(json.dumps([Path(sys.argv[0]).name, sys.argv[1:], "
            "os.environ.get('PYNPUT_BACKEND')]) + '\\n')\n"
            "if sys.argv[1:3] == ['list', 'vocalinux']:\n"
            "    sys.exit(0 if os.environ['SNAP_TEST_EXISTING'] == '1' else 1)\n"
        )
        path.chmod(0o755)
    artifact = tmp_path / "selected.snap"
    artifact.write_bytes(b"artifact stand-in")
    result = subprocess.run(
        ["bash", str(ROOT / "snap/local/smoke-test.sh"), str(artifact)],
        env={
            **os.environ,
            "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
            "SNAP_TEST_LOG": str(log),
            "SNAP_TEST_EXISTING": "1" if existing else "0",
        },
        capture_output=True,
        text=True,
        timeout=5,
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    if existing:
        assert result.returncode != 0
        assert "Refusing to replace" in result.stderr
        assert len(calls) == 1
    else:
        assert result.returncode == 0, result.stderr
        assert calls[1][:2] == ["sudo", ["snap", "install", "--dangerous", str(artifact)]]
        assert calls[2][:2] == ["snap", ["run", "vocalinux", "--version"]]
        assert calls[3][1][:4] == ["run", "--shell", "vocalinux", "-c"]
        assert '"$SNAP/snap/command-chain/desktop-launch"' in calls[3][1][4]
        assert '"$SNAP/usr/lib/vocalinux/check_runtime.py"' in calls[3][1][4]
        assert calls[3][2] == "dummy"
