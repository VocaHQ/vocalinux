"""The AppImage reuses its pywhispercpp Vulkan build only when the pins match.

The compile does not depend on the Vocalinux commit. The cache id is the base
image, tool_checksums.txt, the pinned cmake and ninja, the Vulkan flags, and
the pywhispercpp pin. It is not the git SHA and not the Actions run id. A tree
without libggml-vulkan.so is a CPU wheel and is not cached.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APPIMAGE = REPO_ROOT / "packaging" / "appimage"
ID_SCRIPT = APPIMAGE / "native-cache-id.sh"
CACHE_SH = APPIMAGE / "native-cache.sh"
BUILD_SH = APPIMAGE / "build.sh"
PINS = APPIMAGE / "tool_checksums.txt"
INSTALL_SH = REPO_ROOT / "install.sh"
TOOLS = REPO_ROOT / "requirements" / "appimage-tools.txt"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
APPIMAGE_WORKFLOWS = ("unified-pipeline.yml", "release.yml", "nightly.yml")
NATIVE_KEY = "appimage-native-${{ runner.arch }}-${{ steps.native-cache.outputs.id }}"


def _run(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy() if env is None else env,
    )


def _cache_id(pins: Path, install: Path, extra: dict[str, str] | None = None) -> str:
    env = os.environ.copy()
    env["VOCALINUX_PINS"] = str(pins)
    env["VOCALINUX_INSTALL_SH"] = str(install)
    if extra:
        env.update(extra)
    result = _run(["bash", str(ID_SCRIPT)], env=env)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _source(body: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    script = "set -euo pipefail\nsource " + shlex.quote(str(CACHE_SH)) + "\n" + body + "\n"
    return _run(["bash", "-c", script], env=env)


def _flip_pin_value(text: str, name: str) -> str:
    """Change the value column of one tool_checksums.txt row."""
    pattern = re.compile(rf"^({re.escape(name)}\s+\S+\s+)(\S+)", re.M)
    match = pattern.search(text)
    assert match, name
    value = match.group(2)
    replacement = "0" if value[-1] != "0" else "1"
    return text[: match.start(2)] + value[:-1] + replacement + text[match.end(2) :]


def test_native_cache_id_tracks_base_image_pins_and_pywhispercpp(tmp_path: Path) -> None:
    pins_text = PINS.read_text(encoding="utf-8")
    install_text = INSTALL_SH.read_text(encoding="utf-8")
    pins = tmp_path / "tool_checksums.txt"
    install = tmp_path / "install.sh"
    pins.write_text(pins_text, encoding="utf-8")
    install.write_text(install_text, encoding="utf-8")

    baseline = _cache_id(pins, install)
    assert baseline == _cache_id(PINS, INSTALL_SH)
    assert re.fullmatch(r"[0-9a-f]{64}", baseline)

    pins.write_text(_flip_pin_value(pins_text, "base-image"), encoding="utf-8")
    assert _cache_id(pins, install) != baseline

    pins.write_text(_flip_pin_value(pins_text, "shaderc"), encoding="utf-8")
    assert _cache_id(pins, install) != baseline

    pins.write_text(pins_text, encoding="utf-8")
    declared = re.search(r'^PYWHISPERCPP_VERSION="([^"]+)"', install_text, re.M)
    assert declared, "install.sh no longer declares the version the id reads"
    bumped = install_text.replace(
        f'PYWHISPERCPP_VERSION="{declared.group(1)}"',
        f'PYWHISPERCPP_VERSION="{declared.group(1)}.1"',
        1,
    )
    install.write_text(bumped, encoding="utf-8")
    bumped_id = _cache_id(pins, install)
    assert bumped_id != baseline

    with_sha = _cache_id(pins, install, extra={"GITHUB_SHA": "abc123", "GITHUB_RUN_ID": "11"})
    with_other = _cache_id(pins, install, extra={"GITHUB_SHA": "def456", "GITHUB_RUN_ID": "99"})
    assert with_sha == with_other == bumped_id


def test_native_cache_id_tracks_build_tools_and_compile_flags(tmp_path: Path) -> None:
    baseline = _cache_id(PINS, INSTALL_SH)
    tools = tmp_path / "appimage-tools.txt"
    tools_text = TOOLS.read_text(encoding="utf-8")
    tools.write_text(tools_text.replace("cmake", "cmake-other", 1), encoding="utf-8")
    changed_tools = _cache_id(PINS, INSTALL_SH, extra={"VOCALINUX_APPIMAGE_TOOLS": str(tools)})
    assert changed_tools != baseline

    commented = tmp_path / "build-comment.sh"
    build_text = BUILD_SH.read_text(encoding="utf-8")
    commented.write_text(
        build_text.replace("# GPU:", "# GPU: unchanged flags\n# GPU:", 1), encoding="utf-8"
    )
    assert _cache_id(PINS, INSTALL_SH, extra={"VOCALINUX_BUILD_SH": str(commented)}) == baseline

    flagged = tmp_path / "build-flags.sh"
    flagged.write_text(
        build_text.replace(
            "CMAKE_BUILD_WITH_INSTALL_RPATH=ON",
            "CMAKE_BUILD_WITH_INSTALL_RPATH=OFF",
            1,
        ),
        encoding="utf-8",
    )
    assert _cache_id(PINS, INSTALL_SH, extra={"VOCALINUX_BUILD_SH": str(flagged)}) != baseline


def test_native_cache_id_does_not_read_the_commit_or_the_run() -> None:
    text = ID_SCRIPT.read_text(encoding="utf-8")
    assert "base-image" in text
    assert "PYWHISPERCPP_VERSION" in text
    assert 'sha256sum "$pins"' in text
    assert 'sha256sum "$tools"' in text
    assert "appimage-tools.txt" in text
    assert "CMAKE_ARGS=" in text
    for banned in (
        "GITHUB_SHA",
        "github.sha",
        "GITHUB_RUN_ID",
        "github.run_id",
        "github.run_number",
        "rev-parse",
    ):
        assert banned not in text, banned


def test_publish_refuses_a_cpu_only_tree_and_leaves_no_cache(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "pywhispercpp").mkdir()
    (site / "_pywhispercpp.cpython-312-x86_64-linux-gnu.so").write_bytes(b"cpu")
    dest = tmp_path / "cache" / "pywhispercpp-vulkan"
    result = _source(
        "pywhispercpp_cache_publish " + shlex.quote(str(site)) + " " + shlex.quote(str(dest))
    )
    assert result.returncode != 0
    assert "libggml-vulkan" in result.stderr
    assert not dest.exists()
    assert list((tmp_path / "cache").glob(".pywhispercpp-staging-*")) == []


def test_publish_keeps_the_previous_cache_when_a_copy_fails(tmp_path: Path) -> None:
    site = tmp_path / "built"
    (site / "pywhispercpp").mkdir(parents=True)
    (site / "pywhispercpp" / "secret").write_text("full", encoding="utf-8")
    (site / "libggml-vulkan.so").write_bytes(b"new")
    os.chmod(site / "pywhispercpp", 0)
    dest = tmp_path / "cache" / "tree"
    dest.mkdir(parents=True)
    (dest / "libggml-vulkan.so").write_bytes(b"old-good")
    try:
        result = _source(
            "pywhispercpp_cache_publish " + shlex.quote(str(site)) + " " + shlex.quote(str(dest))
        )
    finally:
        os.chmod(site / "pywhispercpp", 0o755)
    assert result.returncode != 0
    assert "Failed to copy" in result.stderr
    assert (dest / "libggml-vulkan.so").read_bytes() == b"old-good"
    assert list((tmp_path / "cache").glob(".pywhispercpp-staging-*")) == []


def test_restore_refuses_a_cpu_tree_without_touching_the_prefix(tmp_path: Path) -> None:
    src = tmp_path / "cache"
    src.mkdir()
    (src / "_pywhispercpp.cpython-312-x86_64-linux-gnu.so").write_bytes(b"cpu")
    site = tmp_path / "site"
    (site / "numpy").mkdir(parents=True)
    (site / "numpy" / "keep.txt").write_text("stay", encoding="utf-8")
    result = _source(
        "pywhispercpp_cache_restore " + shlex.quote(str(src)) + " " + shlex.quote(str(site))
    )
    assert result.returncode != 0
    assert (site / "numpy" / "keep.txt").read_text(encoding="utf-8") == "stay"
    assert (site / "_pywhispercpp.cpython-312-x86_64-linux-gnu.so").exists() is False


def test_publish_and_restore_round_trip_the_vulkan_tree_only(tmp_path: Path) -> None:
    site = tmp_path / "built"
    (site / "pywhispercpp").mkdir(parents=True)
    (site / "pywhispercpp" / "marker.txt").write_text("vulkan-package", encoding="utf-8")
    (site / "pywhispercpp-1.5.0.dist-info").mkdir()
    (site / "pywhispercpp-1.5.0.dist-info" / "METADATA").write_text(
        "Name: pywhispercpp\n", encoding="utf-8"
    )
    (site / "_pywhispercpp.cpython-312-x86_64-linux-gnu.so").write_bytes(b"ext")
    (site / "libggml-vulkan.so.0.9.8").write_bytes(b"vulkan-bytes")
    (site / "libggml-vulkan.so").symlink_to("libggml-vulkan.so.0.9.8")
    (site / "libwhisper.so.1").write_bytes(b"whisper")
    (site / "numpy").mkdir()
    (site / "numpy" / "nope.txt").write_text("not-native", encoding="utf-8")

    dest = tmp_path / "cache" / "tree"
    published = _source(
        "pywhispercpp_cache_publish " + shlex.quote(str(site)) + " " + shlex.quote(str(dest))
    )
    assert published.returncode == 0, published.stderr
    assert not (dest / "numpy").exists()
    assert (dest / "libggml-vulkan.so").is_symlink()
    assert (dest / "libggml-vulkan.so").read_bytes() == b"vulkan-bytes"

    restored = tmp_path / "prefix"
    (restored / "numpy").mkdir(parents=True)
    (restored / "numpy" / "keep.txt").write_text("stay", encoding="utf-8")
    (restored / "pywhispercpp").mkdir()
    (restored / "pywhispercpp" / "marker.txt").write_text("cpu-package", encoding="utf-8")
    (restored / "pywhispercpp.libs").mkdir()
    (restored / "pywhispercpp.libs" / "cpu.so").write_bytes(b"cpu")
    (restored / "_pywhispercpp.cpython-312-x86_64-linux-gnu.so").write_bytes(b"cpu-ext")

    result = _source(
        "pywhispercpp_cache_restore " + shlex.quote(str(dest)) + " " + shlex.quote(str(restored))
    )
    assert result.returncode == 0, result.stderr
    marker = (restored / "pywhispercpp" / "marker.txt").read_text(encoding="utf-8")
    assert marker == "vulkan-package"
    assert (restored / "libggml-vulkan.so").read_bytes() == b"vulkan-bytes"
    assert (restored / "_pywhispercpp.cpython-312-x86_64-linux-gnu.so").read_bytes() == b"ext"
    assert (restored / "libwhisper.so.1").read_bytes() == b"whisper"
    assert not (restored / "pywhispercpp.libs").exists()
    assert (restored / "numpy" / "keep.txt").read_text(encoding="utf-8") == "stay"
    assert not (restored / "numpy" / "nope.txt").exists()


def _quote(path: Path) -> str:
    return shlex.quote(str(path))


def test_a_cache_hit_does_not_run_the_compile_command(tmp_path: Path) -> None:
    site = tmp_path / "built"
    (site / "pywhispercpp").mkdir(parents=True)
    (site / "libggml-vulkan.so").write_bytes(b"vulkan-bytes")
    cache = tmp_path / "cache" / "tree"
    published = _source("pywhispercpp_cache_publish " + _quote(site) + " " + _quote(cache))
    assert published.returncode == 0, published.stderr
    fresh = tmp_path / "prefix"
    fresh.mkdir()
    marker = tmp_path / "compiled"
    reused = tmp_path / "reused"
    result = _source(
        "on_reuse() { printf reused > "
        + _quote(reused)
        + "; }\n"
        + "compile() { printf compiled > "
        + _quote(marker)
        + "; }\n"
        + "pywhispercpp_restore_or_run "
        + _quote(cache)
        + " "
        + _quote(fresh)
        + " on_reuse compile"
    )
    assert result.returncode == 0, result.stderr
    assert reused.read_text(encoding="utf-8") == "reused"
    assert not marker.exists()
    assert (fresh / "libggml-vulkan.so").read_bytes() == b"vulkan-bytes"
    assert "Rebuilding pywhispercpp with Vulkan" not in result.stdout


def test_a_failed_restore_runs_the_compile_command(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "libggml-vulkan.so").write_bytes(b"vulkan-bytes")
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("file", encoding="utf-8")
    site = blocker / "site"
    marker = tmp_path / "compiled"
    reused = tmp_path / "reused"
    result = _source(
        "on_reuse() { printf reused > "
        + _quote(reused)
        + "; }\n"
        + "compile() { printf compiled > "
        + _quote(marker)
        + "; }\n"
        + "pywhispercpp_restore_or_run "
        + _quote(cache)
        + " "
        + _quote(site)
        + " on_reuse compile"
    )
    assert result.returncode == 0, result.stderr
    assert marker.read_text(encoding="utf-8") == "compiled"
    assert not reused.exists()
    assert "compiling again" in result.stderr


def test_native_cache_dir_binds_the_arch_to_that_id(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["VOCALINUX_APPIMAGE_CACHE"] = str(tmp_path / "cache")
    env.pop("VOCALINUX_PINS", None)
    env.pop("VOCALINUX_INSTALL_SH", None)
    env.pop("VOCALINUX_APPIMAGE_TOOLS", None)
    env.pop("VOCALINUX_BUILD_SH", None)
    result = _source("pywhispercpp_native_cache_dir x86_64", env=env)
    assert result.returncode == 0, result.stderr
    expected = _cache_id(PINS, INSTALL_SH)
    assert Path(result.stdout.strip()) == (
        tmp_path / "cache" / f"pywhispercpp-vulkan-x86_64-{expected}"
    )

    arm = _source("pywhispercpp_native_cache_dir aarch64", env=env)
    assert arm.returncode == 0, arm.stderr
    assert Path(arm.stdout.strip()) == (
        tmp_path / "cache" / f"pywhispercpp-vulkan-aarch64-{expected}"
    )


def test_build_reuses_the_cached_vulkan_tree_before_compiling() -> None:
    text = BUILD_SH.read_text(encoding="utf-8")
    match = re.search(r"\nrebuild_pywhispercpp_vulkan\(\) \{(.+?)\n\}\n", text, re.S)
    assert match, "rebuild_pywhispercpp_vulkan disappeared"
    body = match.group(1)
    assert body.index("VOCALINUX_APPIMAGE_SKIP_VULKAN") < body.index("pywhispercpp_restore_or_run")
    assert "GGML_VULKAN=1" not in body
    assert "_compile_pywhispercpp_vulkan" in body
    compile_fn = re.search(r"\n_compile_pywhispercpp_vulkan\(\) \{(.+?)\n\}\n", text, re.S)
    assert compile_fn, "the compile path disappeared"
    compile_body = compile_fn.group(1)
    assert "GGML_VULKAN=1" in compile_body
    missing_lib = compile_body.index("did not produce libggml-vulkan.so")
    assert missing_lib < compile_body.index("pywhispercpp_cache_publish")
    assert "native-cache.sh" in text


def test_appimage_workflows_share_one_native_cache_key() -> None:
    """CI, Nightly, and Release have to miss together when a pin changes, and
    hit together otherwise. A key that includes the commit never hits."""
    keys = []
    for name in APPIMAGE_WORKFLOWS:
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        found = re.findall(r"path: ~/.cache/vocalinux-appimage\n\s+key: (.+)\n", text)
        assert found, name
        assert all(key == NATIVE_KEY for key in found), found
        for token in ("github.sha", "github.run_id", "github.run_number", "github.run_attempt"):
            assert token not in NATIVE_KEY
        id_steps = re.findall(
            r"- name: AppImage native cache id\n.*?(?=- name: Cache AppImage build tools)",
            text,
            re.S,
        )
        assert len(id_steps) == len(found)
        for step in id_steps:
            assert 'id="$(bash packaging/appimage/native-cache-id.sh)"' in step
            assert 'echo "id=${id}"' in step
            for token in ("github.sha", "github.run_id", "github.run_number", "github.run_attempt"):
                assert token not in step, step
        assert "packaging/appimage/docker-build.sh" in text
        assert 'VOCALINUX_APPIMAGE_REQUIRE_VULKAN: "1"' in text
        assert "aarch64" in text
        keys.extend(found)
    assert len(keys) == 5
    assert len(set(keys)) == 1
