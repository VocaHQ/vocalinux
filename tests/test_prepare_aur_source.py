"""Behavioral checks for the AUR source/provenance publication boundary."""

from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import tarfile
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/prepare_aur_source.py"
COMMIT = "a" * 40


@pytest.fixture
def prepare_tool() -> ModuleType:
    """Load the standalone release helper without importing the application."""
    spec = importlib.util.spec_from_file_location("prepare_aur_source", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sdist(
    directory: Path,
    version: str = "0.18.4",
    metadata: str | None = None,
    extra: tuple[str, ...] = (),
) -> Path:
    """Write a small real sdist with independently controllable metadata/members."""
    path = directory / f"vocalinux-{version}.tar.gz"
    info = metadata if metadata is not None else f"Name: vocalinux\nVersion: {version}\n"
    with tarfile.open(path, "w:gz") as archive:
        for name, text in [(f"vocalinux-{version}/PKG-INFO", info)] + [
            (name, "payload") for name in extra
        ]:
            member = tarfile.TarInfo(name)
            payload = text.encode()
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    return path


def manifest(directory: Path, tool: ModuleType, archive: Path) -> Path:
    """Pin the exact source bytes, like a published release manifest."""
    path = directory / "SHA256SUMS"
    path.write_text(f"{tool.digest(archive)}  {archive.name}\n")
    return path


@pytest.mark.parametrize(
    "tag,version,pkgver",
    [
        ("v0.18.4", "0.18.4", "0.18.4"),
        ("v0.19.0-beta.1", "0.19.0b1", "0.19.0beta.1"),
        ("v0.19.0-rc1", "0.19.0rc1", "0.19.0rc1"),
    ],
)
def test_local_fixture_pins_original_bytes_and_preserves_prerelease_tag(
    prepare_tool: ModuleType, tmp_path: Path, tag: str, version: str, pkgver: str
) -> None:
    archive = sdist(tmp_path, version)
    output = tmp_path / "prepared"
    prepare_tool.prepare(archive, output, tag=tag, local_unattested=True)
    assert (output / archive.name).read_bytes() == archive.read_bytes()
    # Evaluate the real PKGBUILD with bash, including source variable expansion.
    values = subprocess.check_output(
        [
            "bash",
            "-c",
            'source "$1"; printf "%s\\n" "$pkgver" "$_tag" "$_version" "${source[0]}" "${sha256sums[0]}"',
            "bash",
            str(output / "PKGBUILD"),
        ],
        text=True,
    ).splitlines()
    assert values == [
        pkgver,
        tag[1:],
        version,
        f"{archive.name}::https://github.com/VocaHQ/vocalinux/releases/download/{tag}/{archive.name}",
        prepare_tool.digest(archive),
    ]


def test_release_verifies_identity_ref_commit_and_bytes_before_staging(
    prepare_tool: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = sdist(tmp_path)
    sums = manifest(tmp_path, prepare_tool, archive)
    output = tmp_path / "prepared"

    def verified(argv: list[str], **kwargs: object) -> None:
        assert not output.exists()
        assert kwargs == {"check": True}
        assert argv == [
            "gh",
            "attestation",
            "verify",
            str(archive),
            "--repo",
            "VocaHQ/vocalinux",
            "--signer-workflow",
            "VocaHQ/vocalinux/.github/workflows/release.yml",
            "--source-ref",
            "refs/tags/v0.18.4",
            "--source-digest",
            COMMIT,
        ]

    check = Mock(side_effect=verified)
    monkeypatch.setattr(prepare_tool.subprocess, "run", check)
    prepare_tool.prepare(archive, output, "v0.18.4", sums, COMMIT)
    check.assert_called_once()
    assert sorted(path.name for path in output.iterdir()) == ["PKGBUILD", archive.name]


@pytest.mark.parametrize("problem", ["missing", "wrong", "duplicate", "skip", "mixed"])
def test_bad_or_unpinned_checksum_fails_before_attestation_or_staging(
    prepare_tool: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str
) -> None:
    archive = sdist(tmp_path)
    sums = manifest(tmp_path, prepare_tool, archive)
    good = sums.read_text()
    sums.write_text(
        {
            "missing": "",
            "wrong": f"{'0' * 64}  {archive.name}\n",
            "duplicate": good + good,
            "skip": f"SKIP  {archive.name}\n",
            "mixed": good + f"SKIP  {archive.name}\n",
        }[problem]
    )
    check = Mock()
    monkeypatch.setattr(prepare_tool.subprocess, "run", check)
    output = tmp_path / "prepared"
    with pytest.raises(ValueError, match="SHA256SUMS"):
        prepare_tool.prepare(archive, output, "v0.18.4", sums, COMMIT)
    check.assert_not_called()
    assert not output.exists()


def test_rejected_provenance_does_not_expose_publishable_inputs(
    prepare_tool: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = sdist(tmp_path)
    sums = manifest(tmp_path, prepare_tool, archive)
    check = Mock(side_effect=subprocess.CalledProcessError(1, ["gh", "attestation", "verify"]))
    monkeypatch.setattr(prepare_tool.subprocess, "run", check)
    output = tmp_path / "prepared"
    with pytest.raises(subprocess.CalledProcessError):
        prepare_tool.prepare(archive, output, "v0.18.4", sums, COMMIT)
    assert not output.exists()


def test_source_changes_after_verification_are_rejected(
    prepare_tool: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = sdist(tmp_path)
    sums = manifest(tmp_path, prepare_tool, archive)
    check = Mock(
        side_effect=lambda *args, **kwargs: archive.write_bytes(b"changed after verification")
    )
    monkeypatch.setattr(prepare_tool.subprocess, "run", check)
    output = tmp_path / "prepared"
    with pytest.raises(ValueError, match="changed while staging"):
        prepare_tool.prepare(archive, output, "v0.18.4", sums, COMMIT)
    assert not output.exists()


@pytest.mark.parametrize(
    "kwargs,with_manifest,error",
    [
        ({}, False, "requires --manifest"),
        ({"commit": COMMIT}, False, "requires --manifest"),
        ({}, True, "requires --manifest"),
        ({"commit": "abc"}, True, "full source commit"),
        ({"tag": "v0.18.3"}, False, "tag and sdist"),
        ({"tag": "v0.18.4;echo unsafe"}, False, "tag and sdist"),
        ({"tag": "v0.18.4-"}, False, "Invalid version"),
    ],
)
def test_release_verification_cannot_be_silently_skipped(
    prepare_tool: ModuleType,
    tmp_path: Path,
    kwargs: dict[str, str],
    with_manifest: bool,
    error: str,
) -> None:
    archive = sdist(tmp_path)
    output = tmp_path / "prepared"
    arguments = {"tag": "v0.18.4", **kwargs}
    if with_manifest:
        arguments["manifest"] = manifest(tmp_path, prepare_tool, archive)
    with pytest.raises(ValueError, match=error):
        prepare_tool.prepare(archive, output, **arguments)
    assert not output.exists()


@pytest.mark.parametrize(
    "metadata,extra",
    [
        ("Name: other\nVersion: 0.18.4\n", ()),
        ("Name: vocalinux\nVersion: 0.18.3\n", ()),
        ("Name: vocalinux\nVersion: 0.18.4\nVersion: 0.18.3\n", ()),
        (None, ("other-root/file",)),
        (None, ("vocalinux-0.18.4/../unsafe",)),
        (None, ("vocalinux-0.18.4/PKG-INFO",)),
    ],
)
def test_wrong_or_ambiguous_archive_metadata_is_rejected(
    prepare_tool: ModuleType, tmp_path: Path, metadata: str | None, extra: tuple[str, ...]
) -> None:
    archive = sdist(tmp_path, metadata=metadata, extra=extra)
    with pytest.raises(ValueError):
        prepare_tool.prepare(archive, tmp_path / "prepared", local_unattested=True)


def test_existing_outputs_are_not_overwritten(prepare_tool: ModuleType, tmp_path: Path) -> None:
    archive = sdist(tmp_path)
    output = tmp_path / "prepared"
    output.mkdir()
    user_file = output / "keep.txt"
    user_file.write_text("user work")
    with pytest.raises(ValueError, match="output already exists"):
        prepare_tool.prepare(archive, output, local_unattested=True)
    assert user_file.read_text() == "user work"


def test_local_mode_rejects_release_verification_arguments(
    prepare_tool: ModuleType, tmp_path: Path
) -> None:
    archive = sdist(tmp_path)
    with pytest.raises(ValueError, match="cannot take release verification"):
        prepare_tool.prepare(archive, tmp_path / "prepared", commit=COMMIT, local_unattested=True)


def test_cli_failure_is_nonzero_and_leaves_no_publishable_file(tmp_path: Path) -> None:
    """An incomplete release invocation must not fall back to local fixture mode."""
    archive = sdist(tmp_path)
    output = tmp_path / "prepared"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--sdist",
            str(archive),
            "--tag",
            "v0.18.4",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "requires --manifest" in result.stderr
    assert not output.exists()
