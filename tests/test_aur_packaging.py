"""Regression guards for the AUR packaging and its build gate.

#757 reached AUR users because no CI ever ran makepkg on the PKGBUILD before
a tag pushed it to them — and a PKGBUILD change triggered zero jobs in the
first place, because no paths filter matched packaging/aur/**.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AUR = REPO_ROOT / "packaging" / "aur"
PKGBUILD = AUR / "vocalinux" / "PKGBUILD"
GATE_SH = AUR / "build-test.sh"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
PIPELINE = WORKFLOWS / "unified-pipeline.yml"
RELEASE = WORKFLOWS / "release.yml"
RUNTIME_EXPORT = REPO_ROOT / "requirements" / "runtime.txt"

#: depends entries no Arch repo can provide: python-pywhispercpp is a virtual
#: name the AUR -cpu/-cuda/-rocm backends provide (#579), python-pynput lives
#: in the AUR. The gate satisfies them with a stub package; adding another
#: AUR-resolved name to the PKGBUILD means adding it here too.
AUR_RESOLVED = ("python-pywhispercpp", "python-pynput")


def _pipeline_text() -> str:
    return PIPELINE.read_text(encoding="utf-8")


def _job_block(workflow_text: str, job: str) -> str:
    """The job's lines, from its key to the next key at the same indent."""
    lines = workflow_text.splitlines(keepends=True)
    start = next(
        (i for i, line in enumerate(lines) if line.rstrip("\n") == f"  {job}:"),
        None,
    )
    assert start is not None, f"no {job} job in the workflow"
    block = [lines[start]]
    for line in lines[start + 1 :]:
        # The next job starts at two-space indent; deeper lines belong to us.
        if re.match(r"^  \S", line):
            break
        block.append(line)
    return "".join(block)


def _aur_depends() -> set:
    """The depends=() entries of the PKGBUILD, one per line by convention."""
    lines = PKGBUILD.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("depends=("))
    names = set()
    for line in lines[start + 1 :]:
        if line.strip() == ")":
            break
        match = re.match(r"\s*'([^']+)'", line)
        assert match, f"depends=() entry '{line}' is not one-per-line quoted"
        names.add(match.group(1))
    return names


def test_aur_changes_reach_ci():
    """The bug that let the channel break silently: packaging/aur/** matched
    no paths filter, so a PKGBUILD change started zero jobs."""
    text = _pipeline_text()
    assert re.search(r"^            aur:\n", text, re.M), (
        "unified-pipeline.yml has no aur filter; PKGBUILD changes again start" " zero jobs"
    )
    aur_block = re.search(r"^            aur:\n((?:\s+- '[^']+'\n)+)", text, re.M)
    assert "packaging/aur/**" in aur_block.group(1)
    # The filter's output has to be consumed, or the job never runs.
    assert "aur: ${{ steps.filter.outputs.aur }}" in text


def test_the_gate_runs_on_python_changes_and_aur_changes():
    """depends=() mirrors pyproject.toml, so every python change must reach
    the AUR gate; the dedicated aur filter exists so a PKGBUILD-only change
    runs it without dragging the whole python matrix along."""
    block = _job_block(_pipeline_text(), "aur-build-test")
    assert "needs.changes.outputs.python == 'true'" in block
    assert "needs.changes.outputs.aur == 'true'" in block
    assert "packaging/aur/build-test.sh" in block, "the job must run the gate"
    assert "archlinux" in block, "the gate builds on Arch, not the runner"


