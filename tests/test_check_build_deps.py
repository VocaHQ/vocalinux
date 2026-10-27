"""Guards for the `just deps` native build-dependency preflight."""

import importlib.metadata
import importlib.util
import subprocess
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_build_deps.py"
SPEC = importlib.util.spec_from_file_location("check_build_deps", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
PREFLIGHT: Any = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)


@pytest.fixture(autouse=True)
def linux_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep Linux checks covered even when contributors run the suite on macOS."""
    monkeypatch.setattr(PREFLIGHT.sys, "platform", "linux")


def test_os_release_parser_strips_quotes_and_ignores_comments(tmp_path: Path) -> None:
    """os-release is parsed, not sourced; quoted values lose their quotes."""
    release = tmp_path / "os-release"
    release.write_text(
        'ID=fedora\nID_LIKE="rhel centos"\n# comment\nVERSION_ID="45"\n',
        encoding="utf-8",
    )

    assert PREFLIGHT.read_os_release(release) == {
        "ID": "fedora",
        "ID_LIKE": "rhel centos",
        "VERSION_ID": "45",
    }


@pytest.mark.parametrize(
    "distro,like,expected",
    [
        ("ubuntu", "debian", "sudo apt install"),
        ("fedora", "rhel", "sudo dnf install"),
        ("rocky", "rhel fedora", "sudo dnf install"),
        ("arch", "", "sudo pacman -S"),
        ("opensuse-tumbleweed", "suse", "sudo zypper install"),
    ],
)
def test_install_hint_matches_the_distro_family(distro: str, like: str, expected: str) -> None:
    """The failure names the package manager the contributor actually has."""
    hint = "\n".join(PREFLIGHT.install_hint({"ID": distro, "ID_LIKE": like}))
    assert expected in hint


def test_debian_hint_points_older_releases_at_the_installer() -> None:
    """Debian 12 cannot build PyGObject 3.56, so the hint says what works."""
    hint = "\n".join(PREFLIGHT.install_hint({"ID": "debian", "ID_LIKE": ""}))
    assert "sudo apt install" in hint
    assert "./install.sh --dev" in hint


def test_fedora_hint_keeps_the_split_cairo_gobject_package() -> None:
    """Fedora splits cairo-gobject.pc and girepository-2.0.pc across packages."""
    hint = "\n".join(PREFLIGHT.install_hint({"ID": "fedora", "ID_LIKE": ""}))
    assert "cairo-gobject-devel" in hint
    assert "glib2-devel" in hint


def test_old_fedora_hint_points_at_the_installer() -> None:
    """Installing more headers cannot make Fedora 39's glib new enough."""
    hint = "\n".join(PREFLIGHT.install_hint({"ID": "fedora", "VERSION_ID": "39"}))
    assert "./install.sh --dev" in hint
    assert "sudo dnf install" not in hint


def test_unknown_distro_gets_a_generic_hint() -> None:
    """No false package-manager command when the family is unknown."""
    hint = "\n".join(PREFLIGHT.install_hint({"ID": "plan9", "ID_LIKE": ""}))
    assert "development packages" in hint
    assert "sudo " not in hint


def test_missing_pkg_config_is_reported_without_probing_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tool itself missing is the first actionable failure."""
    monkeypatch.setattr(
        PREFLIGHT.shutil,
        "which",
        lambda name: "/usr/bin/cc" if name == "cc" else None,
    )

    def fail_run(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("pkg-config cannot be queried when it is absent")

    monkeypatch.setattr(PREFLIGHT.subprocess, "run", fail_run)

    assert PREFLIGHT.missing_build_dependencies() == ["pkg-config"]


def test_missing_modules_keep_their_explanations(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every absent pkg-config module is reported with the package it comes from."""
    monkeypatch.setattr(PREFLIGHT.shutil, "which", lambda name: f"/usr/bin/{name}")

    class Result:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode

    def fake_run(args: list[str], **kwargs: Any) -> Result:
        return Result(0 if args[-1] == "portaudio-2.0" else 1)

    monkeypatch.setattr(PREFLIGHT.subprocess, "run", fake_run)

    missing = PREFLIGHT.missing_build_dependencies()
    assert any("cairo headers" in item for item in missing)
    assert any("libffi" in item for item in missing)
    assert not any("portaudio" in item.lower() for item in missing)


