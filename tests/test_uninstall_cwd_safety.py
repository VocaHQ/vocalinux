"""uninstall.sh must not delete the caller's working directory.

The website runs ``bash /tmp/vul.sh`` from whatever directory the terminal is
in. ``venv/``, ``build/``, ``dist/``, and Python bytecode are removed only when
the script itself lives in a Vocalinux source checkout, and only inside that
checkout.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
UNINSTALL_SH = REPO_ROOT / "uninstall.sh"


def _write_script(dest: Path) -> None:
    dest.write_bytes(UNINSTALL_SH.read_bytes())
    dest.chmod(0o755)


def _decoy_tree(root: Path) -> None:
    """Files a careless ``find .`` / ``rm -rf venv`` would destroy."""
    package = root / "proj" / "pkg"
    cache = package / "__pycache__"
    cache.mkdir(parents=True)
    (package / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (cache / "mod.cpython-312.pyc").write_bytes(b"pyc")
    (root / "bytecode-only.pyc").write_bytes(b"pyc")
    (root / "bytecode-only.pyo").write_bytes(b"pyo")
    (root / "venv" / "bin").mkdir(parents=True)
    (root / "venv" / "bin" / "python").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / "build").mkdir()
    (root / "build" / "out").write_text("build", encoding="utf-8")
    (root / "dist").mkdir()
    (root / "dist" / "pkg.whl").write_text("wheel", encoding="utf-8")
    (root / "notes.txt").write_text("keep", encoding="utf-8")
    (root / ".pytest_cache").mkdir()
    (root / ".coverage").write_text("cov", encoding="utf-8")
    (root / "src" / "pkg.egg-info").mkdir(parents=True)
    (root / "activate-vocalinux.sh").write_text("echo hi\n", encoding="utf-8")
    (root / "vocalinux-run.py").write_text("print(1)\n", encoding="utf-8")


def _assert_decoy_intact(root: Path) -> None:
    assert (root / "notes.txt").read_text(encoding="utf-8") == "keep"
    assert (root / "proj" / "pkg" / "mod.py").is_file()
    assert (root / "proj" / "pkg" / "__pycache__" / "mod.cpython-312.pyc").is_file()
    assert (root / "bytecode-only.pyc").is_file()
    assert (root / "bytecode-only.pyo").is_file()
    assert (root / "venv" / "bin" / "python").is_file()
    assert (root / "build" / "out").is_file()
    assert (root / "dist" / "pkg.whl").is_file()
    assert (root / ".pytest_cache").is_dir()
    assert (root / ".coverage").is_file()
    assert (root / "src" / "pkg.egg-info").is_dir()
    assert (root / "activate-vocalinux.sh").is_file()
    assert (root / "vocalinux-run.py").is_file()


def _make_checkout(root: Path) -> Path:
    checkout = root / "vocalinux"
    (checkout / "src" / "vocalinux").mkdir(parents=True)
    (checkout / "pyproject.toml").write_text(
        '[project]\nname = "vocalinux"\n',
        encoding="utf-8",
    )
    (checkout / "src" / "vocalinux" / "__init__.py").write_text("", encoding="utf-8")
    _write_script(checkout / "uninstall.sh")
    return checkout


def _write_stub(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _run(script: Path, cwd: Path, home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run uninstall.sh against a fake home, without the host's pgrep or kill.

    The uninstaller looks up this uid's processes and can TERM then KILL a
    running Vocalinux. A stub earlier on PATH records the call and matches
    nothing, so the suite cannot stop the app a developer has open.
    """
    bin_dir = home.parent / "uninstall-test-bin"
    bin_dir.mkdir(exist_ok=True)
    pgrep_log = home.parent / "pgrep.log"
    kill_log = home.parent / "kill.log"
    _write_stub(
        bin_dir / "pgrep",
        "#!/bin/sh\n" 'printf \'%s\\n\' "$*" >> "$VOCALINUX_TEST_PGREP_LOG"\n' "exit 1\n",
    )
    _write_stub(
        bin_dir / "kill",
        "#!/bin/sh\n" 'printf \'%s\\n\' "$*" >> "$VOCALINUX_TEST_KILL_LOG"\n' "exit 0\n",
    )
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = os.pathsep.join((str(bin_dir), env.get("PATH", "")))
    env["VOCALINUX_TEST_PGREP_LOG"] = str(pgrep_log)
    env["VOCALINUX_TEST_KILL_LOG"] = str(kill_log)
    env.pop("XDG_DATA_HOME", None)
    env.pop("XDG_CONFIG_HOME", None)
    env.pop("VIRTUAL_ENV", None)
    result = subprocess.run(
        ["bash", str(script), "-y", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    if "Checking for running Vocalinux processes" in result.stdout:
        logged = pgrep_log.read_text(encoding="utf-8") if pgrep_log.is_file() else ""
        assert "vocalinux" in logged, "uninstall.sh did not use the test pgrep stub"
    if kill_log.is_file():
        assert kill_log.read_text(encoding="utf-8").strip() == ""
    return result


def _output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def test_curl_style_run_leaves_the_callers_directory_alone(tmp_path: Path) -> None:
    """The reported repro: script in /tmp, junk under $PWD, fake home."""
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    _decoy_tree(cwd)
    script = tmp_path / "vul.sh"
    _write_script(script)

    data = home / ".local" / "share" / "vocalinux"
    config = home / ".config" / "vocalinux"
    data.mkdir(parents=True)
    (data / "marker").write_text("data", encoding="utf-8")
    (data / "venv").mkdir()
    (data / "venv" / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    config.mkdir(parents=True)
    (config / "config.json").write_text("{}\n", encoding="utf-8")
    bindir = home / ".local" / "bin"
    bindir.mkdir(parents=True)
    (bindir / "vocalinux").write_text("#!/bin/sh\n", encoding="utf-8")
    (bindir / "vocalinux-gui").symlink_to("vocalinux")
    (bindir / "activate-vocalinux.sh").write_text("echo\n", encoding="utf-8")
    desktop = home / ".local" / "share" / "applications"
    desktop.mkdir(parents=True)
    (desktop / "vocalinux.desktop").write_text("[Desktop Entry]\n", encoding="utf-8")

    result = _run(script, cwd, home)

    assert result.returncode == 0, _output(result)
    assert "skipping build-artifact cleanup" in result.stdout
    assert "Failed to remove some" not in _output(result)
    _assert_decoy_intact(cwd)
    assert not data.exists()
    assert not config.exists()
    assert not (bindir / "vocalinux").exists()
    assert not (bindir / "vocalinux-gui").exists()
    assert not (bindir / "activate-vocalinux.sh").exists()
    assert not (desktop / "vocalinux.desktop").exists()


def test_keep_flags_still_do_not_touch_the_working_directory(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    _decoy_tree(cwd)
    script = tmp_path / "vul.sh"
    _write_script(script)
    config = home / ".config" / "vocalinux"
    data = home / ".local" / "share" / "vocalinux"
    config.mkdir(parents=True)
    data.mkdir(parents=True)
    (config / "config.json").write_text("{}\n", encoding="utf-8")
    (data / "marker").write_text("data", encoding="utf-8")

    result = _run(script, cwd, home, "--keep-config", "--keep-data")

    assert result.returncode == 0, _output(result)
    _assert_decoy_intact(cwd)
    assert (config / "config.json").is_file()
    assert (data / "marker").is_file()


def test_source_checkout_cleans_itself_and_leaves_the_caller_alone(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    checkout = _make_checkout(tmp_path)
    _decoy_tree(checkout)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    _decoy_tree(cwd)

    result = _run(checkout / "uninstall.sh", cwd, home)

    assert result.returncode == 0, _output(result)
    assert "Failed to remove some" not in _output(result)
    _assert_decoy_intact(cwd)
    assert (checkout / "notes.txt").is_file()
    assert (checkout / "proj" / "pkg" / "mod.py").is_file()
    assert (checkout / "src" / "vocalinux" / "__init__.py").is_file()
    assert (checkout / "pyproject.toml").is_file()
    assert not (checkout / "venv").exists()
    assert not (checkout / "build").exists()
    assert not (checkout / "dist").exists()
    assert not (checkout / "bytecode-only.pyc").exists()
    assert not (checkout / "bytecode-only.pyo").exists()
    assert not (checkout / ".coverage").exists()
    assert not (checkout / ".pytest_cache").exists()
    assert not (checkout / "proj" / "pkg" / "__pycache__").exists()
    assert not (checkout / "src" / "pkg.egg-info").exists()
    assert not (checkout / "activate-vocalinux.sh").exists()
    assert not (checkout / "vocalinux-run.py").exists()


def test_dev_venv_records_survive_checkout_cleanup(tmp_path: Path) -> None:
    """`.venv` is the dev environment. Uninstall must not strip its metadata."""
    home = tmp_path / "home"
    home.mkdir()
    checkout = _make_checkout(tmp_path)
    _decoy_tree(checkout)
    dev_egg = checkout / ".venv" / "lib" / "python3.12" / "site-packages" / "dep.egg-info"
    dev_egg.mkdir(parents=True)
    (dev_egg / "PKG-INFO").write_text("Metadata-Version: 2.1\n", encoding="utf-8")
    dev_cache = checkout / ".venv" / "lib" / "python3.12" / "site-packages" / "dep" / "__pycache__"
    dev_cache.mkdir(parents=True)
    (dev_cache / "mod.cpython-312.pyc").write_bytes(b"pyc")
    (checkout / ".venv" / ".coverage").write_text("keep", encoding="utf-8")
    (checkout / "vocalinux.egg-info").mkdir()
    (checkout / "vocalinux.egg-info" / "PKG-INFO").write_text("name\n", encoding="utf-8")

    result = _run(checkout / "uninstall.sh", tmp_path, home)

    assert result.returncode == 0, _output(result)
    assert "Failed to remove some" not in _output(result)
    assert (dev_egg / "PKG-INFO").is_file()
    assert (dev_cache / "mod.cpython-312.pyc").is_file()
    assert (checkout / ".venv" / ".coverage").is_file()
    assert not (checkout / "src" / "pkg.egg-info").exists()
    assert not (checkout / "vocalinux.egg-info").exists()
    assert not (checkout / "proj" / "pkg" / "__pycache__").exists()
    assert not (checkout / ".coverage").exists()


def test_curl_clone_uninstall_does_not_print_a_cleanup_error(tmp_path: Path) -> None:
    """The cloned repo is a checkout, and uninstall deletes that same directory."""
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    (cwd / "notes.txt").write_text("keep", encoding="utf-8")
    clone = home / ".local" / "share" / "vocalinux-install"
    (clone / "src" / "vocalinux").mkdir(parents=True)
    (clone / "pyproject.toml").write_text('[project]\nname = "vocalinux"\n', encoding="utf-8")
    (clone / "src" / "vocalinux" / "__init__.py").write_text("", encoding="utf-8")
    (clone / "src" / "vocalinux.egg-info").mkdir()
    (clone / "build").mkdir()
    (clone / "build" / "out").write_text("build", encoding="utf-8")
    _write_script(clone / "uninstall.sh")

    result = _run(clone / "uninstall.sh", cwd, home)

    assert result.returncode == 0, _output(result)
    output = _output(result)
    assert "Refusing to clean build artifacts" not in output
    assert "[ERROR]" not in output
    assert "Failed to remove some" not in output
    assert "Uninstallation completed successfully" in result.stdout
    assert not clone.exists()
    assert (cwd / "notes.txt").read_text(encoding="utf-8") == "keep"


def test_running_inside_the_checkout_still_cleans_it(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    checkout = _make_checkout(tmp_path)
    _decoy_tree(checkout)

    result = _run(checkout / "uninstall.sh", checkout, home)

    assert result.returncode == 0, _output(result)
    assert (checkout / "proj" / "pkg" / "mod.py").is_file()
    assert not (checkout / "venv").exists()
    assert not (checkout / "bytecode-only.pyc").exists()
    assert not (checkout / "proj" / "pkg" / "__pycache__").exists()


def test_another_projects_tree_is_not_treated_as_a_checkout(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "other"
    (project / "src" / "vocalinux").mkdir(parents=True)
    (project / "pyproject.toml").write_text('name = "not-vocalinux"\n', encoding="utf-8")
    _write_script(project / "uninstall.sh")
    _decoy_tree(project)

    result = _run(project / "uninstall.sh", project, home)

    assert result.returncode == 0, _output(result)
    assert "skipping build-artifact cleanup" in result.stdout
    _assert_decoy_intact(project)


def test_relative_venv_dir_outside_a_checkout_is_refused(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    _decoy_tree(cwd)
    script = tmp_path / "vul.sh"
    _write_script(script)

    result = _run(script, cwd, home, "--venv-dir=venv")

    assert result.returncode == 1
    assert "Refusing relative --venv-dir" in result.stdout
    _assert_decoy_intact(cwd)


def test_relative_venv_dir_resolves_inside_the_checkout(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    checkout = _make_checkout(tmp_path)
    (checkout / "custom-venv" / "bin").mkdir(parents=True)
    (checkout / "custom-venv" / "bin" / "python").write_text("x", encoding="utf-8")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / "custom-venv" / "bin").mkdir(parents=True)
    (cwd / "custom-venv" / "bin" / "python").write_text("keep", encoding="utf-8")
    (cwd / "notes.txt").write_text("keep", encoding="utf-8")

    result = _run(checkout / "uninstall.sh", cwd, home, "--venv-dir=custom-venv")

    assert result.returncode == 0, _output(result)
    assert not (checkout / "custom-venv").exists()
    assert (cwd / "custom-venv" / "bin" / "python").read_text(encoding="utf-8") == "keep"
    assert (cwd / "notes.txt").is_file()


def test_absolute_venv_dir_is_removed_and_the_caller_is_not(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    _decoy_tree(cwd)
    extra = tmp_path / "custom-venv"
    (extra / "bin").mkdir(parents=True)
    (extra / "bin" / "python").write_text("x", encoding="utf-8")
    script = tmp_path / "vul.sh"
    _write_script(script)

    result = _run(script, cwd, home, f"--venv-dir={extra}")

    assert result.returncode == 0, _output(result)
    assert not extra.exists()
    _assert_decoy_intact(cwd)


def test_help_does_not_default_to_a_cwd_relative_venv() -> None:
    result = subprocess.run(
        ["bash", str(UNINSTALL_SH), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, _output(result)
    assert "default: venv" not in result.stdout
    assert "source checkout" in result.stdout


def test_build_artifact_search_stays_on_one_filesystem() -> None:
    source = UNINSTALL_SH.read_text(encoding="utf-8")
    cleanup = source.split("cleanup_build_artifacts() {", 1)[1].split("\n}", 1)[0]
    finds = [line.strip() for line in cleanup.splitlines() if line.strip().startswith("find ")]
    assert finds
    assert all("-xdev" in line for line in finds)


def test_uninstaller_is_valid_bash() -> None:
    syntax = subprocess.run(
        ["bash", "-n", str(UNINSTALL_SH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr


@pytest.mark.parametrize(
    "pyproject",
    [
        "",
        'name = "vocalinux"\n',
    ],
)
def test_checkout_detection_needs_both_the_name_and_the_package_dir(
    tmp_path: Path, pyproject: str
) -> None:
    """A pyproject alone, or the package dir without the project name, is not enough."""
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "partial"
    project.mkdir()
    if pyproject:
        (project / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    else:
        (project / "src" / "vocalinux").mkdir(parents=True)
    _write_script(project / "uninstall.sh")
    (project / "venv").mkdir()
    (project / "venv" / "marker").write_text("keep", encoding="utf-8")

    result = _run(project / "uninstall.sh", tmp_path, home)

    assert result.returncode == 0, _output(result)
    assert (project / "venv" / "marker").is_file()
    assert "skipping build-artifact cleanup" in result.stdout
