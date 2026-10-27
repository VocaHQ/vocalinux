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