def test_girepository_requires_glib_280(monkeypatch: pytest.MonkeyPatch) -> None:
    """A too-old girepository-2.0.pc must not pass the preflight."""
    monkeypatch.setattr(PREFLIGHT.shutil, "which", lambda name: f"/usr/bin/{name}")
    checked: list[list[str]] = []

    class Result:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode

    def fake_run(args: list[str], **kwargs: Any) -> Result:
        checked.append(args)
        return Result(1 if args[-1] == "girepository-2.0" else 0)

    monkeypatch.setattr(PREFLIGHT.subprocess, "run", fake_run)

    assert PREFLIGHT.missing_build_dependencies() == ["GObject Introspection headers (glib 2.80+)"]
    assert ["pkg-config", "--atleast-version=2.80", "girepository-2.0"] in checked


def test_fresh_macos_environment_does_not_need_gi_headers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """PyAudio's build prerequisites suffice when the lock excludes PyGObject."""
    monkeypatch.setattr(PREFLIGHT.sys, "platform", "darwin")
    monkeypatch.setattr(PREFLIGHT, "VENV_PYTHON", tmp_path / "absent-python")
    monkeypatch.setattr(PREFLIGHT.shutil, "which", lambda name: f"/usr/bin/{name}")
    checked: list[str] = []

    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        checked.append(args[-1])
        return subprocess.CompletedProcess(args, 0 if args[-1] == "portaudio-2.0" else 1)

    monkeypatch.setattr(PREFLIGHT.subprocess, "run", fake_run)

    assert PREFLIGHT.main() == 0
    assert checked == ["portaudio-2.0"]


@pytest.mark.parametrize(
    "platform,installed,expected",
    [
        ("darwin", {"pyaudio"}, True),
        ("darwin", set(), False),
        ("linux", {"pyaudio"}, False),
        ("linux", {"pyaudio", "pygobject"}, False),
        ("linux", {"pyaudio", "pycairo"}, False),
        ("linux", {"pyaudio", "pycairo", "pygobject"}, True),
    ],
)
def test_venv_probe_matches_platform_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    platform: str,
    installed: set[str],
    expected: bool,
) -> None:
    """Run the metadata probe against complete and partial per-platform environments."""
    monkeypatch.setattr(PREFLIGHT.sys, "platform", platform)
    python = tmp_path / "python"
    python.touch()
    monkeypatch.setattr(PREFLIGHT, "VENV_PYTHON", python)

    def version(package: str) -> str:
        if package not in installed:
            raise importlib.metadata.PackageNotFoundError(package)
        return "1.0"

    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert args[:2] == [str(python), "-c"]
        try:
            exec(args[2], {})
        except importlib.metadata.PackageNotFoundError:
            return subprocess.CompletedProcess(args, 1)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(importlib.metadata, "version", version)
    monkeypatch.setattr(PREFLIGHT.subprocess, "run", fake_run)

    assert PREFLIGHT.venv_has_compiled_packages() is expected


def test_macos_missing_portaudio_has_no_gi_install_hint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Failure guidance should request only packages macOS tooling actually needs."""
    monkeypatch.setattr(PREFLIGHT.sys, "platform", "darwin")
    monkeypatch.setattr(PREFLIGHT, "VENV_PYTHON", tmp_path / "absent-python")
    monkeypatch.setattr(PREFLIGHT.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        PREFLIGHT.subprocess, "run", lambda args, **kwargs: subprocess.CompletedProcess(args, 1)
    )

    assert PREFLIGHT.main() == 1
    error = capsys.readouterr().err
    assert "PortAudio headers" in error
    assert "brew install portaudio pkg-config" in error
    assert "xcode-select --install" in error
    assert "PyGObject" not in error
    assert "cairo" not in error
    assert "libffi" not in error


def test_existing_environment_short_circuits_the_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """An environment that already holds its native packages needs no header check."""
    monkeypatch.setattr(PREFLIGHT, "venv_has_compiled_packages", lambda: True)
    monkeypatch.setattr(
        PREFLIGHT,
        "missing_build_dependencies",
        lambda: pytest.fail("the preflight should not inspect headers"),
    )

    assert PREFLIGHT.main() == 0


def test_missing_dependencies_fail_with_install_commands(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The default failure is the actionable report, not a compiler traceback."""
    monkeypatch.setattr(PREFLIGHT, "venv_has_compiled_packages", lambda: False)
    monkeypatch.setattr(
        PREFLIGHT, "missing_build_dependencies", lambda: ["PortAudio headers (pyaudio)"]
    )
    monkeypatch.setattr(PREFLIGHT, "read_os_release", lambda: {"ID": "fedora"})

    assert PREFLIGHT.main() == 1

    error = capsys.readouterr().err
    assert "missing native build dependencies" in error
    assert "PortAudio headers (pyaudio)" in error
    assert "sudo dnf install" in error
    assert "CONTRIBUTING.md" in error
