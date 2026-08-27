"""Tests for model download integrity verification.

The manifest-coverage test is what makes verification safe to fail closed: a
model added to the app without regenerating model_checksums.txt is caught here
rather than on a user's machine, where it would surface as an unexplained
refusal to install.
"""

import base64
import hashlib
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from vocalinux.utils import model_checksums
from vocalinux.utils.model_checksums import (
    VERIFICATION_STAMP_NAME,
    ChecksumError,
    Expected,
    expected_for,
    file_digest,
    pinned_filenames,
    verify_file,
    verify_model_file,
    whispercpp_revision,
    write_verification_stamp,
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
            # sha256 only: the VOSK entries used to copy the md5 Alphacephei
            # publishes, which pins nothing they could not change themselves.
            self.assertEqual(expected.algo, "sha256", filename)
            self.assertEqual(len(expected.digest), 64, filename)
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
        "pinned_digest_for",
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


class TestExistingModelsAreVerified(unittest.TestCase):
    """A model that is already on disk must be hashed, not trusted.

    Regression cover for the review finding on #713: all three installer
    functions returned early when the model file existed, so every re-run — and
    every install predating checksum verification — kept an unverified model.
    """

    SOURCE = INSTALL_SH.read_text()

    def _function_body(self, name: str) -> str:
        start = self.SOURCE.index(f"\n{name}() {{")
        end = self.SOURCE.index("\n}\n", start)
        return self.SOURCE[start:end]

    def _exists_guard(self, name: str) -> str:
        """The part of the function before it starts downloading."""
        body = self._function_body(name)
        marker = body.find("Check internet connectivity")
        return body[:marker] if marker != -1 else body

    def test_whisper_hashes_an_existing_model(self):
        guard = self._exists_guard("install_whisper_model")
        self.assertIn("verify_openai_model_checksum", guard)
        self.assertIn("rm -f", guard)

    def test_whispercpp_hashes_an_existing_model(self):
        guard = self._exists_guard("install_whispercpp_model")
        self.assertIn("verify_model_checksum", guard)
        self.assertIn("rm -f", guard)

    def test_vosk_requires_a_matching_verification_stamp(self):
        guard = self._exists_guard("install_vosk_models")
        self.assertIn(VERIFICATION_STAMP_NAME, guard)

    def test_vosk_keeps_an_unstamped_tree_until_it_has_a_replacement(self):
        """Deleting on sight would make every failed install a missing model.

        No stamp is the ordinary case — an older install, or a tree the app
        downloaded itself — and this runs on every ./install.sh. Removal belongs
        after the replacement is downloaded, verified and unpacked, not before.
        """
        guard = self._exists_guard("install_vosk_models")
        self.assertNotIn("rm -rf", guard)

    def test_vosk_unpacks_to_staging_and_swaps_only_what_it_verified(self):
        body = self._function_body("install_vosk_models")
        order = [
            body.index("verify_model_checksum"),
            body.index('unzip -q "$TEMP_ZIP" -d "$STAGING_DIR"'),
            body.index(f'> "$STAGING_DIR/$SMALL_MODEL_NAME/{VERIFICATION_STAMP_NAME}"'),
            body.index('mv "$STAGING_DIR/$SMALL_MODEL_NAME" "$SMALL_MODEL_PATH"'),
        ]
        self.assertEqual(order, sorted(order), "verify, unpack, stamp, then swap")

    def test_vosk_restores_the_old_tree_when_the_swap_fails(self):
        body = self._function_body("install_vosk_models")
        self.assertIn('mv "$REPLACED_DIR" "$SMALL_MODEL_PATH"', body)

    def test_no_installer_path_returns_zero_on_an_unverified_file(self):
        """Each guard must verify before its `return 0`, not after."""
        for name, checker in (
            ("install_whisper_model", "verify_openai_model_checksum"),
            ("install_whispercpp_model", "verify_model_checksum"),
            ("install_vosk_models", ".vocalinux_verified"),
        ):
            guard = self._exists_guard(name)
            self.assertLess(
                guard.index(checker),
                guard.index("return 0"),
                f"{name} returns success before verifying an existing model",
            )


class TestVerificationStamp(unittest.TestCase):
    """The stamp is the only thing that makes an extracted tree verifiable.

    Two implementations write and read it — this module and install.sh — so the
    name and the contents have to be the same on both sides.
    """

    def test_the_installer_uses_the_same_stamp_name(self):
        self.assertIn(VERIFICATION_STAMP_NAME, INSTALL_SH.read_text())

    def test_it_records_the_pinned_digest_of_the_archive(self):
        with TemporaryDirectory() as tree:
            write_verification_stamp(tree, "vosk-model-small-en-us-0.15.zip")
            written = Path(tree, VERIFICATION_STAMP_NAME).read_text()

        pinned = expected_for("vosk-model-small-en-us-0.15.zip")
        self.assertIsNotNone(pinned)
        # install.sh compares with $(cat ...), which strips the trailing newline
        # the shell's own writer leaves; match it byte for byte.
        self.assertEqual(written, f"{pinned.digest}\n")

    def test_it_refuses_to_stamp_an_unpinned_archive(self):
        with TemporaryDirectory() as tree:
            with self.assertRaises(ChecksumError):
                write_verification_stamp(tree, "not-a-model-we-ship.zip")
            self.assertFalse(Path(tree, VERIFICATION_STAMP_NAME).exists())


class TestVoskInstallerReplacesRatherThanDeletes(unittest.TestCase):
    """Run install_vosk_models for real, with the network and unzip around it.

    The static checks above pin the shape of the code; these pin the behaviour
    the review asked for: an install that fails after finding an unstamped tree
    must leave that tree where it was, because "no stamp" is the ordinary state
    of any model the app downloaded itself or that predates stamping.
    """

    # A zip whose top-level directory is the one the real archive unpacks to.
    # Embedded rather than built here so no test that mocks zipfile can reach it.
    FIXTURE_ZIP = base64.b64decode(
        "UEsDBBQAAAAIAM92F12oDuXYFgAAAIgTAAAoAAAAdm9zay1tb2RlbC1zbWFsbC1lbi11cy0wLjE1L2FtL2Zp"
        "bmFsLm1kbO3BMQEAAADCoPVPbQo/oAAAAACAtwFQSwMEFAAAAAgAz3YXXVXAPAMTAAAAEQAAACsAAAB2b3Nr"
        "LW1vZGVsLXNtYWxsLWVuLXVzLTAuMTUvY29uZi9tb2RlbC5jb25m09XNzczTTUwuySxLtTUyMOACAFBLAQIU"
        "AxQAAAAIAM92F12oDuXYFgAAAIgTAAAoAAAAAAAAAAAAAACAAQAAAAB2b3NrLW1vZGVsLXNtYWxsLWVuLXVz"
        "LTAuMTUvYW0vZmluYWwubWRsUEsBAhQDFAAAAAgAz3YXXVXAPAMTAAAAEQAAACsAAAAAAAAAAAAAAIABXAAA"
        "AHZvc2stbW9kZWwtc21hbGwtZW4tdXMtMC4xNS9jb25mL21vZGVsLmNvbmZQSwUGAAAAAAIAAgCvAAAAuAAA"
        "AAAA"
    )
    MODEL_NAME = "vosk-model-small-en-us-0.15"

    PRELUDE = """
set -Eeuo pipefail
print_info() { echo "INFO: $*"; }
print_warning() { echo "WARNING: $*"; }
print_error() { echo "ERROR: $*"; }
print_success() { echo "SUCCESS: $*"; }
command_exists() { command -v "$1" >/dev/null 2>&1; }
DATA_DIR="$ROOT/data"
VOCALINUX_TMP_DIR="$ROOT/tmp"
MODEL_CHECKSUMS_FILE="$ROOT/model_checksums.txt"
mkdir -p "$VOCALINUX_TMP_DIR"

# The installer only probes for these; the download itself is stubbed out.
check_connectivity() { return 0; }
download_model_file() {
    echo "call" >> "$ROOT/downloads"
    [ -z "${DOWNLOAD_FAILS:-}" ] || return 1
    cp "$ROOT/${SERVED_ZIP:-fixture.zip}" "$2"
}
"""

    FUNCTIONS = (
        "compute_file_digest",
        "verify_digest",
        "verify_model_checksum",
        "pinned_digest_for",
        "install_vosk_models",
    )

    def setUp(self):
        if not shutil.which("unzip"):
            self.skipTest("unzip is required to exercise the extraction path")
        self.root = Path(self.enterContext(TemporaryDirectory()))
        (self.root / "fixture.zip").write_bytes(self.FIXTURE_ZIP)
        # A manifest of our own, so the fixture is what the pin describes.
        digest = hashlib.sha256(self.FIXTURE_ZIP).hexdigest()
        self.digest = digest
        (self.root / "model_checksums.txt").write_text(
            f"{self.MODEL_NAME}.zip  sha256  {digest}  {len(self.FIXTURE_ZIP)}\n"
        )
        self.models_dir = self.root / "data" / "models"
        self.model_path = self.models_dir / self.MODEL_NAME
        self.stamp = self.model_path / VERIFICATION_STAMP_NAME

        # install_vosk_models probes for a downloader with `command -v` before it
        # downloads anything. download_model_file is stubbed, so the probe is all
        # that has to succeed, and a stub on PATH keeps the test from depending on
        # the host having wget or curl.
        self.fake_bin = self.root / "bin"
        self.fake_bin.mkdir()
        curl = self.fake_bin / "curl"
        curl.write_text("#!/bin/sh\necho 'the stubbed downloader must not run' >&2\nexit 1\n")
        curl.chmod(0o755)

    def _source(self) -> str:
        text = INSTALL_SH.read_text()
        chunks = []
        for name in self.FUNCTIONS:
            start = text.index(f"\n{name}() {{")
            end = text.index("\n}\n", start) + len("\n}\n")
            chunks.append(text[start:end])
        return self.PRELUDE + "\n".join(chunks)

    def _install(self, **env) -> subprocess.CompletedProcess:
        script = (
            self._source() + '\nif install_vosk_models; then echo "RC=0"; else echo "RC=$?"; fi\n'
        )
        return subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PATH": f"{self.fake_bin}{os.pathsep}{os.environ['PATH']}",
                "ROOT": str(self.root),
                **env,
            },
        )

    @staticmethod
    def _rc(result: subprocess.CompletedProcess) -> str:
        return result.stdout.strip().splitlines()[-1]

    def _downloads(self) -> int:
        path = self.root / "downloads"
        return len(path.read_text().splitlines()) if path.exists() else 0

    def test_fresh_install_extracts_and_stamps(self):
        result = self._install()
        self.assertEqual(self._rc(result), "RC=0", result.stdout + result.stderr)
        self.assertTrue((self.model_path / "am" / "final.mdl").exists())
        self.assertEqual(self.stamp.read_text().strip(), self.digest)

    def test_a_stamped_tree_is_not_downloaded_again(self):
        self.assertEqual(self._rc(self._install()), "RC=0")
        self.assertEqual(self._rc(self._install()), "RC=0")
        self.assertEqual(self._downloads(), 1, "the second run re-fetched a verified model")

    def test_an_unstamped_tree_survives_a_failed_download(self):
        """The regression: the old code deleted here and then failed to download."""
        (self.model_path / "am").mkdir(parents=True)
        (self.model_path / "am" / "final.mdl").write_bytes(b"an older install")

        result = self._install(DOWNLOAD_FAILS="1")

        self.assertEqual(self._rc(result), "RC=1")
        self.assertEqual((self.model_path / "am" / "final.mdl").read_bytes(), b"an older install")

    def test_an_unstamped_tree_survives_a_download_that_fails_verification(self):
        (self.root / "tampered.zip").write_bytes(self.FIXTURE_ZIP + b"trailing junk")
        (self.model_path / "am").mkdir(parents=True)
        (self.model_path / "am" / "final.mdl").write_bytes(b"an older install")

        result = self._install(SERVED_ZIP="tampered.zip")

        self.assertEqual(self._rc(result), "RC=1")
        self.assertEqual((self.model_path / "am" / "final.mdl").read_bytes(), b"an older install")

    def test_an_unstamped_tree_is_replaced_once_a_verified_one_is_ready(self):
        (self.model_path / "am").mkdir(parents=True)
        (self.model_path / "am" / "final.mdl").write_bytes(b"an older install")
        (self.model_path / "stale-file").write_text("gone after the swap")

        result = self._install()

        self.assertEqual(self._rc(result), "RC=0", result.stdout + result.stderr)
        self.assertNotEqual(
            (self.model_path / "am" / "final.mdl").read_bytes(), b"an older install"
        )
        self.assertFalse((self.model_path / "stale-file").exists(), "the swap must not merge")
        self.assertEqual(self.stamp.read_text().strip(), self.digest)

    def test_no_scratch_directories_are_left_behind(self):
        self._install()
        leftovers = [p.name for p in self.models_dir.iterdir() if p.name != self.MODEL_NAME]
        self.assertEqual(leftovers, [])


