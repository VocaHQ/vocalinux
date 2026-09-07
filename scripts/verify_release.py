#!/usr/bin/env python3
"""Check that a published release verifies as published.

The guards in tests/ read workflow files, so none of them can see what a
release looks like once its run has finished. This reads the release:

  manifest    SHA256SUMS is attached, lists every other asset, and its digests
              match the bytes GitHub stores
  provenance  every artifact the manifest lists resolves in the attestations API
  notes       the body still tells users how to check both
  pypi        the wheel and the sdist on PyPI are the bytes on the release

Nothing is downloaded: GitHub reports a sha256 for every asset it stores, and an
asset it reports none for fails rather than being skipped.

Usage: scripts/verify_release.py [tag]   (default: the latest stable release)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

MANIFEST = "SHA256SUMS"
PYPI_PROJECT = "vocalinux"
PYPI_SUFFIXES = (".whl", ".tar.gz")
PYPI_TIMEOUT = 30

#: Both commands the notes should hand the user, plus the file they act on.
NOTES_MUST_MENTION = ("sha256sum -c", "gh attestation verify", MANIFEST)

#: What `gh attestation verify` asks for, so this asks for the same. Pre-encoded:
#: `gh api` reads an unescaped `://` in a query as a protocol and refuses.
SLSA_PROVENANCE = "https%3A%2F%2Fslsa.dev%2Fprovenance%2Fv1"


def _gh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def _gh_ok(*args: str) -> str:
    done = _gh(*args)
    if done.returncode != 0:
        raise SystemExit(f"gh {' '.join(args)} failed:\n{done.stderr.strip()}")
    return done.stdout


def repo_slug() -> str:
    slug = os.environ.get("GITHUB_REPOSITORY")
    return slug or json.loads(_gh_ok("repo", "view", "--json", "nameWithOwner"))["nameWithOwner"]


def _release_from_api(payload: dict) -> dict:
    """Map a Releases REST payload onto the field names the rest of this script uses."""
    return {
        "tagName": payload["tag_name"],
        "body": payload.get("body"),
        "isDraft": payload["draft"],
        "isPrerelease": payload["prerelease"],
        "assets": payload.get("assets") or [],
    }


def fetch_release(tag: str | None) -> dict:
    """The latest stable release, or the one named by tag. `0.16.2` is accepted
    as well as `v0.16.2`, since that is how the version is usually written.

    Digests come from the Releases REST API (`gh api`), not `gh release view
    --json assets`. On gh 2.46 (common in distro packages, and what
    `just verify-release` often runs) view's asset objects have no digest
    field at all, so every asset would fail as undigested. The REST payload
    includes `digest` for assets GitHub stores a hash for.
    """
    slug = repo_slug()
    candidates = [tag] + ([f"v{tag}"] if tag and tag[0].isdigit() else [])
    errors: list[str] = []
    for candidate in candidates:
        path = (
            f"/repos/{slug}/releases/tags/{candidate}"
            if candidate
            else f"/repos/{slug}/releases/latest"
        )
        done = _gh("api", path)
        if done.returncode == 0:
            return _release_from_api(json.loads(done.stdout))
        detail = (done.stderr or done.stdout or "").strip()
        errors.append(f"{path}: {detail or f'exit {done.returncode}'}")
    named = " or ".join(c for c in candidates if c) or "the latest stable release"
    hint = "\n".join(errors)
    raise SystemExit(
        f"no release found for {named}\n{hint}\nusage: verify_release.py [tag], e.g. v0.16.2"
    )


def parse_manifest(text: str) -> dict[str, str]:
    """`<digest>  <name>` per line, as sha256sum writes and reads it."""
    entries = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise ValueError(f"{MANIFEST} line {number} is not `<digest>  <name>`: {line!r}")
        # Binary mode marks the name with a leading star, which is not the name.
        entries[parts[1].strip().lstrip("*")] = parts[0].strip().lower()
    return entries


def asset_digests(assets: list[dict]) -> tuple[dict[str, str], list[str]]:
    """(name -> sha256, names GitHub reports no digest for)."""
    digests: dict[str, str] = {}
    undigested: list[str] = []
    for asset in assets:
        raw = (asset.get("digest") or "").strip().lower()
        if raw.startswith("sha256:"):
            digests[asset["name"]] = raw.split(":", 1)[1]
        else:
            undigested.append(asset["name"])
    return digests, undigested


def check_manifest(stored: dict, manifest: dict, undigested: list) -> list[str]:
    """Both directions: a missing line reads as tampering to anyone running
    `sha256sum -c`, and an extra one is a promise nothing keeps."""
    covered, listed = set(stored) - {MANIFEST}, set(manifest)
    return (
        [f"GitHub reports no digest for {name}" for name in undigested if name != MANIFEST]
        + [f"{name} is published but absent from {MANIFEST}" for name in sorted(covered - listed)]
        + [f"{MANIFEST} lists {name}, which is not an asset" for name in sorted(listed - covered)]
        + [
            f"{name}: {MANIFEST} says {manifest[name]}, GitHub stores {stored[name]}"
            for name in sorted(covered & listed)
            if manifest[name] != stored[name]
        ]
    )


def check_provenance(slug: str, manifest: dict[str, str]) -> list[str]:
    """The manifest is the subject-checksums input, so it is not a subject itself."""
    problems = []
    for name, digest in sorted(manifest.items()):
        query = f"/repos/{slug}/attestations/sha256:{digest}"
        done = _gh("api", f"{query}?predicate_type={SLSA_PROVENANCE}")
        try:
            bundles = json.loads(done.stdout).get("attestations") if done.returncode == 0 else None
        except json.JSONDecodeError:
            bundles = None
        if not bundles:
            problems.append(f"{name} has no build provenance")
    return problems


def check_notes(body: str | None) -> list[str]:
    # GitHub returns JSON null for an empty body; treat that as missing notes.
    text = body or ""
    return [f"the notes never mention `{p}`" for p in NOTES_MUST_MENTION if p not in text]


def check_pypi(version: str, stored: dict[str, str]) -> list[str]:
    expected = {n: d for n, d in stored.items() if n.endswith(PYPI_SUFFIXES)}
    # Per suffix: a release that lost its sdist would otherwise pass on the wheel.
    problems = [
        f"the release carries no {suffix} to compare against PyPI"
        for suffix in PYPI_SUFFIXES
        if not any(name.endswith(suffix) for name in expected)
    ]
    if not expected:
        return problems

    # Past the early return, and not at module scope: urllib.error reaches
    # tempfile, which two tests here leave as a MagicMock in sys.modules.
    import urllib.error
    import urllib.request

    try:
        url = f"https://pypi.org/pypi/{PYPI_PROJECT}/{version}/json"
        with urllib.request.urlopen(url, timeout=PYPI_TIMEOUT) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return problems + [f"PyPI has no {PYPI_PROJECT} {version}"]
        raise
    published = {i["filename"]: i["digests"]["sha256"].lower() for i in payload["urls"]}

    for name, digest in sorted(expected.items()):
        if name not in published:
            problems.append(f"{name} is on the release but not on PyPI")
        elif published[name] != digest:
            problems.append(f"{name}: PyPI serves {published[name]}, the release serves {digest}")
    return problems


def report(results: list[tuple[str, list[str]]]) -> bool:
    width = max(len(label) for label, _ in results)
    for label, problems in results:
        print(f"  {label.ljust(width)}  {'FAIL' if problems else 'PASS'}")
        for problem in problems:
            print(f"  {' ' * width}    {problem}")
    return not any(problems for _, problems in results)


def main(argv: list[str]) -> int:
    tag = argv[1] if len(argv) > 1 and argv[1] else None
    slug = repo_slug()
    release = fetch_release(tag)

    if release["isDraft"] or release["isPrerelease"]:
        # Nightlies never go through publish-checksums and carry no manifest.
        print(f"{release['tagName']} is not a published stable release")
        return 1

    tag = release["tagName"]
    stored, undigested = asset_digests(release["assets"])
    print(f"Verifying {slug} {tag}, {len(release['assets'])} assets\n")

    if MANIFEST not in stored and MANIFEST not in undigested:
        results = [("manifest", [f"{tag} has no {MANIFEST} attached"])]
    else:
        text = _gh_ok("release", "download", tag, "--pattern", MANIFEST, "--output", "-")
        manifest = parse_manifest(text)
        results = [
            ("manifest", check_manifest(stored, manifest, undigested)),
            ("provenance", check_provenance(slug, manifest)),
            ("notes", check_notes(release["body"])),
            ("pypi", check_pypi(tag.removeprefix("v"), stored)),
        ]

    ok = report(results)
    print(f"\n{tag} {'verifies' if ok else 'does not verify'} as published")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
