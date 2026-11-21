"""Unit tests for the Flatpak dependency artifact selector."""

import importlib.util
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync_flatpak_deps.py"
SPEC = importlib.util.spec_from_file_location("sync_flatpak_deps", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
SYNC: Any = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SYNC)


def _wheel(filename: str, digest: str) -> dict[str, object]:
    """Return a small PyPI wheel record for artifact selection tests."""
    return {
        "packagetype": "bdist_wheel",
        "filename": filename,
        "digests": {"sha256": digest},
        "url": f"https://example.invalid/{filename}",
    }


def _install_artifacts(monkeypatch: pytest.MonkeyPatch, artifacts: list[dict[str, object]]) -> None:
    """Replace the PyPI lookup with deterministic artifact records."""

    def fake_pypi_artifacts(name: str, version: str) -> list[dict[str, object]]:
        return artifacts

    monkeypatch.setattr(SYNC, "pypi_artifacts", fake_pypi_artifacts)


def test_binary_only_selection_uses_matching_cpython_architecture_wheel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Select the locked cp313 x86_64 wheel, not other ABI or arch variants."""
    artifacts = [
        _wheel("onnxruntime-1.29.0-cp313-cp313t-manylinux_2_28_x86_64.whl", "a" * 64),
        _wheel("onnxruntime-1.29.0-cp312-cp312-manylinux_2_28_x86_64.whl", "b" * 64),
        _wheel("onnxruntime-1.29.0-cp313-cp313-manylinux_2_28_aarch64.whl", "c" * 64),
        _wheel("onnxruntime-1.29.0-cp313-cp313-manylinux_2_28_x86_64.whl", "d" * 64),
    ]
    _install_artifacts(monkeypatch, artifacts)

    selected = SYNC.choose_artifact(
        "onnxruntime",
        "1.29.0",
        {"a" * 64, "b" * 64, "c" * 64, "d" * 64},
        arch="x86_64",
    )

    assert selected == (artifacts[-1]["url"], "d" * 64)


def test_binary_only_selection_fails_when_matching_wheel_digest_is_not_locked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not select a compatible wheel unless uv recorded its digest."""
    wheel = _wheel("onnxruntime-1.29.0-cp313-cp313-manylinux_2_28_x86_64.whl", "e" * 64)
    _install_artifacts(monkeypatch, [wheel])

    with pytest.raises(SystemExit, match="not among the hashes uv locked"):
        SYNC.choose_artifact("onnxruntime", "1.29.0", {"f" * 64}, arch="x86_64")


