"""Guards for scripts/verify_release.py.

Only the comparisons that carry real logic, plus the one property of the
workflow that is worth pinning. Asserting that the yml says what the yml says
is the antipattern verify_release.py exists to work around.
"""

import importlib.util
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "verify-release.yml"
SCRIPT = REPO_ROOT / "scripts" / "verify_release.py"

_spec = importlib.util.spec_from_file_location("verify_release", SCRIPT)
verify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify)


def test_the_dispatch_input_never_reaches_the_shell():
    """Interpolating it into `run:` splices caller text into a script that
    holds a token. Through the environment it stays a value."""
    text = WORKFLOW.read_text(encoding="utf-8")
    run_lines = [line for line in text.splitlines() if re.match(r"^\s*-?\s*run:", line)]
    assert run_lines, "found no run: step, so this guard is scanning nothing"
    for line in run_lines:
        assert "${{" not in line, f"a run: step interpolates a template expression: {line.strip()}"
    assert 'python3 scripts/verify_release.py "$TAG"' in text


def test_the_manifest_parses_as_sha256sum_writes_it():
    parsed = verify.parse_manifest(
        "0ee0d8e6  Vocalinux-0.16.2-x86_64.AppImage\n22deb51a *vocalinux-0.16.2.whl\n\n"
    )
    assert parsed == {
        "Vocalinux-0.16.2-x86_64.AppImage": "0ee0d8e6",
        "vocalinux-0.16.2.whl": "22deb51a",
    }


def test_an_asset_missing_from_the_manifest_fails():
    """The case that reads as tampering to anyone running `sha256sum -c`."""
    problems = verify.check_manifest(
        {"a.AppImage": "aa", "b.flatpak": "bb", verify.MANIFEST: "cc"}, {"a.AppImage": "aa"}, []
    )
    assert any("b.flatpak is published but absent" in problem for problem in problems)


def test_a_manifest_line_with_no_asset_behind_it_fails():
    """How a hand edit adds a promise nothing keeps."""
    problems = verify.check_manifest(
        {"a.AppImage": "aa", verify.MANIFEST: "cc"},
        {"a.AppImage": "aa", "ghost.flatpak": "bb"},
        [],
    )
    assert any("which is not an asset" in problem for problem in problems)


def test_a_digest_that_disagrees_with_the_stored_bytes_fails():
    problems = verify.check_manifest({"a.AppImage": "aa"}, {"a.AppImage": "bb"}, [])
    assert any("GitHub stores aa" in problem for problem in problems)


def test_an_asset_with_no_digest_fails_rather_than_being_skipped():
    """The manifest's own digest is never checked, so it is not reported."""
    problems = verify.check_manifest({}, {}, ["mystery.snap", verify.MANIFEST])
    assert problems == ["GitHub reports no digest for mystery.snap"]


def test_a_manifest_that_matches_the_release_passes():
    assert not verify.check_manifest(
        {"a.AppImage": "aa", "b.flatpak": "bb", verify.MANIFEST: "cc"},
        {"a.AppImage": "aa", "b.flatpak": "bb"},
        [],
    )


def test_notes_without_the_verification_block_fail():
    """v0.16.2 published a manifest and told nobody it existed."""
    assert verify.check_notes("Download the AppImage and run it.")
    assert not verify.check_notes(
        "Check it with `sha256sum -c --ignore-missing SHA256SUMS`, then `gh attestation verify`."
    )


def test_provenance_asks_only_for_slsa_build_provenance(monkeypatch):
    """Unfiltered, an SBOM would read as the provenance users are told to expect."""

    class Done:
        returncode = 0
        stdout = '{"attestations": [{}]}'

    asked = []

    def fake_gh(*args):
        asked.append(args[-1])
        return Done()

    monkeypatch.setattr(verify, "_gh", fake_gh)
    assert not verify.check_provenance("owner/repo", {"a.whl": "aa"})
    assert f"predicate_type={verify.SLSA_PROVENANCE}" in asked[0]


def test_a_release_missing_a_distribution_names_it():
    """Comparing only what is left would pass while PyPI serves an unchecked file."""
    assert verify.check_pypi("0.16.2", {"Vocalinux-0.16.2-x86_64.AppImage": "aa"}) == [
        "the release carries no .whl to compare against PyPI",
        "the release carries no .tar.gz to compare against PyPI",
    ]


def test_github_digests_are_read_without_their_algorithm_prefix():
    stored, undigested = verify.asset_digests(
        [{"name": "a.AppImage", "digest": "sha256:AABB"}, {"name": "b.snap"}]
    )
    assert stored == {"a.AppImage": "aabb"}
    assert undigested == ["b.snap"]


def test_a_null_release_body_fails_notes_without_typeerror():
    """GitHub serves JSON null for an empty body; that must be notes FAIL."""
    problems = verify.check_notes(None)
    assert problems
    assert all("never mention" in problem for problem in problems)


def test_fetch_release_reads_digests_from_the_rest_api(monkeypatch):
    """`gh release view --json assets` omits digest on gh 2.46; REST does not."""

    class Done:
        returncode = 0
        stdout = ""
        stderr = ""

        def __init__(self, stdout=""):
            self.stdout = stdout

    calls = []

    def fake_gh(*args):
        calls.append(args)
        assert args[:2] == ("api", "/repos/VocaHQ/vocalinux/releases/tags/v0.16.2")
        payload = {
            "tag_name": "v0.16.2",
            "body": "sha256sum -c and gh attestation verify via SHA256SUMS",
            "draft": False,
            "prerelease": False,
            "assets": [
                {"name": "a.AppImage", "digest": "sha256:AABB"},
                {"name": "b.snap", "digest": None},
            ],
        }
        return Done(stdout=json.dumps(payload))

    monkeypatch.setenv("GITHUB_REPOSITORY", "VocaHQ/vocalinux")
    monkeypatch.setattr(verify, "_gh", fake_gh)

    release = verify.fetch_release("v0.16.2")
    assert release["tagName"] == "v0.16.2"
    assert release["body"]
    assert release["isDraft"] is False
    assert release["isPrerelease"] is False
    stored, undigested = verify.asset_digests(release["assets"])
    assert stored == {"a.AppImage": "aabb"}
    assert undigested == ["b.snap"]
    assert all(args[0] == "api" for args in calls)
    assert not any(args[0] == "release" for args in calls)


def test_fetch_release_tries_v_prefix_then_surfaces_api_errors(monkeypatch):
    class Done:
        returncode = 1
        stdout = ""
        stderr = "HTTP 404: Not Found"

    paths = []

    def fake_gh(*args):
        paths.append(args[1])
        return Done()

    monkeypatch.setenv("GITHUB_REPOSITORY", "VocaHQ/vocalinux")
    monkeypatch.setattr(verify, "_gh", fake_gh)

    try:
        verify.fetch_release("0.16.2")
    except SystemExit as error:
        message = str(error)
    else:
        raise AssertionError("expected SystemExit")

    assert paths == [
        "/repos/VocaHQ/vocalinux/releases/tags/0.16.2",
        "/repos/VocaHQ/vocalinux/releases/tags/v0.16.2",
    ]
    assert "HTTP 404: Not Found" in message
    assert "no release found for 0.16.2 or v0.16.2" in message


def test_pypi_version_uses_removeprefix_not_lstrip():
    """lstrip('v') eats every leading v; removeprefix only the tag prefix."""
    import inspect

    source = inspect.getsource(verify.main)
    assert 'removeprefix("v")' in source
    assert 'lstrip("v")' not in source
