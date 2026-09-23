"""Optional Orukeet catalog and publisher-manifest verification."""

import json
from pathlib import Path

import pytest

from vocalinux.utils import parakeet_model_info as models
from vocalinux.utils.model_checksums import ChecksumError, expected_for

MODEL = "orukeet-v0.1.0"


def test_orukeet_is_optional_and_keeps_license_files() -> None:
    assert models.RECOMMENDED_MODEL == "v3-european"
    assert models.MODEL_SIZES[:2] == ["v3-european", "v2-english"]
    assert models.model_files("v3-european") == models.MODEL_FILES
    assert models.model_files(MODEL)[0] == "manifest.json"
    assert {"LICENSE-WEIGHTS", "NOTICE.md"} <= set(models.model_files(MODEL))
    assert models.get_model_file_url(MODEL, "encoder.int8.onnx") == (
        "https://huggingface.co/oruk/orukeet/resolve/"
        "eac739d754bb171287930e6e63386f5b88f8179e/onnx/sherpa-v0.1.0-int8/"
        "encoder.int8.onnx?download=true"
    )


def test_release_manifest_must_agree_with_every_pinned_file(tmp_path) -> None:
    files = []
    for name in models.model_files(MODEL):
        if name == "manifest.json":
            continue
        expected = expected_for(models.manifest_key(MODEL, name))
        assert expected is not None
        files.append({"path": name, "sha256": expected.digest, "bytes": expected.size})
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"files": files}), encoding="utf-8")
    models.validate_release_manifest(MODEL, str(tmp_path))
    files[0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps({"files": files}), encoding="utf-8")
    with pytest.raises(ChecksumError, match="disagrees"):
        models.validate_release_manifest(MODEL, str(tmp_path))


def test_missing_manifest_or_license_keeps_model_unavailable(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(models, "get_model_path", lambda _: str(tmp_path))
    for name in models.model_files(MODEL):
        (tmp_path / name).touch()
    assert models.is_model_downloaded(MODEL)
    (tmp_path / "NOTICE.md").unlink()
    assert not models.is_model_downloaded(MODEL)
    (tmp_path / "NOTICE.md").touch()
    (tmp_path / "manifest.json").unlink()
    assert not models.is_model_downloaded(MODEL)


@pytest.mark.parametrize(
    "content",
    ["{", "null", "{}", '{"files": null}', '{"files": [{}]}', '{"files": [1]}'],
)
def test_malformed_release_manifest_is_a_verification_failure(tmp_path: Path, content: str) -> None:
    (tmp_path / "manifest.json").write_text(content, encoding="utf-8")
    with pytest.raises(ChecksumError, match="Malformed"):
        models.validate_release_manifest(MODEL, str(tmp_path))