def test_non_binary_selection_prefers_universal_wheel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-binary dependencies retain the universal-wheel preference."""
    source = _wheel("sample-1.0.tar.gz", "1" * 64)
    source["packagetype"] = "sdist"
    universal = _wheel("sample-1.0-py3-none-any.whl", "2" * 64)
    _install_artifacts(monkeypatch, [source, universal])

    selected = SYNC.choose_artifact("sample", "1.0", {"1" * 64, "2" * 64})

    assert selected == (universal["url"], "2" * 64)


@pytest.mark.parametrize("arch", ["x86_64", "aarch64"])
def test_binary_only_selection_accepts_py3_none_manylinux2014_wheels(
    monkeypatch: pytest.MonkeyPatch,
    arch: str,
) -> None:
    """sherpa-onnx-core ships py3-none-manylinux2014 wheels per Flatpak arch."""
    other_arch = "aarch64" if arch == "x86_64" else "x86_64"
    expected = _wheel(f"sherpa_onnx_core-1.13.7-py3-none-manylinux2014_{arch}.whl", "1" * 64)
    artifacts = [
        _wheel(f"sherpa_onnx_core-1.13.7-py3-none-android_24_{arch}.whl", "2" * 64),
        _wheel("sherpa_onnx_core-1.13.7-py3-none-macosx_10_15_x86_64.whl", "3" * 64),
        _wheel("sherpa_onnx_core-1.13.7-py3-none-manylinux_2_35_armv7l.whl", "4" * 64),
        _wheel(f"sherpa_onnx_core-1.13.7-py3-none-manylinux2014_{other_arch}.whl", "5" * 64),
        expected,
    ]
    _install_artifacts(monkeypatch, artifacts)

    selected = SYNC.choose_artifact(
        "sherpa-onnx-core",
        "1.13.7",
        {"1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64},
        arch=arch,
    )

    assert selected == (expected["url"], "1" * 64)


@pytest.mark.parametrize("arch", ["x86_64", "aarch64"])
def test_binary_only_selection_accepts_compound_manylinux2014_tags(
    monkeypatch: pytest.MonkeyPatch,
    arch: str,
) -> None:
    """sherpa-onnx ships compound manylinux2014.<pep600> cp313 wheels per arch."""
    other_arch = "aarch64" if arch == "x86_64" else "x86_64"
    expected = _wheel(
        f"sherpa_onnx-1.13.7-cp313-cp313-manylinux2014_{arch}.manylinux_2_17_{arch}.whl",
        "a" * 64,
    )
    artifacts = [
        _wheel("sherpa_onnx-1.13.7-cp313-cp313-linux_armv7l.whl", "b" * 64),
        _wheel(
            f"sherpa_onnx-1.13.7-cp312-cp312-manylinux2014_{arch}.manylinux_2_17_{arch}.whl",
            "c" * 64,
        ),
        _wheel(
            f"sherpa_onnx-1.13.7-cp313-cp313t-manylinux2014_{arch}.manylinux_2_17_{arch}.whl",
            "d" * 64,
        ),
        _wheel(
            f"sherpa_onnx-1.13.7-cp313-cp313-manylinux2014_{other_arch}.manylinux_2_17_{other_arch}.whl",
            "e" * 64,
        ),
        expected,
    ]
    _install_artifacts(monkeypatch, artifacts)

    selected = SYNC.choose_artifact(
        "sherpa-onnx",
        "1.13.7",
        {"a" * 64, "b" * 64, "c" * 64, "d" * 64, "e" * 64},
        arch=arch,
    )

    assert selected == (expected["url"], "a" * 64)


def test_parse_exports_merges_shared_and_extra_packages(tmp_path: Path) -> None:
    """parse_exports unions hashes for shared packages and keeps unique extras."""
    vad = tmp_path / "vad.txt"
    parakeet = tmp_path / "parakeet.txt"
    vad.write_text(
        f"shared==1.0.0 \\\n    --hash=sha256:{'a' * 64}\n"
        f"onnxruntime==1.29.0 \\\n    --hash=sha256:{'b' * 64}\n",
        encoding="utf-8",
    )
    parakeet.write_text(
        f"shared==1.0.0 \\\n    --hash=sha256:{'c' * 64}\n"
        f"sherpa-onnx==1.13.7 \\\n    --hash=sha256:{'d' * 64}\n",
        encoding="utf-8",
    )

    merged = SYNC.parse_exports((vad, parakeet))

    assert merged == {
        "shared": ("1.0.0", {"a" * 64, "c" * 64}),
        "onnxruntime": ("1.29.0", {"b" * 64}),
        "sherpa-onnx": ("1.13.7", {"d" * 64}),
    }


def test_parse_exports_rejects_version_mismatch_across_exports(tmp_path: Path) -> None:
    """Conflicting versions across exports fail loudly instead of picking one."""
    vad = tmp_path / "vad.txt"
    parakeet = tmp_path / "parakeet.txt"
    vad.write_text(
        f"shared==1.0.0 \\\n    --hash=sha256:{'a' * 64}\n",
        encoding="utf-8",
    )
    parakeet.write_text(
        f"shared==2.0.0 \\\n    --hash=sha256:{'b' * 64}\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="resolves to 1.0.0 and 2.0.0"):
        SYNC.parse_exports((vad, parakeet))
