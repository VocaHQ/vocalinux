"""Behavioral tests for the installer's model integrity helpers."""

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

INSTALL_SH = Path(__file__).resolve().parents[1] / "install.sh"

_PRELUDE = """
print_warning() { echo "WARNING: $*"; }
print_info() { echo "INFO: $*"; }
print_success() { echo "SUCCESS: $*"; }
print_error() { echo "ERROR: $*"; }
"""


def _run(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)


def _source(*functions: str) -> str:
    return "\n".join(
        f"source <(sed -n '/^{name}()/,/^}}/p' \"{INSTALL_SH}\")" for name in functions
    )


def _registry(tmp_path: Path, entries: dict) -> Path:
    registry = tmp_path / "model_hashes.json"
    registry.write_text(json.dumps(entries))
    return registry


class TestVerifyModelSha256:
    def test_matching_digest_passes(self, tmp_path):
        model = tmp_path / "ggml-tiny.bin"
        model.write_bytes(b"weights")
        registry = _registry(
            tmp_path,
            {"whispercpp": {"ggml-tiny.bin": {"sha256": hashlib.sha256(b"weights").hexdigest()}}},
        )

        result = _run(
            f"{_PRELUDE}\n{_source('lookup_model_sha256', 'verify_model_sha256')}\n"
            f'MODEL_HASH_REGISTRY="{registry}"\n'
            f'verify_model_sha256 "{model}" whispercpp ggml-tiny.bin "tiny" '
            f"&& echo PASS || echo FAIL"
        )

        assert "PASS" in result.stdout
        assert "SUCCESS: Verified tiny" in result.stdout

    def test_mismatched_digest_fails(self, tmp_path):
        model = tmp_path / "ggml-tiny.bin"
        model.write_bytes(b"tampered")
        registry = _registry(
            tmp_path,
            {"whispercpp": {"ggml-tiny.bin": {"sha256": hashlib.sha256(b"weights").hexdigest()}}},
        )

        result = _run(
            f"{_PRELUDE}\n{_source('lookup_model_sha256', 'verify_model_sha256')}\n"
            f'MODEL_HASH_REGISTRY="{registry}"\n'
            f'verify_model_sha256 "{model}" whispercpp ggml-tiny.bin "tiny" '
            f"&& echo PASS || echo FAIL"
        )

        assert "FAIL" in result.stdout
        assert "ERROR: SHA256 mismatch for tiny" in result.stdout

    def test_unpinned_model_warns_but_does_not_block(self, tmp_path):
        model = tmp_path / "ggml-unlisted.bin"
        model.write_bytes(b"weights")
        registry = _registry(tmp_path, {"whispercpp": {}})

        result = _run(
            f"{_PRELUDE}\n{_source('lookup_model_sha256', 'verify_model_sha256')}\n"
            f'MODEL_HASH_REGISTRY="{registry}"\n'
            f'verify_model_sha256 "{model}" whispercpp ggml-unlisted.bin "unlisted" '
            f"&& echo PASS || echo FAIL"
        )

        assert "PASS" in result.stdout
        assert "WARNING: No pinned SHA256" in result.stdout

    def test_missing_registry_warns_but_does_not_block(self, tmp_path):
        model = tmp_path / "ggml-tiny.bin"
        model.write_bytes(b"weights")

        result = _run(
            f"{_PRELUDE}\n{_source('lookup_model_sha256', 'verify_model_sha256')}\n"
            f'MODEL_HASH_REGISTRY="{tmp_path}/absent.json"\n'
            f'verify_model_sha256 "{model}" whispercpp ggml-tiny.bin "tiny" '
            f"&& echo PASS || echo FAIL"
        )

        assert "PASS" in result.stdout
        assert "WARNING: No pinned SHA256" in result.stdout

    def test_shipped_registry_pins_the_models_the_installer_downloads(self):
        """The installer looks these three up by name; they must exist."""
        registry = json.loads(
            (
                Path(__file__).resolve().parents[1] / "src/vocalinux/utils/model_hashes.json"
            ).read_text()
        )
        assert registry["whispercpp"]["ggml-tiny.bin"]["sha256"]
        assert registry["whisper"]["tiny.pt"]["sha256"]
        assert registry["vosk"]["vosk-model-small-en-us-0.15.zip"]["sha256"]


class TestVerifyZipMembersSafe:
    def test_normal_archive_is_accepted(self, tmp_path):
        archive = tmp_path / "model.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("vosk-model-small-en-us-0.15/am/final.mdl", "weights")

        result = _run(
            f'{_PRELUDE}\n{_source("verify_zip_members_safe")}\n'
            f'verify_zip_members_safe "{archive}" && echo PASS || echo FAIL'
        )

        assert "PASS" in result.stdout

    def test_parent_traversal_is_refused(self, tmp_path):
        archive = tmp_path / "evil.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../../.bashrc", "pwned")

        result = _run(
            f'{_PRELUDE}\n{_source("verify_zip_members_safe")}\n'
            f'verify_zip_members_safe "{archive}" && echo PASS || echo FAIL'
        )

        assert "FAIL" in result.stdout
        assert "unsafe paths" in result.stdout

    def test_absolute_path_is_refused(self, tmp_path):
        archive = tmp_path / "abs.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(zipfile.ZipInfo("/etc/cron.d/pwned"), "* * * * * root sh")

        result = _run(
            f'{_PRELUDE}\n{_source("verify_zip_members_safe")}\n'
            f'verify_zip_members_safe "{archive}" && echo PASS || echo FAIL'
        )

        assert "FAIL" in result.stdout
        assert "unsafe paths" in result.stdout

    def test_symlink_member_is_refused(self, tmp_path):
        archive = tmp_path / "link.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            info = zipfile.ZipInfo("model/link")
            info.external_attr = (0xA000 | 0o777) << 16
            zf.writestr(info, "/etc/passwd")

        result = _run(
            f'{_PRELUDE}\n{_source("verify_zip_members_safe")}\n'
            f'verify_zip_members_safe "{archive}" && echo PASS || echo FAIL'
        )

        assert "FAIL" in result.stdout
        assert "symlink" in result.stdout
