"""Tests for model download integrity checks."""

import hashlib
import json
import os
import stat
import zipfile

import pytest

from vocalinux.utils import model_integrity
from vocalinux.utils.model_integrity import (
    MAX_ARCHIVE_EXPANDED_BYTES,
    ModelIntegrityError,
    ensure_trusted_model_url,
    get_pinned_digest,
    load_registry,
    safe_extract_zip,
    sha256_file,
    strict_mode_enabled,
    verify_downloaded_model,
)
from vocalinux.utils.vosk_model_info import VOSK_MODEL_INFO, vosk_model_url
from vocalinux.utils.whisper_model_info import WHISPER_MODEL_URLS
from vocalinux.utils.whispercpp_model_info import WHISPERCPP_MODEL_INFO


@pytest.fixture
def pinned_file(tmp_path, monkeypatch):
    """Write a model file and pin its real digest in a throwaway registry."""
    payload = b"pretend model weights"
    model_file = tmp_path / "ggml-test.bin"
    model_file.write_bytes(payload)

    registry = tmp_path / "model_hashes.json"
    registry.write_text(
        json.dumps(
            {
                "whispercpp": {
                    "ggml-test.bin": {
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "size": len(payload),
                    }
                }
            }
        )
    )
    monkeypatch.setattr(model_integrity, "REGISTRY_PATH", registry)
    return model_file


class TestRegistryContents:
    """The shipped registry must cover every model the app can download."""

    def test_every_whispercpp_model_is_pinned(self):
        for name, info in WHISPERCPP_MODEL_INFO.items():
            filename = os.path.basename(info["url"])
            assert get_pinned_digest("whispercpp", filename), f"{name} ({filename}) is unpinned"

    def test_every_whisper_model_is_pinned(self):
        for size in WHISPER_MODEL_URLS:
            assert get_pinned_digest("whisper", f"{size}.pt"), f"whisper {size} is unpinned"

    def test_every_vosk_model_is_pinned(self):
        for tier in VOSK_MODEL_INFO.values():
            for language, model_name in tier["languages"].items():
                assert get_pinned_digest(
                    "vosk", f"{model_name}.zip"
                ), f"vosk {language}/{model_name} is unpinned"

    def test_whisper_digests_match_the_digest_embedded_in_the_url(self):
        """OpenAI puts each checkpoint's SHA256 in its URL; the pins must agree."""
        for size, url in WHISPER_MODEL_URLS.items():
            url_digest = url.strip("/").split("/")[-2]
            assert get_pinned_digest("whisper", f"{size}.pt")["sha256"] == url_digest

    def test_portuguese_medium_model_is_the_published_archive(self):
        """vosk-model-pt-0.4 404s; Alphacephei ships the Facebook-trained zip."""
        assert VOSK_MODEL_INFO["medium"]["languages"]["pt"] == (
            "vosk-model-pt-fb-v0.1.1-20220516_2113"
        )
        assert get_pinned_digest("vosk", "vosk-model-pt-fb-v0.1.1-20220516_2113.zip")

    def test_entries_are_well_formed(self):
        registry = load_registry()
        for section in ("whispercpp", "whisper", "vosk"):
            for filename, entry in registry[section].items():
                digest = entry["sha256"]
                assert len(digest) == 64, f"{filename} digest is not a SHA256"
                assert set(digest) <= set("0123456789abcdef"), f"{filename} digest is not hex"
                assert entry["size"] > 0, f"{filename} has no size"


class TestPinnedDigestLookup:
    def test_unknown_model_returns_none(self):
        assert get_pinned_digest("whispercpp", "ggml-does-not-exist.bin") is None
        assert get_pinned_digest("nonsense", "ggml-tiny.bin") is None

    def test_unreadable_registry_degrades_to_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(model_integrity, "REGISTRY_PATH", tmp_path / "missing.json")
        assert load_registry() == {}

    def test_malformed_registry_degrades_to_empty(self, tmp_path, monkeypatch):
        broken = tmp_path / "model_hashes.json"
        broken.write_text("{not json")
        monkeypatch.setattr(model_integrity, "REGISTRY_PATH", broken)
        assert load_registry() == {}


