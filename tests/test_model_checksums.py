"""Tests for model download integrity verification.

The manifest-coverage test is what makes verification safe to fail closed: a
model added to the app without regenerating model_checksums.txt is caught here
rather than on a user's machine, where it would surface as an unexplained
refusal to install.
"""

import hashlib
import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from vocalinux.utils import model_checksums
from vocalinux.utils.model_checksums import (
    ChecksumError,
    Expected,
    expected_for,
    file_digest,
    pinned_filenames,
    sha256_from_openai_url,
    verify_file,
    verify_model_file,
    verify_openai_model,
    whispercpp_revision,
)
from vocalinux.utils.vosk_model_info import VOSK_MODEL_INFO
from vocalinux.utils.whispercpp_model_info import (
    WHISPERCPP_MODEL_INFO,
    whispercpp_model_file,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"


class TestManifestCoverage(unittest.TestCase):
    """Every model the application can download must have a pinned digest."""

    def test_every_whispercpp_model_is_pinned(self):
        pinned = pinned_filenames()
        missing = [
            whispercpp_model_file(name)
            for name in WHISPERCPP_MODEL_INFO
            if whispercpp_model_file(name) not in pinned
        ]
        self.assertEqual(
            missing,
            [],
            "whisper.cpp models without a pinned checksum; "
            "run `just model-checksums` to refresh the manifest",
        )

    def test_every_vosk_model_is_pinned(self):
        pinned = pinned_filenames()
        missing = sorted(
            {
                f"{name}.zip"
                for info in VOSK_MODEL_INFO.values()
                for name in info["languages"].values()
                if name and f"{name}.zip" not in pinned
            }
        )
        self.assertEqual(
            missing,
            [],
            "VOSK models without a pinned checksum; "
            "run `just model-checksums` to refresh the manifest",
        )

    def test_manifest_entries_are_well_formed(self):
        for filename in pinned_filenames():
            expected = expected_for(filename)
            self.assertIn(expected.algo, {"sha256", "md5"}, filename)
            length = 64 if expected.algo == "sha256" else 32
            self.assertEqual(len(expected.digest), length, filename)
            self.assertRegex(expected.digest, r"^[0-9a-f]+$", filename)
            self.assertGreater(expected.size, 0, filename)

    def test_whispercpp_revision_is_pinned_to_a_commit(self):
        revision = whispercpp_revision()
        self.assertNotEqual(revision, "main", "whisper.cpp must not track a branch")
        self.assertRegex(revision, r"^[0-9a-f]{40}$")

    def test_download_urls_use_the_pinned_revision(self):
        revision = whispercpp_revision()
        for name, info in WHISPERCPP_MODEL_INFO.items():
            self.assertIn(f"/resolve/{revision}/", info["url"], name)


class TestVerifyFile(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        self.payload = b"vocalinux model payload"
        self.path = self.tmp / "model.bin"
        self.path.write_bytes(self.payload)
        self.digest = hashlib.sha256(self.payload).hexdigest()

    def test_accepts_a_matching_file(self):
        verify_file(str(self.path), Expected("sha256", self.digest, len(self.payload)))

    def test_rejects_a_wrong_digest(self):
        with self.assertRaises(ChecksumError) as ctx:
            verify_file(str(self.path), Expected("sha256", "0" * 64, len(self.payload)))
        self.assertIn("failed sha256 verification", str(ctx.exception))

    def test_reports_truncation_as_a_size_problem(self):
        """A short read is the common failure; it must not read like tampering."""
        with self.assertRaises(ChecksumError) as ctx:
            verify_file(str(self.path), Expected("sha256", self.digest, len(self.payload) + 10))
        self.assertIn("truncated", str(ctx.exception))

    def test_size_zero_skips_the_size_check(self):
        verify_file(str(self.path), Expected("sha256", self.digest, 0))

    def test_md5_is_supported(self):
        digest = hashlib.md5(self.payload).hexdigest()
        verify_file(str(self.path), Expected("md5", digest, len(self.payload)))

    def test_unknown_algorithm_is_rejected(self):
        with self.assertRaises(ChecksumError):
            file_digest(str(self.path), "not-a-hash")

    def test_digest_matches_hashlib_for_a_multi_chunk_file(self):
        big = self.tmp / "big.bin"
        payload = os.urandom(model_checksums._CHUNK_SIZE * 2 + 7)
        big.write_bytes(payload)
        self.assertEqual(file_digest(str(big), "sha256"), hashlib.sha256(payload).hexdigest())


class TestVerifyModelFile(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))

    def test_unpinned_file_is_refused(self):
        """Fail closed: no pin means no install, not a warning."""
        path = self.tmp / "ggml-not-a-real-model.bin"
        path.write_bytes(b"x")
        with self.assertRaises(ChecksumError) as ctx:
            verify_model_file(str(path))
        self.assertIn("No checksum is pinned", str(ctx.exception))

    def test_temp_name_is_looked_up_under_the_real_name(self):
        """Downloads land as *.tmp, so the lookup key must be overridable."""
        path = self.tmp / "ggml-tiny.bin.tmp"
        path.write_bytes(b"wrong content")
        with self.assertRaises(ChecksumError) as ctx:
            verify_model_file(str(path), "ggml-tiny.bin")
        # Reached the digest comparison, so the manifest lookup succeeded.
        self.assertIn("ggml-tiny.bin", str(ctx.exception))
        self.assertNotIn("No checksum is pinned", str(ctx.exception))

    def test_missing_manifest_refuses_everything(self):
        with patch.object(model_checksums, "_manifest_text", return_value=""):
            model_checksums._parse_manifest.cache_clear()
            try:
                path = self.tmp / "ggml-tiny.bin"
                path.write_bytes(b"x")
                with self.assertRaises(ChecksumError):
                    verify_model_file(str(path))
            finally:
                model_checksums._parse_manifest.cache_clear()


class TestOpenAIUrlDigest(unittest.TestCase):
    URL = (
        "https://openaipublic.azureedge.net/main/whisper/models/"
        "65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9/tiny.pt"
    )

    def test_extracts_the_digest_from_the_path(self):
        self.assertEqual(
            sha256_from_openai_url(self.URL),
            "65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9",
        )

    def test_url_without_a_digest_yields_none(self):
        self.assertIsNone(sha256_from_openai_url("https://example.com/main/whisper/models/tiny.pt"))

    def test_verification_refuses_an_unverifiable_url(self):
        tmp = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        path = tmp / "tiny.pt"
        path.write_bytes(b"x")
        with self.assertRaises(ChecksumError) as ctx:
            verify_openai_model(str(path), "https://example.com/tiny.pt")
        self.assertIn("no sha256 path segment", str(ctx.exception))

    def test_verification_accepts_a_matching_payload(self):
        tmp = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        payload = b"pretend checkpoint"
        path = tmp / "tiny.pt"
        path.write_bytes(payload)
        url = (
            "https://openaipublic.azureedge.net/main/whisper/models/"
            f"{hashlib.sha256(payload).hexdigest()}/tiny.pt"
        )
        verify_openai_model(str(path), url)


class TestInstallerVerification(unittest.TestCase):
    """The bash half must agree with the Python half on the same manifest."""

    PRELUDE = """
set -uo pipefail
print_info() { echo "INFO: $*"; }
print_warning() { echo "WARNING: $*"; }
print_error() { echo "ERROR: $*"; }
print_success() { echo "SUCCESS: $*"; }
command_exists() { command -v "$1" >/dev/null 2>&1; }
INSTALL_DIR="%s"
""" % str(REPO_ROOT)

    FUNCTIONS = (
        "compute_file_digest",
        "verify_digest",
        "verify_model_checksum",
        "verify_openai_model_checksum",
        "whispercpp_pinned_revision",
    )

    def _source(self) -> str:
        text = INSTALL_SH.read_text()
        chunks = []
        for name in self.FUNCTIONS:
            start = text.index(f"\n{name}() {{")
            end = text.index("\n}\n", start) + len("\n}\n")
            chunks.append(text[start:end])
        manifest_line = (
            'MODEL_CHECKSUMS_FILE="$INSTALL_DIR/src/vocalinux/utils/model_checksums.txt"'
        )
        return self.PRELUDE + manifest_line + "\n" + "\n".join(chunks)

    def _run(self, script: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", "-c", self._source() + "\n" + script],
            capture_output=True,
            text=True,
        )

    def test_reads_the_same_revision_as_python(self):
        result = self._run("whispercpp_pinned_revision")
        self.assertEqual(result.stdout.strip(), whispercpp_revision())

    def test_accepts_a_file_matching_the_manifest(self):
        """Build a file whose digest is the pinned one by asking Python for it."""
        tmp = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        # Pick a manifest entry and forge a file that matches it, by rewriting the
        # manifest to the digest of content we control.
        payload = b"installer payload"
        target = tmp / "ggml-tiny.bin"
        target.write_bytes(payload)
        manifest = tmp / "model_checksums.txt"
        manifest.write_text(
            "# whispercpp-revision: " + "a" * 40 + "\n"
            f"ggml-tiny.bin  sha256  {hashlib.sha256(payload).hexdigest()}  {len(payload)}\n"
        )
        result = self._run(f'MODEL_CHECKSUMS_FILE="{manifest}"; verify_model_checksum "{target}"')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("verified (sha256)", result.stdout)

    def test_rejects_a_digest_mismatch(self):
        tmp = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        target = tmp / "ggml-tiny.bin"
        target.write_bytes(b"tampered")
        manifest = tmp / "model_checksums.txt"
        manifest.write_text(f"ggml-tiny.bin  sha256  {'0' * 64}  8\n")
        result = self._run(f'MODEL_CHECKSUMS_FILE="{manifest}"; verify_model_checksum "{target}"')
        self.assertEqual(result.returncode, 1)
        self.assertIn("failed sha256 verification", result.stdout)

    def test_rejects_a_truncated_file_as_truncation(self):
        tmp = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        payload = b"short"
        target = tmp / "ggml-tiny.bin"
        target.write_bytes(payload)
        manifest = tmp / "model_checksums.txt"
        manifest.write_text(
            f"ggml-tiny.bin  sha256  {hashlib.sha256(payload).hexdigest()}  999999\n"
        )
        result = self._run(f'MODEL_CHECKSUMS_FILE="{manifest}"; verify_model_checksum "{target}"')
        self.assertEqual(result.returncode, 1)
        self.assertIn("truncated", result.stdout)

    def test_refuses_an_unpinned_file(self):
        tmp = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        target = tmp / "ggml-unknown.bin"
        target.write_bytes(b"x")
        manifest = tmp / "model_checksums.txt"
        manifest.write_text("ggml-tiny.bin  sha256  " + "0" * 64 + "  1\n")
        result = self._run(f'MODEL_CHECKSUMS_FILE="{manifest}"; verify_model_checksum "{target}"')
        self.assertEqual(result.returncode, 1)
        self.assertIn("No checksum is pinned", result.stdout)

    def test_refuses_when_the_manifest_is_absent(self):
        tmp = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        target = tmp / "ggml-tiny.bin"
        target.write_bytes(b"x")
        result = self._run(
            f'MODEL_CHECKSUMS_FILE="{tmp}/nope.txt"; verify_model_checksum "{target}"'
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Checksum manifest not found", result.stdout)

    def test_openai_url_digest_is_honoured(self):
        tmp = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        payload = b"pretend checkpoint"
        target = tmp / "tiny.pt"
        target.write_bytes(payload)
        url = (
            "https://openaipublic.azureedge.net/main/whisper/models/"
            f"{hashlib.sha256(payload).hexdigest()}/tiny.pt"
        )
        result = self._run(f'verify_openai_model_checksum "{target}" "{url}" "Whisper tiny"')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("verified (sha256)", result.stdout)

    def test_openai_url_without_a_digest_is_refused(self):
        tmp = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        target = tmp / "tiny.pt"
        target.write_bytes(b"x")
        result = self._run(
            f'verify_openai_model_checksum "{target}" "https://example.com/tiny.pt" "Whisper tiny"'
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("no sha256 path segment", result.stdout)

    def test_bash_and_python_agree_on_a_real_manifest_entry(self):
        """Same file, same manifest, same verdict from both implementations."""
        tmp = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        target = tmp / "ggml-tiny.bin"
        target.write_bytes(b"definitely not the real model")

        result = self._run(f'verify_model_checksum "{target}" "ggml-tiny.bin"')
        self.assertEqual(result.returncode, 1)

        with self.assertRaises(ChecksumError):
            verify_model_file(str(target), "ggml-tiny.bin")


if __name__ == "__main__":
    unittest.main()
