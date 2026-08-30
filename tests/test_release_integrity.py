"""Guard what a published release promises about itself.

v0.16.1 shipped four assets — two AppImages of ~100 MB, a wheel and an sdist —
with no checksum, no signature and no provenance, in a project that pins the
digest of all 67 models it downloads. It also built the same version three times
on three runners (`build-and-release`, `build-appimage-arm64`, `publish-pypi`),
so the wheel on PyPI was never the wheel on the GitHub release, and a checksum
for one would not have described the other.

These tests pin the shape of the fix: build once, publish that, and cover every
artifact with one manifest. Parsed as text rather than YAML on purpose — the
sibling workflow guards do the same, and the only YAML parser on hand reaches
the venv transitively through pre-commit.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE = REPO_ROOT / ".github" / "workflows" / "release.yml"

#: The artifact holding the wheel and sdist that every other job consumes.
DIST_ARTIFACT = "python-dist"


def _text() -> str:
    return RELEASE.read_text(encoding="utf-8")


def _without_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _jobs() -> dict:
    """job name -> its block of the workflow, split on the 2-space indent."""
    text = _text()
    start = text.index("\njobs:\n")
    headers = list(re.finditer(r"^  ([a-z0-9][a-z0-9-]*):$", text[start:], re.M))
    assert headers, "no jobs found; release.yml's layout moved"

    jobs = {}
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text) - start
        jobs[header.group(1)] = text[start:][header.start() : end]
    return jobs


def _needs(block: str) -> set:
    match = re.search(r"^    needs: (.+)$", block, re.M)
    if not match:
        return set()
    return set(re.findall(r"[a-z0-9][a-z0-9-]*", match.group(1)))


def _permissions(block: str) -> dict:
    match = re.search(r"^    permissions:\n((?:      \S+: \S+.*\n)+)", block, re.M)
    if not match:
        return {}
    return dict(re.findall(r"^      (\S+): (\S+)", match.group(1), re.M))


def _top_level_permissions() -> dict:
    text = _text()
    match = re.search(r"^permissions:\n((?:  \S+: \S+.*\n)+)", text, re.M)
    assert match, "release.yml declares no top-level permissions"
    return dict(re.findall(r"^  (\S+): (\S+)", match.group(1), re.M))


def test_the_release_is_built_exactly_once():
    """Three builds meant three sets of bytes and no `SOURCE_DATE_EPOCH`, so
    neither a checksum nor an attestation could speak for the whole release."""
    builds = _without_comments(_text()).count("python -m build")
    assert builds == 1, f"the release is built {builds} times; build once and pass the artifact"


def test_the_build_timestamp_is_pinned_to_the_tagged_commit():
    """Otherwise re-running the tag produces bytes the published checksum no
    longer matches."""
    block = _jobs()["build-and-release"]
    assert "SOURCE_DATE_EPOCH=" in block
    assert block.index("SOURCE_DATE_EPOCH=") < block.index(
        "python -m build\n"
    ), "SOURCE_DATE_EPOCH is set after the build, which is the same as not setting it"


def test_every_consumer_downloads_the_build_instead_of_repeating_it():
    jobs = _jobs()
    for name in ("build-appimage-arm64", "publish-pypi"):
        block = jobs[name]
        assert "actions/download-artifact" in block, f"{name} does not consume the build"
        assert f"name: {DIST_ARTIFACT}" in block, f"{name} downloads some other artifact"
        assert "python -m build" not in _without_comments(
            block
        ), f"{name} rebuilds what build-and-release already published"


def _jobs_that_attach_to_the_release() -> set:
    return {
        name
        for name, block in _jobs().items()
        if "gh release upload" in block or "softprops/action-gh-release" in block
    }


def test_the_manifest_waits_for_every_artifact_it_has_to_cover():
    """A SHA256SUMS listing three of the four files is worse than none: the
    missing one is indistinguishable from a tampered one. The aarch64 AppImage
    lands in its own job after the release exists, which is what makes this
    ordering a real constraint rather than a formality."""
    jobs = _jobs()
    assert "publish-checksums" in jobs, "nothing generates a checksum manifest"

    producers = _jobs_that_attach_to_the_release() - {"publish-checksums"}
    missing = producers - _needs(jobs["publish-checksums"])
    assert not missing, f"publish-checksums runs before {sorted(missing)} attach their artifacts"


def test_the_manifest_covers_every_kind_of_artifact_we_publish():
    block = _jobs()["publish-checksums"]
    assert "merge-multiple: true" in block, "it collects one artifact, not all of them"
    checksum_line = re.search(r"sha256sum -- (.+)$", block, re.M)
    assert checksum_line, "publish-checksums does not generate SHA256SUMS"
    for pattern in ("*.whl", "*.tar.gz", "*.AppImage"):
        assert pattern in checksum_line.group(1), f"{pattern} is published but unchecksummed"


def test_provenance_is_generated_from_the_published_manifest():
    """Attesting a second glob would let the file users check and the set we
    attest drift apart."""
    block = _jobs()["publish-checksums"]
    assert "actions/attest-build-provenance" in block, "no build provenance is generated"
    assert (
        "subject-checksums: dist/SHA256SUMS" in block
    ), "provenance is not driven by the manifest we publish"
    assert _permissions(block).get("attestations") == "write"


def test_pypi_is_published_without_a_stored_token():
    text = _text()
    assert "PYPI_API_TOKEN" not in text, "trusted publishing needs no API token"
    assert "TWINE_PASSWORD" not in text
    block = _jobs()["publish-pypi"]
    assert "pypa/gh-action-pypi-publish" in block
    assert _permissions(block).get("id-token") == "write"


def test_only_the_jobs_that_need_it_can_mint_an_oidc_token():
    """`id-token: write` at the top level handed one to publish-aur too, which
    runs a third-party action holding our AUR signing key."""
    assert "id-token" not in _top_level_permissions()
    minters = {
        name for name, block in _jobs().items() if _permissions(block).get("id-token") == "write"
    }
    assert minters == {"publish-pypi", "publish-checksums"}, minters


def test_the_release_notes_tell_users_how_to_verify_the_download():
    """Publishing a manifest nobody is told about verifies nothing."""
    body = _jobs()["build-and-release"]
    assert "SHA256SUMS" in body, "the release notes never mention the manifest"
    assert "sha256sum -c" in body, "the notes do not show how to check it"
    assert "gh attestation verify" in body, "the notes do not show how to check provenance"