class TestVerifyDownloadedModel:
    def test_matching_file_passes(self, pinned_file):
        verify_downloaded_model(str(pinned_file), "whispercpp", "ggml-test.bin")

    def test_sha256_file_matches_hashlib(self, pinned_file):
        assert sha256_file(str(pinned_file)) == hashlib.sha256(pinned_file.read_bytes()).hexdigest()

    def test_sha256_file_can_be_aborted(self, pinned_file):
        with pytest.raises(RuntimeError, match="cancelled"):
            sha256_file(str(pinned_file), should_abort=lambda: True)

    def test_verify_can_be_aborted_while_hashing(self, pinned_file):
        with pytest.raises(RuntimeError, match="cancelled"):
            verify_downloaded_model(
                str(pinned_file),
                "whispercpp",
                "ggml-test.bin",
                should_abort=lambda: True,
            )

    def test_tampered_contents_are_rejected(self, pinned_file):
        pinned_file.write_bytes(b"pretend model weight5")  # same length, different bytes
        with pytest.raises(ModelIntegrityError, match="SHA256 mismatch"):
            verify_downloaded_model(str(pinned_file), "whispercpp", "ggml-test.bin")

    def test_truncated_download_is_rejected_on_size(self, pinned_file):
        pinned_file.write_bytes(b"pretend")
        with pytest.raises(ModelIntegrityError, match="bytes were expected"):
            verify_downloaded_model(str(pinned_file), "whispercpp", "ggml-test.bin")

    def test_unpinned_model_is_allowed_with_a_warning(self, pinned_file, caplog):
        verify_downloaded_model(str(pinned_file), "whispercpp", "ggml-unlisted.bin", strict=False)
        assert "No pinned SHA256 digest" in caplog.text

    def test_unpinned_model_is_refused_in_strict_mode(self, pinned_file):
        with pytest.raises(ModelIntegrityError, match="No pinned SHA256 digest"):
            verify_downloaded_model(
                str(pinned_file), "whispercpp", "ggml-unlisted.bin", strict=True
            )

    def test_strict_mode_reads_the_environment(self, pinned_file, monkeypatch):
        monkeypatch.setenv(model_integrity.STRICT_ENV_VAR, "1")
        assert strict_mode_enabled() is True
        with pytest.raises(ModelIntegrityError):
            verify_downloaded_model(str(pinned_file), "whispercpp", "ggml-unlisted.bin")

    def test_strict_mode_is_off_by_default(self, monkeypatch):
        monkeypatch.delenv(model_integrity.STRICT_ENV_VAR, raising=False)
        assert strict_mode_enabled() is False

    def test_integrity_errors_are_runtime_errors(self):
        """Download callers already clean up after RuntimeError."""
        assert issubclass(ModelIntegrityError, RuntimeError)


class TestTrustedModelUrls:
    @pytest.mark.parametrize(
        "url",
        [
            "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin",
            "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
            "https://openaipublic.azureedge.net/main/whisper/models/abc/tiny.pt",
        ],
    )
    def test_known_hosts_are_accepted(self, url):
        ensure_trusted_model_url(url)

    def test_plain_http_is_refused(self):
        with pytest.raises(ModelIntegrityError, match="over http"):
            ensure_trusted_model_url("http://huggingface.co/ggerganov/whisper.cpp/ggml-tiny.bin")

    @pytest.mark.parametrize(
        "url",
        [
            "https://evil.example/ggml-tiny.bin",
            "https://huggingface.co.evil.example/ggml-tiny.bin",
            "https://notalphacephei.com/vosk/models/model.zip",
        ],
    )
    def test_unknown_hosts_are_refused(self, url):
        with pytest.raises(ModelIntegrityError, match="untrusted host"):
            ensure_trusted_model_url(url)

    def test_every_shipped_model_url_is_trusted(self):
        for info in WHISPERCPP_MODEL_INFO.values():
            ensure_trusted_model_url(info["url"])
        for url in WHISPER_MODEL_URLS.values():
            ensure_trusted_model_url(url)
        for tier in VOSK_MODEL_INFO.values():
            for name in tier["languages"].values():
                ensure_trusted_model_url(vosk_model_url(name))


class TestSafeExtractZip:
    def _write_zip(self, path, members):
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in members:
                archive.writestr(name, data)
        return path

    def test_normal_archive_extracts(self, tmp_path):
        archive = self._write_zip(
            tmp_path / "model.zip", [("model/am/final.mdl", "weights"), ("model/README", "hi")]
        )
        dest = tmp_path / "models"
        dest.mkdir()

        safe_extract_zip(str(archive), str(dest))

        assert (dest / "model" / "am" / "final.mdl").read_text() == "weights"

    def test_parent_traversal_is_refused(self, tmp_path):
        archive = self._write_zip(
            tmp_path / "evil.zip", [("model/ok", "fine"), ("../../.bashrc", "pwned")]
        )
        dest = tmp_path / "models"
        dest.mkdir()

        with pytest.raises(ModelIntegrityError, match="escapes the models directory"):
            safe_extract_zip(str(archive), str(dest))

        assert not (tmp_path.parent / ".bashrc").exists()
        assert list(dest.iterdir()) == [], "nothing may be written when a member is rejected"

    def test_absolute_paths_are_refused(self, tmp_path):
        archive = tmp_path / "abs.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            # zipfile normalises leading slashes through writestr, so build the
            # member the way a hostile packer would.
            zf.writestr(zipfile.ZipInfo("/etc/cron.d/pwned"), "* * * * * root sh")
        dest = tmp_path / "models"
        dest.mkdir()

        with pytest.raises(ModelIntegrityError, match="absolute path"):
            safe_extract_zip(str(archive), str(dest))

    def test_symlink_members_are_refused(self, tmp_path):
        archive = tmp_path / "link.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            info = zipfile.ZipInfo("model/link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/home/user/.ssh/authorized_keys")
        dest = tmp_path / "models"
        dest.mkdir()

        with pytest.raises(ModelIntegrityError, match="symlink"):
            safe_extract_zip(str(archive), str(dest))

    def test_oversized_archive_is_refused(self, tmp_path, monkeypatch):
        archive = self._write_zip(tmp_path / "bomb.zip", [("model/big", "x" * 1024)])
        dest = tmp_path / "models"
        dest.mkdir()

        monkeypatch.setattr(model_integrity, "MAX_ARCHIVE_EXPANDED_BYTES", 16)
        with pytest.raises(ModelIntegrityError, match="refusing to extract"):
            safe_extract_zip(str(archive), str(dest))

    def test_real_cap_is_large_enough_for_the_biggest_model(self):
        """The largest VOSK archive unpacks to roughly 2 GB."""
        assert MAX_ARCHIVE_EXPANDED_BYTES > 4 * 1024**3