def test_the_gate_builds_this_commit_not_the_last_tag():
    """The published source= points at the tag tarball, which does not exist
    until the tag is pushed — the reason nothing could run the PKGBUILD on a
    PR. The gate swaps it for a git archive of HEAD under the same filename
    and the same directory prefix build()/package() cd into."""
    script = GATE_SH.read_text(encoding="utf-8")
    pkgbuild = PKGBUILD.read_text(encoding="utf-8")

    assert "git archive" in script and '--prefix="${pkgname}-${_tag}/"' in script
    assert re.search(r'cd "\$\{pkgname\}-\$\{_tag\}"', pkgbuild), (
        "build()/package() no longer cd into ${pkgname}-${_tag}; the gate's"
        " archive prefix and the PKGBUILD must agree"
    )
    # The substitution itself.
    assert re.search(r"s\|\^source=.*\|source=", script)

    # And the published PKGBUILD still fetches the tag archive — if that
    # changes, updpkgsums at publish time and this gate both need a relook.
    assert "archive/refs/tags/v${_tag}.tar.gz" in pkgbuild
    assert "sha256sums=('SKIP')" in pkgbuild
    assert "updpkgsums: 'true'" in RELEASE.read_text(encoding="utf-8"), (
        "release.yml no longer computes the digest at publish time; the"
        " sha256sums=('SKIP') in the repo would ship to users"
    )


def test_the_gate_uses_a_non_root_build_user():
    """makepkg refuses to run as root; the gate must drop privileges."""
    script = GATE_SH.read_text(encoding="utf-8")
    assert "useradd" in script
    assert re.search(r"runuser -u \w+ -- makepkg", script)


def test_namcap_covers_both_the_pkgbuild_and_the_package_and_fails_on_errors():
    """namcap is noisy about lazy imports and virtual depends, so the gate
    fails on E tags only — but it must run on both targets to be worth its
    output."""
    script = GATE_SH.read_text(encoding="utf-8")
    assert 'check_namcap "$BUILD/PKGBUILD"' in script
    assert 'check_namcap "$BUILD"/*.pkg.tar.*' in script
    assert "grep -q ' E: '" in script


def test_the_stub_matches_the_aur_resolved_depends():
    """makepkg verifies every depends entry, so the gate's stub has to
    provide exactly the names no repo can. A name the stub still provides
    that the PKGBUILD dropped, or a new AUR-resolved dep the stub does not
    know, fails the gate at pacman -Sy — loudly, but far from the cause."""
    script = GATE_SH.read_text(encoding="utf-8")
    names = _aur_depends()

    for name in AUR_RESOLVED:
        assert name in names, (
            f"{name} is satisfied by the gate's stub but no longer depended"
            " on; update AUR_RESOLVED in both the script and this test"
        )
        assert f"'{name}'" in script, (
            f"{name} is AUR-resolved but the gate's stub does not provide it;"
            " makepkg will fail on dependency verification"
        )


def test_the_smoke_walks_the_pinned_deps():
    """The import smoke runs the two AUR-resolved deps from the hash-pinned
    export (under their PyPI names), not from whatever AUR ships, so the pin
    has to exist there."""
    script = GATE_SH.read_text(encoding="utf-8")
    export = RUNTIME_EXPORT.read_text(encoding="utf-8")

    assert "requirements/runtime.txt" in script
    assert "--require-hashes" in script
    assert "pacman -U" in script and "vocalinux --version" in script
    # Arch name -> PyPI name for the export the gate installs from.
    pypi_names = {"python-pywhispercpp": "pywhispercpp", "python-pynput": "pynput"}
    for arch_name, pypi_name in pypi_names.items():
        assert arch_name in AUR_RESOLVED or arch_name in _aur_depends()
        assert re.search(rf"^{pypi_name}==\S+ \\", export, re.M), (
            f"{pypi_name} is not pinned in requirements/runtime.txt; the smoke"
            " would have nothing versioned to install"
        )


def test_the_pkgbuild_builds_without_isolation_on_distro_setuptools():
    """#757: the PKGBUILD builds --no-isolation against Arch's setuptools
    (84 at the time), which is why the setuptools upper cap had to come off
    pyproject.toml. Switching to an isolated build is a decision that
    changes what the gate proves, not a slip to make in passing."""
    pkgbuild = PKGBUILD.read_text(encoding="utf-8")
    assert "--no-isolation" in pkgbuild