class TestReleaseWithoutAManifest(unittest.TestCase):
    """install.sh comes from main; the tree it clones is the last release tag.

    An absent manifest means the release predates pinning, so models are left to
    first run. A manifest that omits a model still fails closed.
    """

    SOURCE = INSTALL_SH.read_text()

    PRELUDE = """
set -uo pipefail
print_info() { echo "INFO: $*"; }
print_warning() { echo "WARNING: $*"; }
print_error() { echo "ERROR: $*"; }
print_success() { echo "SUCCESS: $*"; }
command_exists() { command -v "$1" >/dev/null 2>&1; }
check_connectivity() { return 0; }
download_model_file() { echo "DOWNLOAD ATTEMPTED"; return 1; }
"""

    def _function_body(self, name: str) -> str:
        start = self.SOURCE.index(f"\n{name}() {{")
        end = self.SOURCE.index("\n}\n", start) + len("\n}\n")
        return self.SOURCE[start:end]

    def _run(self, script: str, functions=()) -> subprocess.CompletedProcess:
        body = self.PRELUDE + "\n".join(self._function_body(n) for n in functions)
        return subprocess.run(["bash", "-c", body + "\n" + script], capture_output=True, text=True)

    def test_available_when_the_manifest_ships(self):
        result = self._run(
            f'MODEL_CHECKSUMS_FILE="{REPO_ROOT}/src/vocalinux/utils/model_checksums.txt"; '
            "model_verification_available",
            functions=("model_verification_available",),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unavailable_when_the_release_predates_pinning(self):
        with TemporaryDirectory() as tmp:
            result = self._run(
                f'MODEL_CHECKSUMS_FILE="{tmp}/nope.txt"; model_verification_available',
                functions=("model_verification_available",),
            )
        self.assertEqual(result.returncode, 1)

    def test_vosk_refuses_before_spending_the_download(self):
        """The 40MB fetch must not happen when nothing can verify it."""
        with TemporaryDirectory() as tmp:
            result = self._run(
                f'DATA_DIR="{tmp}/data"; VOCALINUX_TMP_DIR="{tmp}/tmp"; '
                f'mkdir -p "$DATA_DIR" "$VOCALINUX_TMP_DIR"; '
                f'MODEL_CHECKSUMS_FILE="{tmp}/nope.txt"; '
                "install_vosk_models; echo RC=$?",
                functions=("pinned_digest_for", "install_vosk_models"),
            )
        out = result.stdout + result.stderr
        self.assertIn("RC=1", out)
        self.assertIn("No checksum is pinned", out)
        self.assertNotIn("DOWNLOAD ATTEMPTED", out, "refused only after downloading 40MB")

    def _model_install_block(self) -> str:
        """The top-level section deciding which models are pre-downloaded."""
        start = self.SOURCE.index("# Install models based on selected engine")
        end = self.SOURCE.index("# config.json survives reinstalls", start)
        return self.SOURCE[start:end]

    def test_the_manifest_dependent_downloads_are_gated(self):
        """Both engines whose digests live in the manifest sit behind the gate."""
        block = self._model_install_block()
        for call in ("install_whispercpp_model ||", "install_vosk_models ||"):
            gate = block.rindex("if model_verification_available; then", 0, block.index(call))
            self.assertLess(gate, block.index(call), f"{call} is not behind the gate")

    def test_openai_whisper_stays_ungated(self):
        """It verifies against the sha256 in its own URL, so needs no manifest."""
        block = self._model_install_block()
        call = block.index("install_whisper_model ||")
        preceding = block[:call]
        self.assertGreater(
            preceding.rindex("fi"),
            preceding.rindex("if model_verification_available; then"),
            "the OpenAI Whisper download must not be behind the manifest gate",
        )

    def test_the_skew_is_explained_once(self):
        block = self._model_install_block()
        self.assertEqual(
            block.count("if ! model_verification_available; then"),
            1,
            "the reason models are skipped should be stated once, not per engine",
        )


if __name__ == "__main__":
    unittest.main()
